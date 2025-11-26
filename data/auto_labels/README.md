# Auto-Generated Castaway Labels

This directory contains **automatically generated** castaway labels for Episodes 2+ of each season.

## File Organization

**Directory Structure:**
```
data/
├─ manual_labels/
│  └─ survivor_speaker_labels.csv       # Episode 1 only, human-curated
└─ auto_labels/
   └─ survivor_auto_labels.csv          # Episodes 2+, system-generated

data_cache/
├─ survivor_diarized/                   # Diarized parquet files with labels
│  ├─ US01_S01_E01_diarized.parquet    # version_season format in filename
│  ├─ US01_S01_E02_diarized.parquet
│  └─ ...
└─ survivor_embeddings/                 # Voice embeddings (PRIVATE, never in Postgres!)
   ├─ US01_cluster_embeddings.parquet   # Per (version_season, episode, speaker_label)
   ├─ US01_season_centroids.parquet     # Per (version_season, castaway_id) - for auto-labeling
   └─ US01_episode_castaway_embeddings.parquet  # Per (version_season, episode, castaway_id)
```

**Naming Convention:**
- `version_season`: Database key format (e.g., `US01`, `AU03`, `NZ01`)
- Filenames include `version_season` for clarity (e.g., `US01_S01_E01_diarized.parquet`)
- Supports variable episode counts per season (code discovers episodes dynamically)

## Auto-Labels CSV Format

**File:** `survivor_auto_labels.csv`

```csv
version_season,episode,speaker_label,castaway_id,castaway,similarity,notes
US01,2,SPEAKER_0,US01jeffp01,Jeff Probst,0.94,Auto-labeled from E01 centroids
US01,2,SPEAKER_3,US01richardh01,Richard Hatch,0.87,Auto-labeled from E01 centroids
US01,3,SPEAKER_1,US01jeffp01,Jeff Probst,0.92,Auto-labeled from E01 centroids
```

## Three Levels of Embeddings

### 1. Cluster-Level Embeddings (Finest Granularity)
**File:** `US{season:02d}_cluster_embeddings.parquet`
**Key:** `(version_season, episode, speaker_label)`
**Purpose:** Raw building blocks from pyannote speaker clusters
**Storage:** Parquet only (PRIVATE, never in Postgres)
**Used for:** Building season centroids and episode-castaway embeddings

### 2. Season-Level Centroids (For Auto-Labeling)
**File:** `US{season:02d}_season_centroids.parquet`
**Key:** `(version_season, castaway_id)`
**Purpose:** Identity propagation - auto-label new episodes
**Computed from:** Episode 1 manual labels + high-confidence (≥0.90) auto-labels from prior episodes
**Storage:** Parquet only (PRIVATE, never in Postgres)
**Accumulates:** When processing Episode N, uses E01 through E(N-1) labeled clusters

### 3. Per-Episode Per-Castaway Embeddings (For Analytics)
**File:** `US{season:02d}_episode_castaway_embeddings.parquet`
**Key:** `(version_season, episode, castaway_id)`
**Purpose:** Derive NUMERIC features for Postgres (not stored directly)
**Computed from:** Average of all cluster embeddings for each castaway within each episode
**Storage:** Parquet only (PRIVATE, never in Postgres)
**Used to derive:**
- `distance_to_season_centroid` (float)
- `voice_consistency_score` (float)
- `acoustic_drift` (float)
- Other numeric features suitable for database storage

## What Goes to Postgres?

**✅ ALLOWED in Postgres:**
- Episode metadata (version_season, episode, castaway_id)
- Timing data (start_time, end_time, duration)
- Speaker labels (speaker_label)
- Word counts and text statistics
- **NUMERIC features derived FROM embeddings** (distances, scores, acoustic metrics)

**❌ NEVER in Postgres:**
- Raw 512-dimensional embedding vectors
- Subtitle text (copyright, stored in parquet only)
- Any personally identifiable voice data

## Key Properties

1. **Episode 1 NOT included in auto-labels** - Only manual labels in `data/manual_labels/`
2. **Automatically generated** - Created by `manage_speaker_labels.py full-workflow`
3. **Never manually edited** - System overwrites/appends to this file
4. **Variable episode counts supported** - Code dynamically discovers episodes (no hardcoded limits)
5. **Embeddings stay private** - All three levels stored in parquet, never in database

## Workflow

1. User manually labels Episode 1 → `data/manual_labels/survivor_speaker_labels.csv`
2. System runs auto-labeling → writes `data/auto_labels/survivor_auto_labels.csv`
3. System updates parquet files with castaway/castaway_id columns
4. Downstream pipelines read from parquet files (have all labels + embeddings)
5. Feature extraction derives NUMERIC values from embeddings for Postgres

## Similarity Threshold

- **≥ 0.80**: Auto-labeled and applied to parquet
- **≥ 0.90**: High-confidence, used to refine season centroids
- **< 0.80**: Left as `UNKNOWN`, not auto-labeled
