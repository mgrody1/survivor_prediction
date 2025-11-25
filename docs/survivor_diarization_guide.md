# Survivor Speaker Diarization Pipeline

## Overview

This module provides end-to-end speaker diarization for Survivor TV episodes:

1. **Audio Extraction**: Extract mono 16kHz audio from video files using ffmpeg
2. **Speaker Diarization**: Run pyannote.audio to identify speaker segments
3. **Subtitle Alignment**: Align SRT subtitles to speaker clusters by temporal overlap
4. **Feature Extraction**: Generate castaway-episode-level features (talk time, utterance counts, etc.)
5. **Optional Ray Distribution**: Scale processing across multiple machines

## Architecture

```
gamebot_core/media_diarization/
├── __init__.py          # Public API exports
├── config.py            # Environment variable configuration
├── pipeline.py          # Core diarization logic
└── ray_backend.py       # Optional Ray distribution

airflow/dags/
└── survivor_diarization_dag.py  # Airflow orchestration
```

**Design Principles:**
- **Modular & Reusable**: All logic in dedicated package, not inline in DAG
- **Config via Environment**: No hard-coded paths, all configurable via .env
- **Ray is Optional**: Works with or without Ray, no hard dependencies
- **Lazy Imports**: Heavy libraries (torch, pyannote, ray) imported inside functions to keep Airflow DAG parsing fast

## Quick Start

### 1. Prerequisites

**System Requirements:**
- Ubuntu/Linux with NAS access (or adjust paths for your setup)
- ffmpeg installed: `sudo apt-get install ffmpeg`
- Python 3.10+ with dependencies (see below)
- Hugging Face account with pyannote model license accepted

**Python Dependencies:**
```bash
pip install pyannote.audio torch srt pandas pyarrow
# Optional for distributed processing:
pip install ray
```

### 2. Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required: NAS mount paths (adjust for your setup)
SURVIVOR_VIDEO_DIR=/mnt/nas/Max2NUC Files/TV Shows/Survivor (2000) {TvbId-76733}
SURVIVOR_SUBTITLE_DIR=/mnt/nas/Max2NUC Files/Subtitles

# Required: Hugging Face token (after accepting model license)
HF_TOKEN=hf_your_token_here

# Optional: Customize output locations
SURVIVOR_AUDIO_OUT_DIR=data_cache/survivor_audio
SURVIVOR_DIARIZED_DIR=data_cache/survivor_diarized

# Optional: Show version identifier
VERSION_COUNTRY=US

# Optional: Ray distributed processing
USE_RAY=false
RAY_ADDRESS=auto
```

**Important:** Get your HF token from https://huggingface.co/settings/tokens and accept the pyannote model license at https://huggingface.co/pyannote/speaker-diarization-3.1

### 3. Running Locally (Without Airflow)

```python
from gamebot_core.media_diarization import (
    list_all_episode_videos,
    run_diarization,
    build_castaway_episode_features,
)

# Discover episodes
episodes = list_all_episode_videos()
print(f"Found {len(episodes)} episodes")

# Process all episodes (uses Ray if configured, otherwise local)
output_paths = run_diarization(episodes)

# Build aggregated features
features_path = build_castaway_episode_features()
print(f"Features saved to: {features_path}")
```

### 4. Running with Airflow

1. **Ensure Airflow is configured** (see Docker setup below)
2. **Navigate to Airflow UI**: http://localhost:8080
3. **Find DAG**: `survivor_diarization_pipeline`
4. **Trigger manually** (scheduled as `@once` by default)

## Docker / Airflow Deployment

### Development Environment (airflow/docker-compose.yaml)

This is the **development deployment** used for building and testing DAGs locally.

**Required Changes:**

1. **Add NAS volume mounts** to `airflow/docker-compose.yaml`:

```yaml
x-airflow-common:
  &airflow-common
  volumes:
    # ... existing volumes ...
    # ADD THESE LINES:
    - /mnt/nas/Max2NUC Files:/mnt/nas/Max2NUC Files:ro  # Read-only NAS access
    - ../data_cache:/opt/airflow/data_cache              # Persistent output
