"""
Survivor TV show speaker diarization pipeline.

This package provides tools for extracting audio from video episodes,
running speaker diarization with pyannote.audio, and aligning subtitles
to speaker segments. Results are stored in bronze.diarization_segments table.

OPTIONAL FEATURE: This pipeline is disabled by default. Set ENABLE_DIARIZATION=true
to enable. Most users won't have access to source video files.
"""

from .config import (
    ENABLE_DIARIZATION,
    BASE_VIDEO_DIR,
    BASE_SUBTITLE_DIR,
    AUDIO_OUT_DIR,
    DIARIZED_PARQUET_DIR,
    EMBEDDINGS_DIR,
    MANUAL_LABELS_PATH,
    AUTO_LABELS_PATH,
    HF_TOKEN,
    PYANNOTE_MODEL,
    VERSION_COUNTRY,
)
from .pipeline import (
    extract_episode_id,
    find_matching_srt,
    audio_path_for_video,
    extract_audio_for_video,
    load_srt_segments,
    process_single_episode,
    build_speech_features_from_parquet,
    list_all_episode_videos,
)
from .ray_backend import run_diarization, should_use_ray
from .labels import load_speaker_labels, apply_speaker_labels
from .embeddings import (
    compute_cluster_embeddings_for_episode,
    save_cluster_embeddings,
    load_all_embeddings,
    propagate_castaway_labels,
    auto_label_unlabeled_clusters,
)

__all__ = [
    # Config
    "ENABLE_DIARIZATION",
    "BASE_VIDEO_DIR",
    "BASE_SUBTITLE_DIR",
    "AUDIO_OUT_DIR",
    "DIARIZED_PARQUET_DIR",
    "EMBEDDINGS_DIR",
    "MANUAL_LABELS_PATH",
    "AUTO_LABELS_PATH",
    "HF_TOKEN",
    "PYANNOTE_MODEL",
    "VERSION_COUNTRY",
    # Pipeline functions
    "extract_episode_id",
    "find_matching_srt",
    "audio_path_for_video",
    "extract_audio_for_video",
    "load_srt_segments",
    "process_single_episode",
    "build_speech_features_from_parquet",
    "list_all_episode_videos",
    # Ray backend
    "run_diarization",
    "should_use_ray",
    # Manual labels
    "load_speaker_labels",
    "apply_speaker_labels",
    # Embeddings
    "compute_cluster_embeddings_for_episode",
    "save_cluster_embeddings",
    "load_all_embeddings",
    "propagate_castaway_labels",
    "auto_label_unlabeled_clusters",
]
