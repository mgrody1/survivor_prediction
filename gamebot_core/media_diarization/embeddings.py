"""Speaker embedding extraction and castaway label propagation.

This module computes cluster-level speaker embeddings from diarized audio segments
and uses them to automatically propagate castaway labels to unlabeled speaker clusters.

PRIVACY NOTE: Embeddings are ONLY stored in local parquet files, never in the database.
This keeps voice biometric data private while allowing advanced speaker recognition.

Workflow:
---------
1. compute_cluster_embeddings_for_episode() - Extract embeddings for each speaker cluster
2. save_cluster_embeddings() - Save to local parquet file
3. load_all_embeddings() - Load embeddings across episodes
4. propagate_castaway_labels() - Use cosine similarity to suggest labels for UNKNOWN clusters
5. auto_label_unlabeled_clusters() - End-to-end auto-labeling workflow

Architecture:
-------------
- Lazy imports of heavy libraries (pyannote, torch) inside functions
- Embeddings stored as lists in DataFrame, converted to numpy for computation
- Centroid-based matching for castaway label propagation
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    AUDIO_OUT_DIR,
    DIARIZED_PARQUET_DIR,
    EMBEDDINGS_DIR,
    HF_TOKEN,
    MANUAL_LABELS_PATH,
    VERSION_COUNTRY,
)

logger = logging.getLogger(__name__)

# Global cache for embedding model (avoid reloading)
_EMBEDDING_MODEL = None


def _get_embedding_model():
    """
    Lazy-load pyannote speaker embedding model.

    Heavy imports (torch, torchaudio, pyannote) happen here, not at module import time.
    This keeps Airflow DAG parsing lightweight.

    Returns:
        Pyannote Inference model for speaker embedding extraction

    Raises:
        ValueError: If HF_TOKEN not configured
        ImportError: If pyannote.audio not installed
    """
    global _EMBEDDING_MODEL

    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL

    if not HF_TOKEN:
        raise ValueError(
            "HF_TOKEN not set for embedding model. "
            "Set HF_TOKEN in .env after accepting model license on Hugging Face."
        )

    # Import compatibility patches from pipeline module
    from .pipeline import (
        _apply_huggingface_hub_compatibility_patches,
        _apply_torchaudio_compatibility_patches,
    )

    _apply_torchaudio_compatibility_patches()
    _apply_huggingface_hub_compatibility_patches()

    try:
        from pyannote.audio import Inference  # Lazy import
    except ImportError as exc:
        raise ImportError(
            "pyannote.audio not installed. Install with: pip install pyannote.audio"
        ) from exc

    # Set HF token for authentication
    import os

    os.environ["HF_TOKEN"] = HF_TOKEN
    os.environ["HUGGING_FACE_HUB_TOKEN"] = HF_TOKEN

    # Use pyannote embedding model for speaker recognition
    model_name = "pyannote/embedding"
    logger.info(f"Loading pyannote embedding model: {model_name}")

    try:
        _EMBEDDING_MODEL = Inference(model_name, window="whole")
    except Exception as e:
        logger.error(f"Failed to load embedding model: {e}")
        raise

    logger.info("Embedding model loaded successfully")
    return _EMBEDDING_MODEL


def _load_audio_segment(
    audio_path: Path, start_time: float, end_time: float
) -> np.ndarray:
    """
    Load a specific time segment from an audio file.

    Uses torchaudio to load and slice audio by time.

    Args:
        audio_path: Path to .wav audio file
        start_time: Start time in seconds
        end_time: End time in seconds

    Returns:
        Audio waveform as numpy array (mono, 16kHz)

    Raises:
        RuntimeError: If audio loading fails
    """
    try:
        import torchaudio  # Lazy import
    except ImportError as exc:
        raise ImportError(
            "torchaudio not installed. Install with: pip install torchaudio"
        ) from exc

    try:
        waveform, sample_rate = torchaudio.load(str(audio_path))
    except Exception as exc:
        raise RuntimeError(f"Failed to load audio file {audio_path}: {exc}") from exc

    # Convert time to sample indices
    start_sample = int(start_time * sample_rate)
    end_sample = int(end_time * sample_rate)

    # Slice audio segment
    segment = waveform[:, start_sample:end_sample]

    # Convert to mono if stereo
    if segment.shape[0] > 1:
        segment = segment.mean(dim=0, keepdim=True)

    return segment.numpy()


def compute_cluster_embeddings_for_episode(
    version_season: str, episode: int
) -> pd.DataFrame:
    """
    Compute speaker embeddings for each cluster in an episode.

    Loads the diarized parquet file and audio, then computes an average embedding
    for each speaker_label by:
    1. Extracting all audio segments for that speaker
    2. Computing embeddings for each segment
    3. Averaging embeddings to create a cluster-level representation

    Args:
        version_season: Episode identifier (e.g., "US01")
        episode: Episode number

    Returns:
        DataFrame with columns:
        - version_season
        - episode
        - speaker_label
        - castaway
        - embedding (list of floats)

    Raises:
        FileNotFoundError: If parquet or audio file not found
        RuntimeError: If embedding extraction fails
    """
    # Load diarized parquet file
    parquet_path = (
        DIARIZED_PARQUET_DIR / f"{version_season}_E{episode:02d}_diarized.parquet"
    )

    if not parquet_path.exists():
        raise FileNotFoundError(
            f"Diarized parquet not found: {parquet_path}. "
            "Run diarization pipeline first."
        )

    df = pd.read_parquet(parquet_path)
    logger.info(f"Loaded {len(df)} segments from {parquet_path.name}")

    # Load audio file
    episode_id = f"S{int(version_season[-2:]):02d}E{episode:02d}"
    audio_path = AUDIO_OUT_DIR / f"{VERSION_COUNTRY}{episode_id}.wav"

    if not audio_path.exists():
        raise FileNotFoundError(
            f"Audio file not found: {audio_path}. Run audio extraction first."
        )

    # Get embedding model
    embedding_model = _get_embedding_model()

    # Compute embeddings for each speaker cluster
    cluster_embeddings = []

    for speaker_label in df["speaker_label"].unique():
        speaker_df = df[df["speaker_label"] == speaker_label]
        castaway = (
            speaker_df["castaway"].iloc[0]
            if "castaway" in speaker_df.columns
            else "UNKNOWN"
        )

        logger.debug(
            f"Computing embedding for {speaker_label} ({len(speaker_df)} segments, castaway={castaway})"
        )

        # Collect embeddings for all segments of this speaker
        segment_embeddings = []

        for _, row in speaker_df.iterrows():
            start = row["start_time"]
            end = row["end_time"]
            duration = end - start

            # Skip very short segments (< 0.5s) - not enough for reliable embeddings
            if duration < 0.5:
                continue

            try:
                # Load audio segment
                audio_segment = _load_audio_segment(audio_path, start, end)

                # Compute embedding
                # pyannote expects dict with 'waveform' and 'sample_rate'
                segment_dict = {
                    "waveform": audio_segment,
                    "sample_rate": 16000,  # Our audio is always 16kHz mono
                }

                embedding = embedding_model(segment_dict)

                # Convert to numpy array and store
                if hasattr(embedding, "data"):
                    embedding = embedding.data  # Extract numpy from pyannote Segment

                segment_embeddings.append(embedding)

            except Exception as e:
                logger.warning(
                    f"Failed to extract embedding for segment {start:.2f}-{end:.2f}s: {e}"
                )
                continue

        if not segment_embeddings:
            logger.warning(f"No valid embeddings for {speaker_label}, skipping")
            continue

        # Average all segment embeddings to get cluster-level embedding
        cluster_embedding = np.mean(segment_embeddings, axis=0)

        cluster_embeddings.append(
            {
                "version_season": version_season,
                "episode": episode,
                "speaker_label": speaker_label,
                "castaway": castaway,
                "embedding": cluster_embedding.tolist(),  # Store as list for parquet
            }
        )

    result_df = pd.DataFrame(cluster_embeddings)
    logger.info(
        f"Computed embeddings for {len(result_df)} speaker clusters in "
        f"{version_season} E{episode:02d}"
    )

    return result_df


def save_cluster_embeddings(
    emb_df: pd.DataFrame, version_season: str, episode: int
) -> Path:
    """
    Save cluster embeddings to parquet file.

    Embeddings are saved locally only - NEVER to the database.
    This keeps voice biometric data private.

    Args:
        emb_df: DataFrame with embedding data
        version_season: Episode identifier
        episode: Episode number

    Returns:
        Path to saved parquet file
    """
    output_path = (
        EMBEDDINGS_DIR / f"{version_season}_E{episode:02d}_speaker_embeddings.parquet"
    )

    emb_df.to_parquet(output_path, index=False)
    logger.info(f"Saved {len(emb_df)} speaker embeddings to {output_path.name}")

    return output_path


def load_all_embeddings(version_season: str) -> pd.DataFrame:
    """
    Load all speaker embedding parquet files for a given season.

    Args:
        version_season: Season identifier (e.g., "US01")

    Returns:
        DataFrame with all embeddings concatenated

    Raises:
        RuntimeError: If no embedding files found
    """
    # Find all embedding files for this season
    pattern = f"{version_season}_E*_speaker_embeddings.parquet"
    embedding_files = list(EMBEDDINGS_DIR.glob(pattern))

    if not embedding_files:
        raise RuntimeError(
            f"No embedding files found for {version_season} in {EMBEDDINGS_DIR}. "
            "Run compute_cluster_embeddings_for_episode() first."
        )

    logger.info(f"Loading {len(embedding_files)} embedding files for {version_season}")

    # Load and concatenate all files
    dfs = [pd.read_parquet(f) for f in sorted(embedding_files)]
    all_embeddings = pd.concat(dfs, ignore_index=True)

    logger.info(
        f"Loaded {len(all_embeddings)} speaker embeddings across "
        f"{len(embedding_files)} episodes"
    )

    return all_embeddings


def _cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """
    Compute cosine similarity between two vectors.

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        Cosine similarity (0 to 1, where 1 is identical)
    """
    dot_product = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


def propagate_castaway_labels(
    emb_df: pd.DataFrame, similarity_threshold: float = 0.8
) -> pd.DataFrame:
    """
    Propagate castaway labels to unlabeled clusters using embedding similarity.

    This function is KEY to handling inconsistent speaker numbering across episodes.
    Pyannote assigns cluster IDs (SPEAKER_0, SPEAKER_1, etc.) independently for
    each episode, so the same person may have different IDs in different episodes.

    By comparing embeddings, we can identify that:
    - Episode 1: SPEAKER_0 = "Jeff Probst" (manually labeled)
    - Episode 2: SPEAKER_7 has similar embedding → likely "Jeff Probst"

    For each castaway with known labels (from manual CSV), computes a centroid
    embedding (average of all their cluster embeddings across all labeled episodes).
    Then matches unlabeled clusters to the nearest castaway centroid using cosine
    similarity.

    Args:
        emb_df: DataFrame with columns:
            - version_season, episode, speaker_label, castaway, embedding
        similarity_threshold: Minimum cosine similarity to assign a label (0-1)

    Returns:
        DataFrame with updated castaway column (unlabeled clusters may be assigned)

    Note:
        This does NOT modify the input DataFrame in place.
        Returns a new DataFrame with updated labels.
    """
    df = emb_df.copy()

    # Convert embedding lists to numpy arrays
    df["embedding_array"] = df["embedding"].apply(np.array)

    # Separate labeled and unlabeled clusters
    labeled = df[df["castaway"] != "UNKNOWN"].copy()
    unlabeled = df[df["castaway"] == "UNKNOWN"].copy()

    if labeled.empty:
        logger.warning("No labeled clusters found - cannot propagate labels")
        return df

    if unlabeled.empty:
        logger.info("All clusters already labeled - no propagation needed")
        return df

    logger.info(
        f"Propagating labels: {len(labeled)} labeled clusters "
        f"(from {labeled['episode'].nunique()} episodes), "
        f"{len(unlabeled)} unlabeled clusters "
        f"(from {unlabeled['episode'].nunique()} episodes)"
    )

    # Compute centroid embedding for each castaway (across ALL labeled episodes)
    castaway_centroids = {}

    for castaway in labeled["castaway"].unique():
        castaway_embeddings = labeled[labeled["castaway"] == castaway][
            "embedding_array"
        ].tolist()
        centroid = np.mean(castaway_embeddings, axis=0)
        castaway_centroids[castaway] = centroid
        logger.debug(
            f"Computed centroid for {castaway} from {len(castaway_embeddings)} "
            f"clusters across episodes {sorted(labeled[labeled['castaway'] == castaway]['episode'].unique())}"
        )

    # Match unlabeled clusters to castaway centroids
    propagated_labels = []

    for idx, row in unlabeled.iterrows():
        cluster_embedding = row["embedding_array"]

        # Compute similarity to each castaway centroid
        similarities = {}
        for castaway, centroid in castaway_centroids.items():
            sim = _cosine_similarity(cluster_embedding, centroid)
            similarities[castaway] = sim

        # Find best match
        best_castaway = max(similarities, key=similarities.get)
        best_similarity = similarities[best_castaway]

        # Only assign if similarity exceeds threshold
        if best_similarity >= similarity_threshold:
            df.loc[idx, "castaway"] = best_castaway
            propagated_labels.append(
                {
                    "version_season": row["version_season"],
                    "episode": row["episode"],
                    "speaker_label": row["speaker_label"],
                    "suggested_castaway": best_castaway,
                    "similarity": best_similarity,
                }
            )
            logger.debug(
                f"Propagated label: E{row['episode']:02d} {row['speaker_label']} → "
                f"{best_castaway} (similarity={best_similarity:.3f})"
            )

    # Drop temporary embedding_array column
    df = df.drop(columns=["embedding_array"])

    logger.info(
        f"Propagated {len(propagated_labels)} labels across episodes "
        f"(threshold={similarity_threshold:.2f})"
    )

    return df


def auto_label_unlabeled_clusters(
    version_season: str, similarity_threshold: float = 0.8
) -> Path:
    """
    End-to-end workflow: load embeddings, propagate labels, save suggestions.

    This function:
    1. Loads all embeddings for the season
    2. Propagates castaway labels to unlabeled clusters
    3. Saves suggested labels to a CSV for human review

    IMPORTANT: This does NOT automatically update the manual labels CSV.
    The output is a separate file with suggestions that the user can review
    and manually merge into survivor_speaker_labels.csv.

    Args:
        version_season: Season identifier (e.g., "US01")
        similarity_threshold: Minimum cosine similarity to assign a label

    Returns:
        Path to the auto-labels CSV file

    Raises:
        RuntimeError: If no embeddings found for the season
    """
    logger.info(
        f"Starting auto-label workflow for {version_season} "
        f"(threshold={similarity_threshold:.2f})"
    )

    # Load all embeddings for this season
    emb_df = load_all_embeddings(version_season)

    # Propagate labels
    updated = propagate_castaway_labels(
        emb_df, similarity_threshold=similarity_threshold
    )

    # Extract only the newly-assigned labels (previously UNKNOWN)
    was_unknown = emb_df["castaway"] == "UNKNOWN"
    now_labeled = updated["castaway"] != "UNKNOWN"
    suggestions = updated[was_unknown & now_labeled].copy()

    # Prepare output CSV (episode-specific labels for review)
    output_df = suggestions[
        ["version_season", "episode", "speaker_label", "castaway"]
    ].copy()
    output_df["confidence"] = "auto"
    output_df["notes"] = f"Auto-labeled with similarity >= {similarity_threshold:.2f}"

    # Save to CSV
    out_path = EMBEDDINGS_DIR / f"{version_season}_auto_labels.csv"
    output_df.to_csv(out_path, index=False)

    logger.info(
        f"Auto-label workflow complete: {len(output_df)} suggestions written to {out_path.name}"
    )
    logger.info(
        "Review the suggestions and manually merge approved labels into "
        f"{MANUAL_LABELS_PATH}"
    )

    return out_path
