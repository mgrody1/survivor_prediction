# Speaker Diarization Pipeline - Quick Reference

## What This Does

Processes Survivor TV episode videos to identify **who is speaking when**, aligned with subtitle timing. Outputs:
1. **Parquet files** (local only, includes text) → For NLP analysis
2. **Database tables** (shared, NO text) → Timing metadata + derived features

## Key Architecture Decisions

### Copyright Compliance

- **Subtitle text is copyrighted** → stays in local parquet files only
- **Database contains NO text** → only timing metadata and statistical features
- This allows sharing the database/gamebot-lite package without copyright issues

### Data Flow

```
Episode Videos → Diarization → Dual Output:
                                  ├─ Parquet (with text, local only)
                                  └─ PostgreSQL (NO text, shareable)
```

**Bronze Layer** (`bronze.diarization_segments`):
- Speaker timing metadata only
- Columns: `version_season`, `episode`, `subtitle_index`, `start_time`, `end_time`, `speaker_label`

**Silver Layer** (`silver.castaway_episode_speech_features`):
- Aggregated NLP features computed in Python (not SQL/dbt)
- Columns: `utterance_count`, `total_speaking_seconds`, `share_of_voice`, `vocabulary_richness`, etc.
- User can extend with: sentiment scores, topic distributions, linguistic complexity

### Who Runs What

| Component | Who Uses It | Purpose |
|-----------|-------------|---------|
| **Diarization Pipeline** | Only you (repo owner) | Process source videos you have access to |
| **Parquet Files** | Only you (local machine) | Run Python NLP analysis on subtitle text |
| **PostgreSQL Database** | All contributors | Query timing metadata and derived features |
| **gamebot-lite (pip)** | External researchers | Install via `pip install gamebot-lite`, get SQLite export |

## Quick Start

### Local Development (Test First!)

```bash
# 1. Install dependencies
pipenv install

# 2. Start PostgreSQL
cd deploy && docker compose up warehouse-db -d

# 3. Configure .env
ENABLE_DIARIZATION=true
SURVIVOR_VIDEO_DIR=/path/to/videos
SURVIVOR_SUBTITLE_DIR=/path/to/subtitles
HF_TOKEN=your_hf_token

# 4. Run diarization (same script Airflow uses)
pipenv run python scripts/diarization_pipeline.py

# 5. Build NLP features
pipenv run python scripts/diarization_pipeline.py --features-only
```

**Split work across computers:**
```bash
# Computer 1: episodes 1-30
pipenv run python scripts/diarization_pipeline.py --range 1 30

# Computer 2: episodes 31-60
pipenv run python scripts/diarization_pipeline.py --range 31 60

# Then build features on any computer:
pipenv run python scripts/diarization_pipeline.py --features-only
```

### Production Airflow (After Local Testing)

```bash
# .env file
ENABLE_DIARIZATION=true
SURVIVOR_VIDEO_DIR=/path/to/your/videos
SURVIVOR_SUBTITLE_DIR=/path/to/your/subtitles
HF_TOKEN=your_huggingface_token  # From https://huggingface.co/settings/tokens
```

### Production Airflow (After Local Testing)

```bash
# Same .env, then start Airflow
cd airflow && docker compose up -d
```

DAG `survivor_diarization_pipeline` calls the same `scripts/diarization_pipeline.py` code.

### Adding Your Own NLP Features

Edit `gamebot_core/media_diarization/pipeline.py` → `build_speech_features_from_parquet()`:

```python
# Example: Add sentiment analysis
from textblob import TextBlob

def calc_sentiment(group):
    all_text = " ".join(group["subtitle_text"].astype(str))
    blob = TextBlob(all_text)
    return blob.sentiment.polarity  # -1 to 1

sentiment = (
    all_data.groupby(["version_season", "episode", "speaker_label"])
    .apply(calc_sentiment)
    .reset_index(name="sentiment_score")
)
features = features.merge(sentiment, on=["version_season", "episode", "speaker_label"])
```

Then add `sentiment_score DOUBLE PRECISION` to `Database/create_tables.sql` in the silver table.

## Detailed Documentation

For comprehensive setup, troubleshooting, and advanced usage:

**→ [Full Implementation Guide](docs/diarization_implementation_summary.md)**

Key sections:
- [Docker Setup](docs/diarization_implementation_summary.md#docker--airflow) - Volume mounts, ffmpeg, dependencies
- [Ray Distributed Processing](docs/diarization_implementation_summary.md#ray-distributed-processing) - Multi-machine clusters
- [Database Schema](docs/diarization_implementation_summary.md#storage-layer) - Table structures and constraints
- [Feature Engineering](docs/diarization_implementation_summary.md#future-enhancements) - Ideas for NLP features
- [Troubleshooting](docs/diarization_implementation_summary.md#troubleshooting) - Common errors and solutions

## File Structure

```
gamebot_core/media_diarization/
├── config.py              # Environment config with ENABLE_DIARIZATION flag
├── pipeline.py            # Core: audio extraction, diarization, NLP features
├── ray_backend.py         # Optional: distributed processing
└── __init__.py

airflow/dags/
└── survivor_diarization_dag.py  # Orchestration

Database/
└── create_tables.sql      # bronze + silver schemas (lines 639-700)

docs/
└── diarization_implementation_summary.md  # Full documentation
```

## Design Philosophy

1. **Optional by default** - Most users don't have source media, so feature is disabled
2. **Copyright compliant** - No text in shared database, only local parquet
3. **Python for NLP** - Use sklearn, spaCy, transformers, not SQL
4. **Docker-first** - Designed for containerized deployment
5. **Production patterns** - Follows existing gamebot conventions (db_utils, log_utils, ingest tracking)

---

**Questions?** See the [full implementation guide](docs/diarization_implementation_summary.md) or check existing [contributor docs](docs/production_contributor_guide.md).
