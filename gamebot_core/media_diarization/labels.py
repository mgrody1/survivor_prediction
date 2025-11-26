"""Manual castaway label management for speaker diarization.

This module handles the mapping from diarization speaker_label (e.g., "SPEAKER_0")
to actual castaway names and IDs through a CSV file maintained by the user.

CSV Format:
-----------
version_season,episode,speaker_label,castaway_id,castaway,confidence,notes
US01,1,SPEAKER_0,US01jeffp01,Jeff Probst,high,Host - appears in all episodes
US01,1,SPEAKER_1,US01richardh01,Richard Hatch,high,Winner - distinctive voice
US01,2,SPEAKER_7,US01jeffp01,Jeff Probst,high,Matched via embedding similarity

IMPORTANT: Speaker cluster numbers (SPEAKER_0, SPEAKER_1, etc.) are assigned
by pyannote.audio independently for each episode. The same person may be
SPEAKER_0 in episode 1 but SPEAKER_7 in episode 2.

Workflow:
1. Run diarization on all episodes (batch processing)
2. Manually label speaker clusters in episode 1 (this CSV)
3. Compute embeddings for episode 1
4. For episode 2+, use embedding similarity to auto-suggest labels
   (review and merge approved labels into this CSV)
5. Process episodes sequentially, accumulating embedding reference library

The 'confidence' and 'notes' columns are optional and ignored by the code -
they're for human reference during manual labeling.

The 'castaway_id' field links to bronze.castaway_details table in the database.
"""

from __future__ import annotations

import logging

import pandas as pd

from .config import MANUAL_LABELS_PATH

logger = logging.getLogger(__name__)


def load_speaker_labels() -> pd.DataFrame:
    """
    Load manual speaker->castaway labels from CSV.

    Returns an empty DataFrame with expected columns if the file does not exist.
    This allows the pipeline to run even without manual labels (all castaways
    will be "UNKNOWN").

    Returns:
        DataFrame with columns: version_season, episode, speaker_label,
        castaway_id, castaway

    Raises:
        ValueError: If CSV exists but is missing required columns
    """
    if not MANUAL_LABELS_PATH.exists():
        logger.warning(
            f"Manual labels file not found: {MANUAL_LABELS_PATH}. "
            "All speaker clusters will be labeled as 'UNKNOWN'. "
            "Create the file to add manual castaway labels."
        )
        return pd.DataFrame(
            columns=[
                "version_season",
                "episode",
                "speaker_label",
                "castaway_id",
                "castaway",
            ]
        )

    try:
        labels = pd.read_csv(MANUAL_LABELS_PATH)
    except Exception as e:
        logger.error(f"Failed to read manual labels CSV: {e}")
        return pd.DataFrame(
            columns=[
                "version_season",
                "episode",
                "speaker_label",
                "castaway_id",
                "castaway",
            ]
        )

    # Validate required columns
    expected_cols = {
        "version_season",
        "episode",
        "speaker_label",
        "castaway_id",
        "castaway",
    }
    missing = expected_cols - set(labels.columns)
    if missing:
        raise ValueError(
            f"Manual labels file is missing required columns: {missing}. "
            f"Expected columns: {expected_cols}"
        )

    # Keep only required columns (drop optional confidence, notes)
    labels = labels[list(expected_cols)].copy()

    logger.info(
        f"Loaded {len(labels)} manual labels from {MANUAL_LABELS_PATH.name} "
        f"({labels['castaway'].nunique()} unique castaways across "
        f"{labels['episode'].nunique()} episodes)"
    )
    return labels


def apply_speaker_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge manual castaway labels and IDs into a diarized DataFrame.

    Expected input DataFrame columns:
        - version_season: str (e.g., "US01")
        - episode: int (e.g., 1)
        - speaker_label: str (e.g., "SPEAKER_0")

    Adds 'castaway_id' and 'castaway' columns based on manual labels CSV.
    Unlabeled rows (no match in CSV) get castaway='UNKNOWN' and castaway_id=''.

    NOTE: Labels are episode-specific because pyannote assigns speaker cluster
    numbers independently for each episode. Use embedding similarity to propagate
    labels across episodes.

    Args:
        df: Diarized DataFrame with speaker clusters

    Returns:
        DataFrame with added 'castaway_id' and 'castaway' columns

    Note:
        This function does NOT modify the input DataFrame in place.
        It returns a new DataFrame with the castaway columns added.
    """
    labels = load_speaker_labels()
    df = df.copy()

    if labels.empty:
        logger.debug("No manual labels available, setting all castaways to UNKNOWN")
        df["castaway_id"] = ""
        df["castaway"] = "UNKNOWN"
        return df

    # Merge on (version_season, episode, speaker_label)
    df = df.merge(
        labels,
        on=["version_season", "episode", "speaker_label"],
        how="left",
    )

    # Fill missing labels with defaults
    df["castaway"] = df["castaway"].fillna("UNKNOWN")
    df["castaway_id"] = df["castaway_id"].fillna("")

    # Log labeling statistics
    total_segments = len(df)
    unknown_segments = (df["castaway"] == "UNKNOWN").sum()
    labeled_segments = total_segments - unknown_segments

    if total_segments > 0:
        labeled_pct = (labeled_segments / total_segments) * 100
        logger.info(
            f"Applied castaway labels: {labeled_segments}/{total_segments} segments "
            f"({labeled_pct:.1f}%) labeled, {unknown_segments} UNKNOWN"
        )

    return df