```

2. **Install ffmpeg** in `airflow/Dockerfile`:

```dockerfile
# Add before the final USER statement:
USER root
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*
USER airflow
```

3. **Add Python dependencies** to `airflow/requirements.txt`:

```
pyannote.audio
torch
srt
# Optional:
ray
```

4. **Add environment variables** to the `environment` section under `airflow-common-env`:

```yaml
environment: &airflow-common-env
  # ... existing vars ...
  # ADD THESE:
  SURVIVOR_VIDEO_DIR: /mnt/nas/Max2NUC Files/TV Shows/Survivor (2000) {TvbId-76733}
  SURVIVOR_SUBTITLE_DIR: /mnt/nas/Max2NUC Files/Subtitles
  SURVIVOR_AUDIO_OUT_DIR: /opt/airflow/data_cache/survivor_audio
  SURVIVOR_DIARIZED_DIR: /opt/airflow/data_cache/survivor_diarized
  HF_TOKEN: ${HF_TOKEN}  # From host .env
  VERSION_COUNTRY: US
  USE_RAY: "false"
```

### Production Environment (deploy/docker-compose.yml)

This is the **production deployment** for running the warehouse in production.

Apply the **same changes** as above (NAS mounts, ffmpeg, dependencies, env vars) to `deploy/docker-compose.yml`.

**Note:** The production deployment uses pre-built images (`mhgrody/gamebot-warehouse:latest`), so you'll need to rebuild and push the image after adding ffmpeg and Python dependencies.

## Ray Distributed Processing Setup

For processing many episodes across multiple machines:

### 1. Start Ray Cluster (External to Airflow)

**On head node:**
```bash
ray start --head --port=6379
```

**On worker nodes:**
```bash
ray start --address=<head-node-ip>:6379
```

### 2. Configure Airflow Environment

Update your `.env` or docker-compose environment:

```bash
USE_RAY=true
RAY_ADDRESS=ray://<head-node-ip>:10001  # Ray Client address
```

### 3. Network Access

Ensure Airflow containers can reach Ray cluster nodes (open firewall ports, configure Docker networking, etc.).

### Important Notes

- **DO NOT run Ray inside Airflow containers** - start it externally on dedicated machines
- Ray workers need access to the same NAS mounts (video/subtitle directories)
- For single-machine testing, use `RAY_ADDRESS=auto` (auto-starts local cluster)

## File Naming Conventions

**Episode Videos:**
- Must contain season/episode pattern: `S01E01`, `s02e03`, etc.
- Examples: `Survivor.S01E01.720p.mkv`, `Survivor_S45E13.mp4`

**Subtitle Files:**
- Must contain matching episode ID: `*S01E01*.srt`
- Searched in `SURVIVOR_SUBTITLE_DIR` (including subdirectories)

**Output Files:**
- Per-episode: `{VERSION_COUNTRY}{episode_id}_diarized.parquet` (e.g., `USS01E01_diarized.parquet`)
- Aggregated: `{VERSION_COUNTRY}_castaway_episode_features.parquet` (e.g., `US_castaway_episode_features.parquet`)

## Output Schema

### Per-Episode Parquet Files

Each episode produces a parquet file with subtitle segments aligned to speakers:

| Column | Type | Description |
|--------|------|-------------|
| `version_country` | str | Show version (e.g., "US") |
| `episode_id` | str | Episode identifier (e.g., "S01E01") |
| `index` | int | Subtitle sequence number |
| `start` | float | Segment start time (seconds) |
| `end` | float | Segment end time (seconds) |
| `speaker` | str | Speaker cluster label (e.g., "SPEAKER_0") |
| `speaker_confidence` | float | Overlap duration with speaker segment |
| `text` | str | Subtitle text content |
| `word_count` | int | Number of words in subtitle |
| `video_path` | str | Source video file path |
| `srt_path` | str | Source subtitle file path |
| `audio_path` | str | Extracted audio file path |

### Castaway-Episode Features

Aggregated features per (episode, speaker):

| Column | Type | Description |
|--------|------|-------------|
| `version_country` | str | Show version |
| `episode_id` | str | Episode identifier |
| `speaker` | str | Speaker cluster label |
| `castaway` | str | Castaway name (currently "UNKNOWN") |
| `utterance_count` | int | Number of speaking segments |
| `total_talk_time_seconds` | float | Total time speaking |
| `total_words` | int | Total word count |
| `mean_words_per_utterance` | float | Average words per segment |
| `mean_utterance_duration_seconds` | float | Average segment length |
| `share_of_voice` | float | Proportion of episode talk time |

## Speaker Mapping to Castaways

**Current State:** Speaker clusters are labeled as `SPEAKER_0`, `SPEAKER_1`, etc. These do NOT correspond to actual castaway names yet.

**Future Enhancement:** Map speaker clusters to castaways using:
1. **Manual Labeling**: Listen to samples and manually tag speakers
2. **Contestant Roster Matching**: Use castaway_details table to narrow down possibilities
3. **Voice Models**: Train per-castaway voice models for automated recognition
4. **Confessional Alignment**: Match confessional timestamps (if available) to speaker segments

This is intentionally left as a **manual/semi-automated step** to allow flexibility in approach.

## Troubleshooting

### Common Issues

**1. `FileNotFoundError: No SRT subtitle file found`**
- Ensure subtitle files follow naming convention: `*S01E01*.srt`
- Check `SURVIVOR_SUBTITLE_DIR` path is correct
- Verify NAS is mounted

**2. `ffmpeg not found in PATH`**
- Install ffmpeg: `sudo apt-get install ffmpeg`
- For Docker: Add to Dockerfile (see above)

**3. `HF_TOKEN environment variable not set`**
- Set `HF_TOKEN` in your `.env` file
- Accept pyannote model license on Hugging Face first

**4. `No episode video files found`**
- Check `SURVIVOR_VIDEO_DIR` path is correct
- Verify video files contain `SxxExx` pattern in filename
- Ensure NAS is mounted

**5. Ray connection errors**
- Verify Ray cluster is running: `ray status`
- Check `RAY_ADDRESS` is correct
- Ensure network connectivity between Airflow and Ray nodes

### Performance Tuning

**GPU Acceleration:**
- Pyannote automatically uses GPU if CUDA is available
- For Docker, use nvidia-docker and pass GPU devices
- Expect ~10-20x speedup with GPU vs CPU

**Processing Time Estimates:**
- **CPU (no GPU)**: ~30-60 minutes per episode
- **GPU (RTX 3090)**: ~3-5 minutes per episode
- **Ray cluster (4 workers with GPU)**: ~1 minute per episode (parallel)

## Integration with Existing Gamebot

This diarization pipeline is designed to integrate with Gamebot's medallion architecture:

**Future Integration Points:**
1. **Bronze Layer**: Raw diarized segments as bronze table
2. **Silver Layer**: Speaker-to-castaway mappings, cleaned features
3. **Gold Layer**: ML-ready confessional/dialogue features joined with existing contestant data
4. **TF-IDF / NLP**: Text analysis on what castaways say per episode

**Current State:** Pipeline saves to parquet files. Database insertion logic is stubbed out (see `build_castaway_episode_features()` in `pipeline.py`).

## Example Analysis

```python
import pandas as pd

