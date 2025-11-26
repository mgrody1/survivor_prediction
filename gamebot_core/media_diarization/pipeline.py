"""Core pipeline logic for Survivor speaker diarization.

This module implements:
- Audio extraction from video files using ffmpeg
- SRT subtitle parsing
- Speaker diarization using pyannote.audio
- Alignment of SRT segments to speaker segments
- Per-episode processing with database storage in bronze layer

CRITICAL: Heavy imports (torch, pyannote, etc.) are done INSIDE functions
to keep Airflow DAG parsing lightweight.
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from .config import (
    AUDIO_OUT_DIR,
    BASE_SUBTITLE_DIR,
    BASE_VIDEO_DIR,
    DIARIZED_PARQUET_DIR,
    HF_TOKEN,
    PYANNOTE_MODEL,
    VERSION_COUNTRY,
)

logger = logging.getLogger(__name__)


def _apply_torchaudio_compatibility_patches():
    """Apply compatibility patches for torchaudio API changes.

    Newer torchaudio removed several attributes that older pyannote.audio versions expect.
    This must be called BEFORE importing pyannote.audio.
    """
    try:
        import torchaudio

        # Patch 1: AudioMetaData removed in newer torchaudio
        if not hasattr(torchaudio, "AudioMetaData"):
            import dataclasses

            @dataclasses.dataclass
            class AudioMetaData:
                sample_rate: int = 16000
                num_frames: int = 0
                num_channels: int = 1

            torchaudio.AudioMetaData = AudioMetaData

        # Patch 2: list_audio_backends removed in newer torchaudio
        if not hasattr(torchaudio, "list_audio_backends"):

            def list_audio_backends():
                return ["sox", "soundfile"]

            torchaudio.list_audio_backends = list_audio_backends

        # Patch 3: get_audio_backend removed in newer torchaudio
        if not hasattr(torchaudio, "get_audio_backend"):

            def get_audio_backend():
                return "soundfile"

            torchaudio.get_audio_backend = get_audio_backend

        # Patch 4: info() removed in newer torchaudio - use torchaudio.info() -> AudioMetaData
        if not hasattr(torchaudio, "info"):

            def info(filepath, **kwargs):
                """Replacement for removed torchaudio.info function.
                Accepts format, backend, and any other kwargs for compatibility.
                """
                # Use soundfile to get audio metadata (ignore all kwargs)
                import soundfile as sf

                file_info = sf.info(filepath)
                return torchaudio.AudioMetaData(
                    sample_rate=file_info.samplerate,
                    num_frames=file_info.frames,
                    num_channels=file_info.channels,
                )

            torchaudio.info = info

    except ImportError:
        pass  # torchaudio not installed yet


def _apply_huggingface_hub_compatibility_patches():
    """Apply compatibility patch for huggingface_hub API changes.

    pyannote.audio 3.4.0 uses old use_auth_token parameter,
    huggingface_hub 1.1+ expects token parameter.
    """
    try:
        from huggingface_hub import hf_hub_download as _original_hf_hub_download
        import functools

        @functools.wraps(_original_hf_hub_download)
        def _patched_hf_hub_download(*args, use_auth_token=None, token=None, **kwargs):
            # Convert old parameter name to new one
            if use_auth_token is not None and token is None:
                token = use_auth_token
            return _original_hf_hub_download(*args, token=token, **kwargs)

        # Replace the function in the huggingface_hub module
        import huggingface_hub

        huggingface_hub.hf_hub_download = _patched_hf_hub_download
    except ImportError:
        pass  # huggingface_hub not installed yet


# =============================================================================
# Episode ID and Version Parsing
# =============================================================================


def extract_episode_id(video_path: Path) -> str:
    """
    Extract season/episode identifier from a video filename.

    Expects filename format like: "Survivor.S01E01.*.mkv" or similar.
    Returns normalized format: "S01E01"

    Args:
        video_path: Path to video file

    Returns:
        Episode ID string like "S01E01"

    Raises:
        ValueError: If episode ID cannot be extracted from filename
    """
    pattern = r"[sS](\d{2})[eE](\d{2})"
    match = re.search(pattern, video_path.name)
    if not match:
        raise ValueError(
            f"Could not extract episode ID from filename: {video_path.name}. "
            f"Expected pattern like 'S01E01' in the filename."
        )
    season_num, episode_num = match.groups()
    return f"S{season_num}E{episode_num}"


def parse_episode_numbers(episode_id: str) -> tuple[int, int]:
    """
    Parse season and episode numbers from episode ID.

    Args:
        episode_id: Episode ID like "S01E01"

    Returns:
        Tuple of (season_number, episode_number) as ints

    Raises:
        ValueError: If episode ID format is invalid
    """
    pattern = r"[sS](\d{2})[eE](\d{2})"
    match = re.match(pattern, episode_id)
    if not match:
        raise ValueError(f"Invalid episode ID format: {episode_id}")
    season_num, episode_num = match.groups()
    return int(season_num), int(episode_num)


def build_version_season(version: str, season: int) -> str:
    """
    Build version_season string following Gamebot schema conventions.

    Args:
        version: Country code (e.g., "US", "AU")
        season: Season number

    Returns:
        version_season string like "US01" or "AU11"
    """
    return f"{version}{season:02d}"


# =============================================================================
# SRT Subtitle Matching
# =============================================================================


def find_matching_srt(video_path: Path) -> Path:
    """
    Find the matching SRT subtitle file for a video episode.

    Searches BASE_SUBTITLE_DIR for .srt files containing the episode ID.

    Args:
        video_path: Path to video file

    Returns:
        Path to matching .srt file

    Raises:
        FileNotFoundError: If no matching SRT file is found
    """
    episode_id = extract_episode_id(video_path)

    # Search for SRT files containing the episode ID
    matches = list(BASE_SUBTITLE_DIR.glob(f"*{episode_id}*.srt"))

    if not matches:
        # Try recursive search in subdirectories
        matches = list(BASE_SUBTITLE_DIR.glob(f"**/*{episode_id}*.srt"))

    if not matches:
        raise FileNotFoundError(
            f"No SRT subtitle file found for episode {episode_id} in {BASE_SUBTITLE_DIR}"
        )

    if len(matches) > 1:
        logger.warning(
            f"Multiple SRT files found for {episode_id}: {matches}. Using first: {matches[0]}"
        )

    return matches[0]


# =============================================================================
# Audio Extraction
# =============================================================================


def audio_path_for_video(video_path: Path) -> Path:
    """
    Generate the output audio path for a video file.

    Output format: AUDIO_OUT_DIR / "{VERSION_COUNTRY}{episode_id}.wav"
    Example: "data_cache/survivor_audio/USS01E01.wav"

    Args:
        video_path: Path to video file

    Returns:
        Path where extracted audio should be saved
    """
    episode_id = extract_episode_id(video_path)
    return AUDIO_OUT_DIR / f"{VERSION_COUNTRY}{episode_id}.wav"


def extract_audio_for_video(video_path: Path) -> Path:
    """
    Extract mono 16kHz audio from a video file using ffmpeg.

    If audio file already exists, skips extraction and returns existing path.

    AMBIGUITY NOTE: Requires ffmpeg to be installed and available in PATH.
    Docker deployments should include ffmpeg in the container image.

    Args:
        video_path: Path to video file

    Returns:
        Path to extracted .wav audio file

    Raises:
        RuntimeError: If ffmpeg command fails
    """
    audio_path = audio_path_for_video(video_path)

    # Skip if already extracted
    if audio_path.exists():
        logger.info(f"Audio already extracted: {audio_path}")
        return audio_path

    logger.info(f"Extracting audio from {video_path.name} -> {audio_path.name}")

    # ffmpeg command to extract mono 16kHz wav
    cmd = [
        "ffmpeg",
        "-i",
        str(video_path),
        "-ar",
        "16000",  # 16kHz sample rate (required by many speech models)
        "-ac",
        "1",  # Mono channel
        "-y",  # Overwrite output file if exists
        str(audio_path),
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info(f"Successfully extracted audio to {audio_path}")
        return audio_path
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"ffmpeg failed for {video_path.name}: {exc.stderr}"
        ) from exc
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg not found in PATH. Please install ffmpeg: "
            "https://ffmpeg.org/download.html"
        ) from exc


# =============================================================================
# SRT Subtitle Parsing
# =============================================================================


def load_srt_segments(srt_path: Path) -> list[dict[str, Any]]:
    """
    Parse an SRT subtitle file into time-stamped text segments.

    Uses the `srt` library to parse subtitle format.

    AMBIGUITY NOTE: Lazy import of `srt` library to avoid DAG parse overhead.
    Assumes srt file is UTF-8 encoded. May fail on non-standard encodings.

    Args:
        srt_path: Path to .srt subtitle file

    Returns:
        List of dictionaries with keys:
        - start: float (seconds)
        - end: float (seconds)
        - text: str (subtitle content)
        - index: int (subtitle sequence number)

    Raises:
        ImportError: If srt library is not installed
        ValueError: If SRT file cannot be parsed
    """
    try:
        import srt  # Lazy import to avoid DAG parse time
    except ImportError as exc:
        raise ImportError(
            "srt library not installed. Install with: pip install srt"
        ) from exc

    logger.info(f"Loading SRT file: {srt_path}")

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            subtitle_generator = srt.parse(f.read())
            subtitles = list(subtitle_generator)
    except Exception as exc:
        raise ValueError(f"Failed to parse SRT file {srt_path}: {exc}") from exc

    segments: list[dict[str, Any]] = []
    for sub in subtitles:
        segments.append(
            {
                "index": sub.index,
                "start": sub.start.total_seconds(),
                "end": sub.end.total_seconds(),
                "text": sub.content.strip(),
            }
        )

    logger.info(f"Loaded {len(segments)} subtitle segments from {srt_path.name}")
    return segments


# =============================================================================
# Pyannote Speaker Diarization
# =============================================================================

# Global cache for pyannote pipeline to avoid reloading for every episode
_PYANNOTE_PIPELINE = None


def _get_pyannote_pipeline():
    """
    Lazy-load and cache the pyannote.audio diarization pipeline.

    AMBIGUITY NOTE: Imports torch and pyannote inside function to keep DAG
    parsing lightweight. Requires HF_TOKEN to be set for model download.

    Returns:
        Pyannote speaker diarization pipeline instance

    Raises:
        ImportError: If pyannote.audio or torch not installed
        ValueError: If HF_TOKEN not configured
    """
    global _PYANNOTE_PIPELINE

    if _PYANNOTE_PIPELINE is not None:
        return _PYANNOTE_PIPELINE

    if not HF_TOKEN:
        raise ValueError(
            "HF_TOKEN environment variable not set. Required for pyannote.audio model download. "
            "Set HF_TOKEN in .env after accepting model license on Hugging Face."
        )

    # Apply compatibility patches BEFORE importing pyannote
    _apply_torchaudio_compatibility_patches()
    _apply_huggingface_hub_compatibility_patches()

    try:
        from pyannote.audio import Pipeline  # Lazy import
    except ImportError as exc:
        raise ImportError(
            "pyannote.audio not installed. Install with: pip install pyannote.audio"
        ) from exc

    logger.info(f"Loading pyannote model: {PYANNOTE_MODEL}")

    # Set HF token for authentication - try multiple env var names
    import os

    os.environ["HF_TOKEN"] = HF_TOKEN
    os.environ["HUGGING_FACE_HUB_TOKEN"] = HF_TOKEN

    # Also try using huggingface_hub login
    try:
        from huggingface_hub import login

        login(token=HF_TOKEN, add_to_git_credential=False)
    except Exception as e:
        logger.warning(f"Could not login to HuggingFace Hub: {e}")

    try:
        _PYANNOTE_PIPELINE = Pipeline.from_pretrained(PYANNOTE_MODEL)
    except Exception as e:
        logger.error(f"Failed to load pyannote model: {e}")
        raise

    if _PYANNOTE_PIPELINE is None:
        raise RuntimeError(
            f"Pipeline.from_pretrained() returned None for model {PYANNOTE_MODEL}. "
            "Check HuggingFace token permissions and model license acceptance."
        )

    # Move to GPU if available (pyannote handles this automatically)
    # AMBIGUITY NOTE: GPU usage is automatic if torch detects CUDA.
    # For CPU-only, this will run on CPU (slower but functional).

    logger.info("Pyannote pipeline loaded successfully")
    return _PYANNOTE_PIPELINE


def diarize_wav(
    wav_path: Path,
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Run speaker diarization on a WAV audio file.

    Optional hints:
        num_speakers: exact number of speakers.
        min_speakers / max_speakers: range of speakers.

    These hints can be derived from database (known castaways in episode)
    or manually overridden for better accuracy.

    AMBIGUITY NOTE: Returns speaker clusters labeled as "SPEAKER_0", "SPEAKER_1", etc.
    These are NOT mapped to actual castaway names yet - that requires manual labeling
    or additional ML logic not implemented here.

    Args:
        wav_path: Path to .wav audio file (mono 16kHz)
        num_speakers: Exact number of speakers (mutually exclusive with min/max)
        min_speakers: Minimum number of speakers to detect
        max_speakers: Maximum number of speakers to detect

    Returns:
        List of speaker segments with keys:
        - start: float (seconds)
        - end: float (seconds)
        - speaker: str (e.g., "SPEAKER_0")
        - duration: float (seconds)

    Raises:
        RuntimeError: If diarization fails
    """
    pipeline = _get_pyannote_pipeline()

    diar_kwargs: dict[str, Any] = {}
    if num_speakers is not None:
        diar_kwargs["num_speakers"] = num_speakers
    else:
        if min_speakers is not None:
            diar_kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            diar_kwargs["max_speakers"] = max_speakers

    logger.info(f"Running diarization on {wav_path.name} with args: {diar_kwargs}")

    try:
        diarization = pipeline(str(wav_path), **diar_kwargs)
    except Exception as exc:
        raise RuntimeError(f"Diarization failed for {wav_path}: {exc}") from exc

    segments: list[dict[str, Any]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append(
            {
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker,
                "duration": turn.end - turn.start,
            }
        )

    logger.info(
        f"Diarization complete: {len(segments)} speaker segments, "
        f"{len(set(s['speaker'] for s in segments))} unique speakers detected"
    )
    return segments


# =============================================================================
# SRT + Diarization Alignment
# =============================================================================


def merge_speaker_segments(
    segments: list[dict[str, Any]],
    gap_tolerance: float = 0.3,
) -> list[dict[str, Any]]:
    """
    Merge adjacent speaker segments when:
      - they have the same 'speaker' label, and
      - the gap between segments is <= gap_tolerance (seconds).

    This reduces fragmentation before aligning to SRT segments.

    Args:
        segments: List of speaker segments from diarization
        gap_tolerance: Maximum gap (seconds) between segments to merge

    Returns:
        List of merged speaker segments
    """
    if not segments:
        return []

    # Ensure sorted by start time
    segments = sorted(segments, key=lambda s: s["start"])

    merged: list[dict[str, Any]] = []
    current = segments[0].copy()

    for seg in segments[1:]:
        same_speaker = seg["speaker"] == current["speaker"]
        gap = seg["start"] - current["end"]

        if same_speaker and gap <= gap_tolerance:
            # Extend current merged segment
            current["end"] = max(current["end"], seg["end"])
            current["duration"] = current["end"] - current["start"]
        else:
            merged.append(current)
            current = seg.copy()

    merged.append(current)

    logger.info(
        f"Merged {len(segments)} speaker segments into {len(merged)} "
        f"(gap_tolerance={gap_tolerance:.3f}s)"
    )
    return merged


def _compute_overlap(start1: float, end1: float, start2: float, end2: float) -> float:
    """
    Compute temporal overlap (in seconds) between two time intervals.

    Args:
        start1, end1: First interval
        start2, end2: Second interval

    Returns:
        Overlap duration in seconds (0 if no overlap)
    """
    overlap_start = max(start1, start2)
    overlap_end = min(end1, end2)
    return max(0.0, overlap_end - overlap_start)


def assign_speakers_to_srt(
    srt_segments: list[dict[str, Any]],
    speaker_segments: list[dict[str, Any]],
    tolerance: float = 0.3,
    min_overlap: float = 0.1,
) -> list[dict[str, Any]]:
    """
    Align SRT subtitle segments to speaker diarization segments by time overlap.

    A small 'tolerance' (seconds) is added on both sides of each subtitle segment
    to absorb timing differences between subtitles and diarization.

    If the best overlap for a subtitle segment is less than min_overlap seconds,
    its speaker is set to "UNKNOWN".

    Args:
        srt_segments: List of subtitle segments from load_srt_segments()
        speaker_segments: List of speaker segments from diarize_wav()
        tolerance: Expand subtitle window by this many seconds on each side
        min_overlap: Minimum overlap (seconds) required to assign a speaker

    Returns:
        List of aligned segments with keys:
        - All fields from srt_segments
        - speaker: str (assigned speaker label or "UNKNOWN")
        - speaker_confidence: float (overlap duration in seconds)
    """
    aligned: list[dict[str, Any]] = []

    for srt_seg in srt_segments:
        # Expand subtitle window by tolerance seconds on each side
        srt_start = srt_seg["start"] - tolerance
        srt_end = srt_seg["end"] + tolerance

        # Find speaker with maximum overlap
        best_speaker = "UNKNOWN"
        best_overlap = 0.0

        for spk_seg in speaker_segments:
            overlap = _compute_overlap(
                srt_start, srt_end, spk_seg["start"], spk_seg["end"]
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = spk_seg["speaker"]

        # Enforce minimum overlap threshold
        if best_overlap < min_overlap:
            best_speaker = "UNKNOWN"

        aligned.append(
            {
                **srt_seg,
                "speaker": best_speaker,
                "speaker_confidence": best_overlap,  # Overlap duration in seconds
            }
        )

    logger.info(
        f"Aligned {len(aligned)} subtitle segments to speakers "
        f"(tolerance={tolerance:.3f}s, min_overlap={min_overlap:.3f}s). "
        f"{sum(1 for s in aligned if s['speaker'] == 'UNKNOWN')} had no speaker match."
    )
    return aligned


# =============================================================================
# Episode Video Discovery
# =============================================================================


def list_all_episode_videos() -> list[str]:
    """
    Discover all Survivor episode video files in BASE_VIDEO_DIR.

    AMBIGUITY NOTE: Searches for common video extensions (.mkv, .mp4, .avi).
    Filters for files containing SxxExx pattern. Users with different file
    organization may need to adjust this logic.

    Returns:
        List of absolute paths (as strings) to video files

    Raises:
        RuntimeError: If BASE_VIDEO_DIR doesn't exist or no episodes found
    """
    if not BASE_VIDEO_DIR.exists():
        raise RuntimeError(
            f"Video directory does not exist: {BASE_VIDEO_DIR}. "
            "Ensure NAS is mounted or update SURVIVOR_VIDEO_DIR in .env"
        )

    # Search for common video file extensions (recursively in subdirectories)
    video_extensions = ["*.mkv", "*.mp4", "*.avi", "*.mov"]
    video_files: list[Path] = []

    for ext in video_extensions:
        video_files.extend(BASE_VIDEO_DIR.rglob(ext))

    # Filter for files that match episode pattern (SxxExx)
    episode_pattern = re.compile(r"[sS]\d{2}[eE]\d{2}")
    episode_videos = [str(vf) for vf in video_files if episode_pattern.search(vf.name)]

    if not episode_videos:
        raise RuntimeError(
            f"No episode video files found in {BASE_VIDEO_DIR}. "
            f"Searched extensions: {video_extensions}"
        )

    logger.info(f"Found {len(episode_videos)} episode videos in {BASE_VIDEO_DIR}")
    return sorted(episode_videos)


# =============================================================================
# Database Helper Functions
# =============================================================================


def _insert_dataframe_to_table(
    df: pd.DataFrame,
    table_name: str,
    conn,
    unique_constraint_columns: Optional[list[str]] = None,
) -> int:
    """
    Insert DataFrame into database table with optional upsert on conflict.

    Simple helper for inserting diarization data - does NOT fetch from external sources.

    Args:
        df: DataFrame with columns matching table schema
        table_name: Fully qualified table name (e.g., "bronze.diarization_segments")
        conn: Database connection
        unique_constraint_columns: Columns for ON CONFLICT clause (performs upsert if specified)

    Returns:
        Number of rows inserted/updated
    """
    if df.empty:
        logger.warning(f"Empty DataFrame provided for {table_name}, skipping insert")
        return 0

    # Build column list and placeholders
    columns = df.columns.tolist()
    placeholders = ", ".join(["%s"] * len(columns))
    column_names = ", ".join(columns)

    # Build base INSERT statement
    insert_sql = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"

    # Add ON CONFLICT clause if unique constraints provided
    if unique_constraint_columns:
        conflict_cols = ", ".join(unique_constraint_columns)
        update_cols = [col for col in columns if col not in unique_constraint_columns]
        update_set = ", ".join([f"{col} = EXCLUDED.{col}" for col in update_cols])
        insert_sql += f" ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_set}"

    # Execute batch insert
    with conn.cursor() as cur:
        rows = [tuple(row) for row in df.itertuples(index=False, name=None)]
        cur.executemany(insert_sql, rows)

    conn.commit()
    logger.info(f"Inserted {len(df)} rows into {table_name}")
    return len(df)


# =============================================================================
# Per-Episode Processing with Database Storage
# =============================================================================


def _get_speaker_hints_from_db(
    conn, version_season: str, episode: int
) -> tuple[Optional[int], Optional[int]]:
    """
    Query database for episode metadata to derive speaker count hints.

    Returns (min_speakers, max_speakers) based on known castaways in the episode.
    Returns (None, None) if data unavailable or query fails.

    Queries:
    - bronze.castaways to find who's competing in this season
    - bronze.boot_mapping to determine who's still in the game at this episode

    Args:
        conn: Database connection
        version_season: e.g., "US01"
        episode: Episode number

    Returns:
        Tuple of (min_speakers, max_speakers) or (None, None)
    """
    try:
        with conn.cursor() as cur:
            # Count active castaways at this episode
            # Active = appeared in season AND not yet eliminated OR eliminated after this episode
            cur.execute(
                """
                SELECT COUNT(DISTINCT c.castaway_id) as active_count
                FROM bronze.castaways c
                LEFT JOIN bronze.boot_mapping bm
                    ON c.castaway_id = bm.castaway_id
                    AND c.version_season = bm.version_season
                WHERE c.version_season = %s
                  AND c.castaway_id IS NOT NULL
                  AND (
                    bm.episode IS NULL  -- Never eliminated (winner/finalists)
                    OR bm.episode >= %s  -- Eliminated at or after this episode
                  )
                """,
                (version_season, episode),
            )
            result = cur.fetchone()

            if result and result[0] and result[0] > 0:
                active_count = int(result[0])

                # Conservative estimates:
                # min_speakers: At least 2-3 main speakers (allow for quiet episodes)
                # max_speakers: Active castaways + host + possible guests/loved ones
                min_speakers = max(2, active_count - 3)
                max_speakers = active_count + 4  # +1 for host, +3 buffer for guests

                logger.info(
                    f"Speaker hints for {version_season} E{episode:02d}: "
                    f"{active_count} active castaways → min={min_speakers}, max={max_speakers}"
                )
                return min_speakers, max_speakers
            else:
                logger.debug(
                    f"No castaway data found for {version_season} E{episode:02d}. "
                    "Using pyannote auto-detection."
                )
                return None, None

    except Exception as e:
        logger.warning(
            f"Failed to query speaker hints from database: {e}. "
            "Using pyannote auto-detection."
        )
        return None, None


def process_single_episode(
    video_path_str: str, conn, ingest_run_id: str
) -> tuple[int, str]:
    """
    Process a single Survivor episode: extract audio, diarize, align subtitles.

    Saves outputs to BOTH:
    1. Parquet file (with full subtitle text for NLP processing)
    2. Database bronze table (metadata only, NO subtitle text for copyright)

    This is the main per-episode workflow that can be called locally or
    distributed via Ray.

    Args:
        video_path_str: Absolute path to video file (as string for Ray serialization)
        conn: psycopg2 connection object
        ingest_run_id: UUID of current ingestion run for tracking

    Returns:
        Tuple of (database rows inserted, parquet file path)

    Raises:
        Various exceptions from extraction, diarization, or alignment steps
    """
    video_path = Path(video_path_str)
    episode_id = extract_episode_id(video_path)
    season_num, episode_num = parse_episode_numbers(episode_id)
    version_season = build_version_season(VERSION_COUNTRY, season_num)

    logger.info(
        f"Processing episode {version_season} E{episode_num:02d}: {video_path.name}"
    )

    # Step 1: Find matching SRT
    srt_path = find_matching_srt(video_path)
    logger.info(f"  Found subtitle: {srt_path.name}")

    # Step 2: Extract audio (or use existing)
    audio_path = extract_audio_for_video(video_path)

    # Step 3: Run diarization with database-driven speaker hints
    min_speakers, max_speakers = _get_speaker_hints_from_db(
        conn, version_season, episode_num
    )
    raw_speaker_segments = diarize_wav(
        audio_path, min_speakers=min_speakers, max_speakers=max_speakers
    )

    # Drop ultra-short segments (likely noise or false positives)
    raw_speaker_segments = [
        seg
        for seg in raw_speaker_segments
        if seg.get("duration", seg["end"] - seg["start"]) >= 0.15
    ]

    # Merge adjacent same-speaker segments to reduce fragmentation
    speaker_segments = merge_speaker_segments(raw_speaker_segments, gap_tolerance=0.3)

    # Step 4: Load and align subtitles with temporal tolerance
    srt_segments = load_srt_segments(srt_path)
    aligned_segments = assign_speakers_to_srt(
        srt_segments,
        speaker_segments,
        tolerance=0.3,
        min_overlap=0.1,
    )

    # Step 5: Build full DataFrame with ALL data
    df = pd.DataFrame(aligned_segments)
    df["version_country"] = VERSION_COUNTRY
    df["version_season"] = version_season
    df["season"] = season_num
    df["episode"] = episode_num
    df["episode_id"] = episode_id
    df["subtitle_index"] = df["index"]
    df["start_time"] = df["start"]
    df["end_time"] = df["end"]
    df["speaker_label"] = df["speaker"]
    df["subtitle_text"] = df["text"]
    df["word_count"] = df["text"].apply(lambda t: len(str(t).split()))

    # Step 5b: Apply manual castaway labels (if available)
    from .labels import apply_speaker_labels

    df = apply_speaker_labels(df)
    logger.info(f"  Applied castaway labels: {df['castaway'].value_counts().to_dict()}")

    # Step 6: Save to parquet WITH subtitle text and castaway labels (for local NLP processing)
    # This contains copyrighted content and stays local only
    DIARIZED_PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = (
        DIARIZED_PARQUET_DIR / f"{version_season}_E{episode_num:02d}_diarized.parquet"
    )
    df.to_parquet(parquet_path, index=False)
    logger.info(f"  Saved parquet with text and labels: {parquet_path.name}")

    # Step 7: Save to database WITHOUT subtitle text (copyright compliance)
    # Only timing metadata - allows distributed analysis without copyright issues
    db_df = df[
        [
            "version_season",
            "episode",
            "subtitle_index",
            "start_time",
            "end_time",
            "speaker_label",
        ]
    ].copy()
    db_df["ingest_run_id"] = ingest_run_id

    rows_inserted = _insert_dataframe_to_table(
        df=db_df,
        table_name="bronze.diarization_segments",
        conn=conn,
        unique_constraint_columns=["version_season", "episode", "subtitle_index"],
    )

    logger.info(
        f"Episode {version_season} E{episode_num:02d} complete: "
        f"{rows_inserted} segments to DB, parquet at {parquet_path.name}"
    )
    return rows_inserted, str(parquet_path)


# =============================================================================
# NLP Feature Extraction from Parquet Files
# =============================================================================


def build_speech_features_from_parquet(conn, ingest_run_id: str) -> int:
    """
    Build NLP-derived speech features from diarized parquet files.

    Reads all *_diarized.parquet files (which contain subtitle text),
    computes aggregated features using Python NLP libraries, and saves
    to silver.castaway_episode_speech_features table.

    IMPORTANT: This function processes copyrighted subtitle text that is
    stored locally in parquet files. The OUTPUT contains NO text, only
    derived statistical features suitable for public database storage.

    Features computed:
    - Basic: utterance_count, total_speaking_seconds, share_of_voice
    - Text-derived: total_words, mean_words_per_utterance, vocabulary_richness
    - Future: sentiment scores, topic distributions, linguistic complexity (user adds)

    Args:
        conn: Database connection object
        ingest_run_id: UUID of current ingestion run for tracking

    Returns:
        Number of castaway-episode feature rows inserted

    Raises:
        RuntimeError: If no diarized parquet files found
        Various database errors if connection/insert fails
    """
    logger.info("Building NLP speech features from diarized parquet files...")

    # Find all diarized parquet files
    parquet_files = list(DIARIZED_PARQUET_DIR.glob("*_diarized.parquet"))

    if not parquet_files:
        raise RuntimeError(
            f"No diarized parquet files found in {DIARIZED_PARQUET_DIR}. "
            "Run episode processing first."
        )

    logger.info(
        f"Loading {len(parquet_files)} episode parquet files for feature extraction..."
    )

    # Load and concatenate all episodes
    dfs = [pd.read_parquet(pf) for pf in parquet_files]
    all_data = pd.concat(dfs, ignore_index=True)

    logger.info(
        f"Loaded {len(all_data)} subtitle segments across {len(parquet_files)} episodes"
    )

    # Compute per-(episode, speaker) aggregates
    logger.info("Computing speech features per episode-speaker...")

    # Calculate duration for each segment
    all_data["duration"] = all_data["end_time"] - all_data["start_time"]

    # Basic speaking metrics
    features = (
        all_data.groupby(["version_season", "episode", "speaker_label"])
        .agg(
            utterance_count=("subtitle_index", "count"),
            total_speaking_seconds=("duration", "sum"),
            mean_utterance_duration=("duration", "mean"),
            total_words=("word_count", "sum"),
            mean_words_per_utterance=("word_count", "mean"),
        )
        .reset_index()
    )

    # Calculate vocabulary richness (unique words / total words)
    def calc_vocabulary_richness(group):
        all_text = " ".join(group["subtitle_text"].astype(str))
        words = all_text.lower().split()
        if len(words) == 0:
            return 0.0
        return len(set(words)) / len(words)

    vocab_richness = (
        all_data.groupby(["version_season", "episode", "speaker_label"])
        .apply(calc_vocabulary_richness)
        .reset_index(name="vocabulary_richness")
    )

    features = features.merge(
        vocab_richness, on=["version_season", "episode", "speaker_label"], how="left"
    )

    # Calculate share of voice within each episode
    episode_totals = (
        features.groupby(["version_season", "episode"])["total_speaking_seconds"]
        .sum()
        .reset_index(name="episode_total_speaking_seconds")
    )
    features = features.merge(
        episode_totals, on=["version_season", "episode"], how="left"
    )
    features["share_of_voice"] = (
        features["total_speaking_seconds"] / features["episode_total_speaking_seconds"]
    )
    features = features.drop(columns=["episode_total_speaking_seconds"])

    # =============================================================================
    # PLACEHOLDER: Advanced Acoustic & Linguistic Features
    # =============================================================================
    # Future enhancements - add columns for:
    #
    # ACOUSTIC FEATURES (requires audio analysis libraries like librosa, praat-parselmouth):
    # - mean_pitch, pitch_std: Average/variability of fundamental frequency (F0)
    # - mean_intensity, intensity_std: Speaking energy/loudness
    # - formant_f1_mean, formant_f2_mean: Vowel space characteristics
    # - speech_rate: Words per second or syllables per second
    # - pause_frequency: Number of silent gaps per minute
    # - jitter, shimmer: Voice quality metrics
    #
    # PROSODY FEATURES (emotional/stylistic):
    # - pitch_range: Max pitch - min pitch (emotional expressiveness)
    # - energy_variance: Variability in speaking intensity (engagement)
    # - speaking_tempo_variance: Consistency of speech rate
    #
    # LINGUISTIC FEATURES (requires NLP libraries like spaCy, NLTK):
    # - lexical_diversity: Type-token ratio, moving average TTR
    # - sentiment_score: Positive/negative/neutral from sentiment analysis
    # - formality_score: Formal vs casual language patterns
    # - complexity_score: Sentence length, subordinate clauses, etc.
    # - topic_distributions: NMF/LDA topic weights per speaker-episode
    # - named_entity_counts: References to people, places, events
    #
    # EMBEDDINGS (private/local only - NOT for database):
    # - voice_embedding_path: Reference to speaker voice embeddings (.npy file)
    #   stored locally for speaker recognition/verification tasks
    # - linguistic_embedding_path: Sentence/doc embeddings for semantic similarity
    #
    # NOTE: Text and embeddings stay in local parquet files for copyright/privacy.
    # Only derived statistics go to public database.
    # =============================================================================

    # Add ingest_run_id for tracking
    features["ingest_run_id"] = ingest_run_id

    logger.info(f"Computed {len(features)} castaway-episode feature records")

    # Save to silver.castaway_episode_speech_features table
    rows_inserted = _insert_dataframe_to_table(
        df=features,
        table_name="silver.castaway_episode_speech_features",
        conn=conn,
        unique_constraint_columns=["version_season", "episode", "speaker_label"],
    )

    logger.info(
        f"Speech features complete: {rows_inserted} rows saved to silver.castaway_episode_speech_features"
    )

    return rows_inserted
