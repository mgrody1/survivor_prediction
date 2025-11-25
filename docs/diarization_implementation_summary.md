# Speaker Diarization Implementation Summary

## Overview

The speaker diarization pipeline processes Survivor TV episode video files to identify who is speaking when, aligned with subtitle text. This is an **optional feature** disabled by default because most users won't have access to source media files.

## Architecture

### Data Flow

```
Source Media → Audio Extraction → Diarization → Subtitle Alignment → Database Storage
     ↓               ↓                  ↓                ↓                    ↓
  .mkv files    ffmpeg extract    pyannote.audio   srt alignment    bronze.diarization_segments
```

### Storage Layer

Data is stored in the **bronze layer** (`bronze.diarization_segments`) with the following schema:

```sql
CREATE TABLE bronze.diarization_segments (
    version_season VARCHAR(10) NOT NULL,      -- e.g., "US01", "AU05"
    episode INT NOT NULL,                      -- Episode number within season
    subtitle_index INT NOT NULL,               -- Subtitle sequence number
    start_time NUMERIC(10,3) NOT NULL,         -- Segment start in seconds
    end_time NUMERIC(10,3) NOT NULL,           -- Segment end in seconds
    speaker_label VARCHAR(50) NOT NULL,        -- e.g., "SPEAKER_00"
    subtitle_text TEXT,                        -- Subtitle content
    word_count INT,                            -- Word count in subtitle
    ingest_run_id BIGINT NOT NULL,             -- FK to bronze.ingestion_runs

    -- Constraints
    UNIQUE (version_season, episode, subtitle_index),
    FOREIGN KEY (version_season) REFERENCES bronze.season_summary(version_season),
    FOREIGN KEY (version_season, episode) REFERENCES bronze.episodes(version_season, episode),
    FOREIGN KEY (ingest_run_id) REFERENCES bronze.ingestion_runs(run_id)
);
```

### Why Bronze Layer?

- **Raw data**: Contains minimally processed diarization output
- **Speaker labels**: Not yet mapped to actual castaway names (still "SPEAKER_00", etc.)
- **Future transformations**: Silver/gold layers can aggregate by castaway, compute speaking metrics, analyze dialogue patterns

## Configuration

### Environment Variables

All configuration is optional and disabled by default:

```bash
# Enable the feature (defaults to false)
ENABLE_DIARIZATION=false

# Required only if enabled
SURVIVOR_VIDEO_DIR=/path/to/videos          # Directory with .mkv files
SURVIVOR_SUBTITLE_DIR=/path/to/subtitles    # Directory with .srt files
SURVIVOR_AUDIO_OUT_DIR=data_cache/audio     # Where to cache extracted audio
HF_TOKEN=your_huggingface_token             # For pyannote.audio model access

# Optional configuration
VERSION_COUNTRY=US                           # For version_season format
PYANNOTE_DIARIZATION_MODEL=pyannote/speaker-diarization-3.1
USE_RAY=false                                # Distributed processing
RAY_ADDRESS=auto                             # Ray cluster address
```

### Key Design Decisions

1. **No hardcoded defaults**: All paths must be explicitly configured
2. **Feature flag**: `ENABLE_DIARIZATION=false` by default - users opt-in
3. **Config validation**: Raises errors if enabled but paths not set
4. **Docker-first**: Designed for volume mounts, not local paths

## Components

### 1. Config Module (`config.py`)

- Loads environment variables
- Validates required settings when feature is enabled
- Provides lazy imports for heavy dependencies (pyannote, torch)

**Key exports:**
- `ENABLE_DIARIZATION`: Feature flag
- `BASE_VIDEO_DIR`, `BASE_SUBTITLE_DIR`, `AUDIO_OUT_DIR`: Path configurations
- `HF_TOKEN`, `VERSION_COUNTRY`: Model and version settings

### 2. Pipeline Module (`pipeline.py`)

Core processing functions:

**Episode discovery:**
- `list_all_episode_videos()`: Find all .mkv files matching pattern
- `extract_episode_id()`: Parse season/episode from filename (e.g., "S01E01")

**Audio processing:**
- `extract_audio_for_video()`: Use ffmpeg to extract mono 16kHz audio
- `audio_path_for_video()`: Compute output audio path

**Diarization:**
- `run_diarization_on_audio()`: Use pyannote.audio to identify speakers
- `align_speakers_to_srt()`: Map speaker segments to subtitle timestamps

**Database integration:**
- `process_single_episode()`: Full pipeline for one episode
  - Accepts database connection and ingest_run_id
  - Parses season/episode numbers from filename
  - Builds version_season format (e.g., "US01")
  - Creates DataFrame with proper schema
  - Calls `db_utils.load_dataset_to_table()`
  - Returns row count inserted

### 3. Ray Backend Module (`ray_backend.py`)

Optional distributed processing:

- `should_use_ray()`: Check if Ray is available and enabled
- `run_diarization()`: Main entry point
  - Falls back to local processing if Ray unavailable
  - Passes database connection to workers
  - Returns list of row counts
- `_run_locally()`: Sequential processing
- `_run_with_ray()`: Distributed processing across Ray cluster

**Note:** Database connections may not serialize properly in Ray. Users with Ray clusters may need to pass connection strings instead of connection objects.

### 4. Airflow DAG (`survivor_diarization_dag.py`)

Orchestration with three tasks:

1. **check_enabled**: Skip entire pipeline if `ENABLE_DIARIZATION=false`
2. **list_episodes**: Discover all video files
3. **run_diarization_task**: Process episodes and store results
   - Creates database connection
   - Starts ingest run
   - Calls `run_diarization()` with connection
   - Ends ingest run with success/failure