# Load features
df = pd.read_parquet("data_cache/survivor_diarized/US_castaway_episode_features.parquet")

# Top talkers in S45E01
episode = df[df["episode_id"] == "S45E01"]
top_talkers = episode.nlargest(5, "total_talk_time_seconds")
print(top_talkers[["speaker", "utterance_count", "total_talk_time_seconds", "share_of_voice"]])

# Share of voice distribution
import matplotlib.pyplot as plt
episode["share_of_voice"].hist(bins=20)
plt.xlabel("Share of Voice")
plt.ylabel("Count")
plt.title("Speaker Distribution in Episode")
plt.show()
```

## Known Limitations & Ambiguities

1. **Speaker Identity**: Clusters are not mapped to castaway names yet
2. **Music/Effects**: Non-speech audio may create false speaker segments
3. **Subtitle Quality**: Alignment accuracy depends on SRT timing precision
4. **File Naming**: Assumes specific patterns (SxxExx) - may need adjustment
5. **Single-Version**: Currently configured for one show version at a time
6. **Database Integration**: Parquet output only, no DB insertion yet
7. **Error Handling**: Pipeline halts on first error - could be more resilient

All ambiguities are documented in code comments with `AMBIGUITY NOTE:` markers for easy searching.

## Contributing

When making changes:
- Keep heavy imports inside functions (lazy loading)
- Document assumptions with `AMBIGUITY NOTE:` comments
- Add type hints for public API functions
- Test both with and without Ray
- Update this README for any new configuration options

## License

Same as parent Gamebot repository.
