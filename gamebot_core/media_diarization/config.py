"""Configuration for Survivor media diarization pipeline.

All settings are read from environment variables, integrating with the
existing Gamebot .env file pattern. Paths are returned as Path objects.

This pipeline is OPTIONAL - if source data is not available, it can be safely
skipped without affecting other Gamebot functionality.
"""

import os
import warnings
from pathlib import Path

# =============================================================================
# Pipeline Enable/Disable Flag
# =============================================================================
# Set to "true" to enable diarization pipeline processing
# Most users won't have access to source video/subtitle files, so this
# defaults to false to make the pipeline optional
ENABLE_DIARIZATION = os.getenv("ENABLE_DIARIZATION", "false").lower() in {
    "true",
    "1",
    "yes",
    "on",
}

# =============================================================================
# Video and Subtitle Paths
# =============================================================================
# NO DEFAULTS - users must configure these paths in their environment
# These should point to wherever video files and SRT subtitles are stored
# (local directory, NAS mount, cloud storage mount, etc.)

_video_dir_str = os.getenv("SURVIVOR_VIDEO_DIR")
_subtitle_dir_str = os.getenv("SURVIVOR_SUBTITLE_DIR")

if ENABLE_DIARIZATION and not _video_dir_str:
    raise ValueError(
        "ENABLE_DIARIZATION=true but SURVIVOR_VIDEO_DIR not set. "
        "Set the environment variable to your video directory path."
    )

if ENABLE_DIARIZATION and not _subtitle_dir_str:
    raise ValueError(
        "ENABLE_DIARIZATION=true but SURVIVOR_SUBTITLE_DIR not set. "
        "Set the environment variable to your subtitle directory path."
    )

BASE_VIDEO_DIR = Path(_video_dir_str) if _video_dir_str else Path("/dev/null")
BASE_SUBTITLE_DIR = Path(_subtitle_dir_str) if _subtitle_dir_str else Path("/dev/null")

# =============================================================================
# Output Directories
# =============================================================================
# Defaults to data_cache for temporary/intermediate files (Docker-compatible)
# Docker deployments should mount a persistent volume at /opt/airflow/data_cache

AUDIO_OUT_DIR = Path(os.getenv("SURVIVOR_AUDIO_OUT_DIR", "data_cache/survivor_audio"))

DIARIZED_PARQUET_DIR = Path(
    os.getenv("SURVIVOR_DIARIZED_DIR", "data_cache/survivor_diarized")
)

# Speaker embeddings (private, local-only)
EMBEDDINGS_DIR = DIARIZED_PARQUET_DIR.parent / "survivor_embeddings"

# Manual castaway labels CSV (Episode 1 only, human-curated)
MANUAL_LABELS_PATH = Path("data/manual_labels/survivor_speaker_labels.csv")

# Auto-generated labels CSV (Episodes 2+, system-generated)
AUTO_LABELS_PATH = Path("data/auto_labels/survivor_auto_labels.csv")

# Ensure output directories exist (only when enabled)
if ENABLE_DIARIZATION:
    AUDIO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    DIARIZED_PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    MANUAL_LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTO_LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)

# =============================================================================
# Hugging Face Configuration
# =============================================================================
# Pyannote models require HuggingFace token after accepting license
# Get token from: https://huggingface.co/settings/tokens
# Accept license at: https://huggingface.co/pyannote/speaker-diarization-3.1

HF_TOKEN = os.getenv("HF_TOKEN", "")

if ENABLE_DIARIZATION and not HF_TOKEN:
    raise ValueError(
        "ENABLE_DIARIZATION=true but HF_TOKEN not set. "
        "Get token from https://huggingface.co/settings/tokens and accept model license."
    )

# Pyannote model selection
PYANNOTE_MODEL = os.getenv(
    "PYANNOTE_DIARIZATION_MODEL",
    "pyannote/speaker-diarization-3.1",
)

# =============================================================================
# Ray Configuration (Optional Distributed Processing)
# =============================================================================
# Ray is optional for distributing work across multiple machines
# Default is local sequential processing - no Ray required

USE_RAY = os.getenv("USE_RAY", "false").lower() in {"true", "1", "yes", "on"}

# Ray cluster address (only relevant if USE_RAY=true)
# "auto" = auto-detect or start local cluster
# "ray://hostname:10001" = connect to remote Ray cluster
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "auto")

# =============================================================================
# Show Version Configuration
# =============================================================================
# Survivor version being processed (US, AU, SA, NZ, etc.)
# Used in database version_season field and output naming

VERSION_COUNTRY = os.getenv("VERSION_COUNTRY", "US").upper()

# =============================================================================
# Validation (only when diarization is enabled)
# =============================================================================

if ENABLE_DIARIZATION:
    if not BASE_VIDEO_DIR.exists():
        warnings.warn(
            f"SURVIVOR_VIDEO_DIR does not exist: {BASE_VIDEO_DIR}. "
            "Ensure media source is mounted/accessible.",
            UserWarning,
            stacklevel=2,
        )

    if not BASE_SUBTITLE_DIR.exists():
        warnings.warn(
            f"SURVIVOR_SUBTITLE_DIR does not exist: {BASE_SUBTITLE_DIR}. "
            "Ensure subtitle source is mounted/accessible.",
            UserWarning,
            stacklevel=2,
        )