**Design notes:**
- No heavy imports at module level (keeps DAG parsing fast)
- Uses `AirflowSkipException` to gracefully skip when disabled
- Tracks all processing in `bronze.ingestion_runs`

## Usage

### Local Development

```bash
# 1. Set up environment
cp .env.example .env
# Edit .env to set:
#   ENABLE_DIARIZATION=true
#   SURVIVOR_VIDEO_DIR=/path/to/your/videos
#   SURVIVOR_SUBTITLE_DIR=/path/to/your/subtitles
#   HF_TOKEN=your_token

# 2. Install dependencies
pipenv install pyannote.audio torch srt

# 3. Process episodes programmatically
python
>>> from gamebot_core.media_diarization import list_all_episode_videos, run_diarization
>>> from gamebot_core.db_utils import get_connection, start_ingest_run, end_ingest_run
>>>
>>> conn = get_connection()
>>> ingest_run_id = start_ingest_run(conn, "survivor_diarization", "Manual test")
>>> episodes = list_all_episode_videos()
>>> row_counts = run_diarization(episodes, conn, ingest_run_id)
>>> end_ingest_run(conn, ingest_run_id, "success", sum(row_counts))
```

### Docker / Airflow

```bash
# 1. Update docker-compose.yml to mount media directories
services:
  airflow-common:
    volumes:
      - /path/to/videos:/mnt/videos:ro
      - /path/to/subtitles:/mnt/subtitles:ro

# 2. Set environment variables in docker-compose.yml
environment:
  ENABLE_DIARIZATION: 'true'
  SURVIVOR_VIDEO_DIR: /mnt/videos
  SURVIVOR_SUBTITLE_DIR: /mnt/subtitles
  HF_TOKEN: ${HF_TOKEN}

# 3. Ensure ffmpeg is installed in Airflow image
# Add to airflow/Dockerfile:
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# 4. Add dependencies to airflow/requirements.txt
pyannote.audio>=3.1.0
torch>=2.0.0
srt>=3.5.0

# 5. Trigger DAG manually in Airflow UI
# Or via CLI:
docker exec airflow-scheduler airflow dags trigger survivor_diarization_pipeline
```

### Ray Distributed Processing

For multi-machine processing:

```bash
# 1. Start Ray cluster externally (on dedicated machines)
# On head node:
ray start --head --port=6379

# On worker nodes:
ray start --address=<head-node-ip>:6379

# 2. Configure environment
USE_RAY=true
RAY_ADDRESS=ray://<head-node-ip>:10001

# 3. Ensure network connectivity between Airflow and Ray cluster

# 4. Run DAG - work will be distributed across Ray workers
```

## Data Export (gamebot-lite)

The bronze.diarization_segments table is automatically included in SQLite exports:

```bash
# Export with bronze layer (includes diarization data)
pipenv run python scripts/export_sqlite.py --layer bronze --output gamebot.sqlite --package
```

The exported SQLite file will contain the `diarization_segments` table with all processed episodes.

## Future Enhancements

### Speaker-to-Castaway Mapping

Current implementation assigns generic speaker labels ("SPEAKER_00", "SPEAKER_01"). Future work could:

1. **Roster matching**: Use episode cast lists to map speakers to names
2. **Voice profiles**: Build voice models for known castaways
3. **Manual labeling**: Provide UI for correcting speaker assignments
4. **Transfer learning**: Use previous seasons' labeled data

### Silver/Gold Layer Features

Potential downstream transformations:

**Silver layer:**
- `silver.episode_speaker_stats`: Aggregate by (episode, speaker)
  - Total speaking time
  - Utterance count
  - Average utterance duration
  - Share of voice

**Gold layer:**
- `gold.castaway_speaking_metrics`: ML features per castaway-episode
  - Speaking dominance (compared to episode average)
  - Interaction patterns (who speaks after whom)
  - Sentiment analysis on dialogue
  - Topic modeling (NMF, LDA) on spoken text

### Pipeline Improvements

1. **Incremental processing**: Only process new episodes
2. **Error recovery**: Resume from last successful episode
3. **Quality metrics**: Track diarization confidence scores
4. **Parallel audio extraction**: Use multiprocessing for ffmpeg calls

## Troubleshooting

### "ENABLE_DIARIZATION is false, skipping DAG"

This is expected behavior. Set `ENABLE_DIARIZATION=true` to enable.

### "Required environment variable not set"

Ensure all required variables are set when `ENABLE_DIARIZATION=true`:
- `SURVIVOR_VIDEO_DIR`
- `SURVIVOR_SUBTITLE_DIR`
- `SURVIVOR_AUDIO_OUT_DIR`
- `HF_TOKEN`

### "ffmpeg not found"

Install ffmpeg in your environment:
- Docker: Add to Dockerfile `RUN apt-get install -y ffmpeg`
- Local: `sudo apt-get install ffmpeg` (Ubuntu) or `brew install ffmpeg` (macOS)

### "pyannote.audio model download fails"

1. Check HuggingFace token is valid
2. Accept model license at https://huggingface.co/pyannote/speaker-diarization-3.1
3. Verify network connectivity to huggingface.co

### Ray serialization errors with database connection

Ray cannot serialize database connection objects. Solutions:
1. Use connection string instead and recreate connection in remote workers
2. Use Ray's `put()` to share connection across workers
3. Pass connection parameters and reconstruct in remote functions

## References

- **pyannote.audio**: https://github.com/pyannote/pyannote-audio
- **Speaker diarization paper**: https://arxiv.org/abs/2104.04045
- **Ray documentation**: https://docs.ray.io/
- **ffmpeg audio processing**: https://ffmpeg.org/ffmpeg-filters.html#Audio-Filters
