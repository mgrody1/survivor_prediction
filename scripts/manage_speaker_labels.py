#!/usr/bin/env python3
"""
Fully automated speaker labeling for diarized episodes.

CRITICAL REQUIREMENT:
The ONLY manual labor is labeling Episode 1 clusters for each season.
Everything else runs fully automatically with no human review/approval.

Architecture - Three Levels of Embeddings (ALL PRIVATE, NEVER IN POSTGRES):

1. Cluster-level embeddings: per (version_season, episode, speaker_label)
   - File: US01_cluster_embeddings.parquet
   - Raw building blocks from pyannote speaker clusters
   - Used for: Building higher-level aggregations

2. Season-level centroids: per (version_season, castaway_id)
   - File: US01_season_centroids.parquet
   - Aggregated from Episode 1 manual + high-confidence auto-labels
   - Used for: Auto-labeling new episodes (identity propagation)
   - Accumulates: Episode N uses E01 through E(N-1) labeled clusters

3. Per-episode per-castaway embeddings: per (version_season, episode, castaway_id)
   - File: US01_episode_castaway_embeddings.parquet
   - Average of cluster embeddings for each castaway within each episode
   - Used for: Deriving NUMERIC features for Postgres (NOT storing raw embeddings!)

What Goes to Postgres:
✅ Numeric features DERIVED FROM embeddings (distances, scores, acoustic metrics)
❌ Raw 512-dimensional embedding vectors (stay in parquet only)

File Naming Convention:
- Diarized parquet: US01_S01_E01_diarized.parquet (version_season in filename)
- Embeddings: US01_cluster_embeddings.parquet (version_season prefix)
- Code supports variable episode counts per season (no hardcoded limits)

Usage:
  # Full workflow for entire season (label E01 once, auto-process E02-EN)
  python scripts/manage_speaker_labels.py full-workflow --season 1

  # Incremental mode for new episode (e.g., E14 airs later)
  python scripts/manage_speaker_labels.py full-workflow --season 1 --episode 14

  # Individual steps (advanced usage):
  python scripts/manage_speaker_labels.py apply-labels --season 1
  python scripts/manage_speaker_labels.py compute-embeddings --season 1
  python scripts/manage_speaker_labels.py auto-label --season 1
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
if REPO_ROOT not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gamebot_core.log_utils import setup_logging  # noqa: E402
from gamebot_core.media_diarization import (  # noqa: E402
    DIARIZED_PARQUET_DIR,
    EMBEDDINGS_DIR,
    MANUAL_LABELS_PATH,
    AUTO_LABELS_PATH,
    VERSION_COUNTRY,
    apply_speaker_labels,
    compute_cluster_embeddings_for_episode,
    save_cluster_embeddings,
)

import logging  # noqa: E402

logger = logging.getLogger(__name__)


def apply_labels_to_parquet_files(
    season: int | None = None, episode: int | None = None
):
    """
    Apply manual Episode 1 labels to Episode 1 parquet file.

    This ONLY applies manual labels from CSV to Episode 1.
    Episodes 2+ are labeled via auto_label_season() function.

    Args:
        season: Filter to specific season (e.g., 1 for Season 1)
        episode: Should always be 1 (manual labels only for Episode 1)
    """
    if not DIARIZED_PARQUET_DIR.exists():
        logger.error(f"Diarized parquet directory not found: {DIARIZED_PARQUET_DIR}")
        return 0

    # Find Episode 1 parquet files
    parquet_files = list(DIARIZED_PARQUET_DIR.glob("*.parquet"))

    # Filter by season if specified
    if season is not None:
        season_str = f"_S{season:02d}_"
        parquet_files = [f for f in parquet_files if season_str in f.name]

    # Filter to Episode 1 only (manual labels)
    if episode is None:
        episode = 1  # Default to Episode 1

    episode_str = f"E{episode:02d}_"
    parquet_files = [f for f in parquet_files if episode_str in f.name]

    if not parquet_files:
        logger.warning(f"No Episode {episode} parquet files found for Season {season}")
        return 0

    logger.info(
        f"Applying manual labels to {len(parquet_files)} Episode {episode} parquet file(s)"
    )

    # Apply labels to each file
    updated = 0
    for i, parquet_path in enumerate(sorted(parquet_files), 1):
        logger.info(f"[{i}/{len(parquet_files)}] Processing {parquet_path.name}")

        try:
            # Load existing diarized data
            df = pd.read_parquet(parquet_path)

            # Apply manual labels (from manual CSV)
            if "castaway" in df.columns:
                df = df.drop(columns=["castaway"])
            if "castaway_id" in df.columns:
                df = df.drop(columns=["castaway_id"])

            df_labeled = apply_speaker_labels(df)

            # Save back to parquet
            df_labeled.to_parquet(parquet_path, index=False)

            labeled_count = (df_labeled["castaway"] != "UNKNOWN").sum()
            total_count = len(df_labeled)
            logger.info(
                f"  ✅ Updated: {labeled_count}/{total_count} segments labeled "
                f"({labeled_count / total_count * 100:.1f}%)"
            )
            updated += 1

        except Exception as e:
            logger.error(f"  ❌ Failed to process {parquet_path.name}: {e}")
            continue

    logger.info(f"\n✅ Complete: Updated {updated}/{len(parquet_files)} parquet files")
    return updated


def compute_embeddings_for_season(season: int, episode: int | None = None):
    """
    Compute voice embeddings at THREE levels for a season.

    Creates:
    1. Cluster-level embeddings: Per (version_season, episode, speaker_label)
       - Stored in parquet, used for auto-labeling and building higher-level embeddings
       - Private, local-only (NAS)

    2. Season-level centroids: Per (version_season, castaway_id)
       - Aggregated from ALL labeled cluster embeddings across all episodes
       - Used for auto-labeling new episodes (identity propagation)
       - Accumulated from Episode 1 manual + high-confidence auto-labels

    3. Per-episode per-castaway embeddings: Per (version_season, episode, castaway_id)
       - Aggregated from cluster embeddings within each episode for each castaway
       - Ready for Postgres storage and feature engineering
       - Clean analytical units for downstream analytics

    Args:
        season: Season number (e.g., 1 for Season 1)
        episode: Optional episode filter (for incremental updates)
    """
    logger.info(f"Computing embeddings for Season {season}")

    # Find parquet files for this season
    season_str = f"_S{season:02d}_"
    parquet_files = [
        f for f in DIARIZED_PARQUET_DIR.glob("*.parquet") if season_str in f.name
    ]

    if episode is not None:
        episode_str = f"E{episode:02d}_"
        parquet_files = [f for f in parquet_files if episode_str in f.name]

    if not parquet_files:
        logger.warning(f"No diarized parquet files found for Season {season}")
        return

    logger.info(f"Found {len(parquet_files)} episodes to process")

    # Compute cluster-level embeddings (building blocks)
    episode_embeddings = []
    for i, parquet_path in enumerate(sorted(parquet_files), 1):
        logger.info(f"[{i}/{len(parquet_files)}] {parquet_path.name}")

        try:
            # Extract version_season and episode from filename
            # Expected format: US01_S01_E01_diarized.parquet
            parts = parquet_path.stem.split("_")
            version_season = parts[0]  # e.g., "US01"
            ep_num = int(parts[2][1:])  # e.g., "E01" -> 1

            # Compute cluster-level embeddings for this episode
            emb_df = compute_cluster_embeddings_for_episode(
                version_season=version_season,
                episode=ep_num,
                parquet_path=parquet_path,
            )

            if emb_df is not None and len(emb_df) > 0:
                episode_embeddings.append(emb_df)
                logger.info(f"  ✅ Computed {len(emb_df)} cluster-level embeddings")
            else:
                logger.warning("  ⚠️  No embeddings computed")

        except Exception as e:
            logger.error(f"  ❌ Failed: {e}")
            continue

    if not episode_embeddings:
        logger.warning("No embeddings computed for any episode")
        return

    # Combine all cluster-level embeddings
    all_cluster_embeddings = pd.concat(episode_embeddings, ignore_index=True)

    # Save cluster-level embeddings (raw building blocks)
    cluster_level_path = (
        EMBEDDINGS_DIR / f"{VERSION_COUNTRY}{season:02d}_cluster_embeddings.parquet"
    )
    save_cluster_embeddings(all_cluster_embeddings, cluster_level_path)
    logger.info(f"✅ Saved cluster-level embeddings: {cluster_level_path.name}")
    logger.info(f"   Total clusters: {len(all_cluster_embeddings)}")

    # Filter to labeled clusters only
    labeled_only = all_cluster_embeddings[
        all_cluster_embeddings["castaway"] != "UNKNOWN"
    ].copy()

    if len(labeled_only) == 0:
        logger.warning(
            "No labeled embeddings - cannot create season centroids or episode-castaway embeddings"
        )
        return

    # =========================================================================
    # LEVEL 2: Season-level centroids (for auto-labeling)
    # =========================================================================
    logger.info(
        f"\nComputing season-level centroids for {labeled_only['castaway'].nunique()} castaways"
    )

    season_centroids = []
    for castaway in labeled_only["castaway"].unique():
        castaway_clusters = labeled_only[labeled_only["castaway"] == castaway]

        # Average ALL cluster embeddings for this castaway across ALL episodes
        mean_embedding = np.mean(
            [emb for emb in castaway_clusters["embedding"]], axis=0
        )

        season_centroids.append(
            {
                "version_season": f"{VERSION_COUNTRY}{season:02d}",
                "castaway_id": castaway_clusters.iloc[0]["castaway_id"],
                "castaway": castaway,
                "embedding": mean_embedding,
                "n_episodes": castaway_clusters["episode"].nunique(),
                "n_clusters": len(castaway_clusters),
            }
        )

    season_centroids_df = pd.DataFrame(season_centroids)
    season_level_path = (
        EMBEDDINGS_DIR / f"{VERSION_COUNTRY}{season:02d}_season_centroids.parquet"
    )
    season_centroids_df.to_parquet(season_level_path, index=False)

    logger.info(
        f"✅ Saved season-level centroids: {season_level_path.name} "
        f"({len(season_centroids_df)} castaways)"
    )

    # =========================================================================
    # LEVEL 3: Per-episode per-castaway embeddings (for analytics/DB)
    # =========================================================================
    logger.info("\nComputing per-episode per-castaway embeddings")

    episode_castaway_embeddings = []

    # Group by (episode, castaway_id)
    for (ep_num, castaway_id), group in labeled_only.groupby(
        ["episode", "castaway_id"]
    ):
        # Average all cluster embeddings for this castaway in this episode
        episode_mean_embedding = np.mean([emb for emb in group["embedding"]], axis=0)

        episode_castaway_embeddings.append(
            {
                "version_season": f"{VERSION_COUNTRY}{season:02d}",
                "season": season,
                "episode": ep_num,
                "castaway_id": castaway_id,
                "castaway": group.iloc[0]["castaway"],
                "embedding": episode_mean_embedding,
                "n_clusters": len(group),  # How many clusters merged into this
                "total_segments": group["n_segments"].sum()
                if "n_segments" in group.columns
                else None,
            }
        )

    episode_castaway_df = pd.DataFrame(episode_castaway_embeddings)
    episode_castaway_path = (
        EMBEDDINGS_DIR
        / f"{VERSION_COUNTRY}{season:02d}_episode_castaway_embeddings.parquet"
    )
    episode_castaway_df.to_parquet(episode_castaway_path, index=False)

    logger.info(
        f"✅ Saved per-episode per-castaway embeddings: {episode_castaway_path.name}"
    )
    logger.info(
        f"   {len(episode_castaway_df)} episode-castaway pairs across "
        f"{episode_castaway_df['episode'].nunique()} episodes"
    )
    logger.info("   Ready for Postgres storage and feature engineering!")


def suggest_labels_for_season(season: int, threshold: float = 0.80):
    """
    Auto-suggest labels for unlabeled clusters using growing episode embeddings.

    NOTE: This function is DEPRECATED in favor of auto_label_season() which
    applies labels automatically. This is kept for debugging/review purposes only.

    For each episode, compares that episode's embeddings to ALL PRIOR episodes'
    embeddings (not just Episode 1). This creates a growing reference library
    that improves with each processed episode.

    Example:
    - Episode 2: Compare E02 clusters to E01 labeled embeddings
    - Episode 3: Compare E03 clusters to E01+E02 labeled embeddings
    - Episode 13: Compare E13 clusters to E01-E12 labeled embeddings

    Args:
        season: Season number
        threshold: Minimum cosine similarity for auto-suggestions
    """
    logger.info(f"Auto-suggesting labels for Season {season} (threshold={threshold})")

    # Load cluster-level embeddings
    cluster_path = (
        EMBEDDINGS_DIR / f"{VERSION_COUNTRY}{season:02d}_cluster_embeddings.parquet"
    )
    if not cluster_path.exists():
        logger.error(
            f"Cluster embeddings not found: {cluster_path.name}. "
            "Run compute-embeddings first!"
        )
        return

    all_embeddings = pd.read_parquet(cluster_path)

    # Get unique episodes, sorted
    episodes = sorted(all_embeddings["episode"].unique())

    if len(episodes) < 2:
        logger.warning("Need at least 2 episodes to auto-suggest labels")
        return

    logger.info(f"Found {len(episodes)} episodes: {episodes}")

    all_suggestions = []

    # Process episodes sequentially (E02, E03, ..., E13)
    for target_episode in episodes[1:]:  # Skip first episode (manually labeled)
        logger.info(f"\nProcessing Episode {target_episode}...")

        # Get reference embeddings: ALL episodes BEFORE this one
        prior_episodes = [e for e in episodes if e < target_episode]
        reference_embeddings = all_embeddings[
            all_embeddings["episode"].isin(prior_episodes)
        ]

        # Filter to labeled references only
        labeled_refs = reference_embeddings[
            reference_embeddings["castaway"] != "UNKNOWN"
        ].copy()

        if len(labeled_refs) == 0:
            logger.warning(
                f"  No labeled reference embeddings for Episode {target_episode}"
            )
            continue

        logger.info(
            f"  Reference library: {len(labeled_refs)} labeled clusters from "
            f"Episodes {prior_episodes} ({labeled_refs['castaway'].nunique()} unique castaways)"
        )

        # Get target (unlabeled) embeddings from this episode
        target_embeddings = all_embeddings[
            (all_embeddings["episode"] == target_episode)
            & (all_embeddings["castaway"] == "UNKNOWN")
        ]

        if len(target_embeddings) == 0:
            logger.info(f"  No unlabeled clusters in Episode {target_episode}")
            continue

        logger.info(f"  Unlabeled clusters: {len(target_embeddings)}")

        # For each unlabeled cluster, find best matching castaway
        for _, target_row in target_embeddings.iterrows():
            target_emb = target_row["embedding"]
            best_similarity = -1
            best_castaway = None
            best_castaway_id = None

            # Compare to each labeled castaway in reference library
            for castaway in labeled_refs["castaway"].unique():
                castaway_refs = labeled_refs[labeled_refs["castaway"] == castaway]

                # Compute similarity to each reference cluster for this castaway
                similarities = []
                for _, ref_row in castaway_refs.iterrows():
                    ref_emb = ref_row["embedding"]
                    # Cosine similarity
                    sim = np.dot(target_emb, ref_emb) / (
                        np.linalg.norm(target_emb) * np.linalg.norm(ref_emb)
                    )
                    similarities.append(sim)

                # Use max similarity for this castaway
                max_sim = max(similarities)

                if max_sim > best_similarity:
                    best_similarity = max_sim
                    best_castaway = castaway
                    # Try to get castaway_id from reference
                    best_castaway_id = castaway_refs.iloc[0].get("castaway_id", "")

            # If similarity exceeds threshold, suggest this label
            if best_similarity >= threshold:
                all_suggestions.append(
                    {
                        "version_season": target_row["version_season"],
                        "episode": target_episode,
                        "speaker_label": target_row["speaker_label"],
                        "castaway_id": best_castaway_id,
                        "castaway": best_castaway,
                        "confidence": "auto",
                        "notes": f"Similarity {best_similarity:.3f} (prior episodes: {prior_episodes})",
                    }
                )
                logger.info(
                    f"    {target_row['speaker_label']} → {best_castaway} "
                    f"(similarity: {best_similarity:.3f})"
                )

    if not all_suggestions:
        logger.warning("No auto-suggestions generated (all below threshold)")
        return

    # Save suggestions
    suggestions_df = pd.DataFrame(all_suggestions)
    suggestions_path = (
        EMBEDDINGS_DIR / f"{VERSION_COUNTRY}{season:02d}_auto_suggestions.csv"
    )
    suggestions_df.to_csv(suggestions_path, index=False)

    logger.info(
        f"\n✅ Generated {len(all_suggestions)} suggestions across "
        f"{suggestions_df['episode'].nunique()} episodes"
    )
    logger.info(f"   Saved: {suggestions_path}")


def auto_label_season(
    season: int,
    episode: int | None = None,
    threshold: float = 0.80,
    refine_centroids: bool = True,
):
    """
    Automatically label ALL unlabeled episodes using Episode 1 centroids.

    FULLY AUTOMATED - No human review required!

    Process:
    1. Load Episode 1 manual labels → compute centroids
    2. For each episode 2-N:
       - Compare unlabeled clusters to centroids
       - Auto-apply labels if similarity >= threshold
       - Update parquet file with castaway/castaway_id
       - Save to auto_labels CSV
    3. Optionally refine centroids using high-confidence auto-labels (>0.90)

    Args:
        season: Season number
        episode: If specified, only process this episode (incremental mode)
        threshold: Minimum cosine similarity for auto-labeling (default 0.80)
        refine_centroids: Use high-confidence auto-labels to improve centroids
    """
    logger.info(f"\n{'=' * 80}")
    logger.info(
        f"AUTO-LABELING Season {season} (threshold={threshold}, refine={refine_centroids})"
    )
    logger.info(f"{'=' * 80}\n")

    # Load cluster-level embeddings
    cluster_emb_path = (
        EMBEDDINGS_DIR / f"{VERSION_COUNTRY}{season:02d}_cluster_embeddings.parquet"
    )
    if not cluster_emb_path.exists():
        logger.error(
            f"Cluster embeddings not found: {cluster_emb_path.name}. "
            "Run compute-embeddings first!"
        )
        return

    all_embeddings = pd.read_parquet(cluster_emb_path)

    # Get episodes to process
    all_episodes = sorted(all_embeddings["episode"].unique())

    if episode is not None:
        # Incremental mode: process only specified episode
        if episode not in all_episodes:
            logger.error(f"Episode {episode} not found in embeddings")
            return
        episodes_to_label = [episode]
        logger.info(f"INCREMENTAL MODE: Processing Episode {episode} only")
    else:
        # Full mode: process all episodes except Episode 1 (manually labeled)
        episodes_to_label = [e for e in all_episodes if e > 1]
        logger.info(f"FULL MODE: Processing Episodes {episodes_to_label}")

    if len(episodes_to_label) == 0:
        logger.warning("No episodes to auto-label")
        return

    # Build initial centroids from Episode 1 manual labels
    episode_1_embeddings = all_embeddings[all_embeddings["episode"] == 1]
    labeled_e1 = episode_1_embeddings[episode_1_embeddings["castaway"] != "UNKNOWN"]

    if len(labeled_e1) == 0:
        logger.error("No manual labels found for Episode 1. Label Episode 1 first!")
        return

    logger.info(f"Building centroids from {len(labeled_e1)} Episode 1 labeled clusters")
    logger.info(f"Castaways: {sorted(labeled_e1['castaway'].unique())}")

    # Compute initial centroids (average embedding per castaway from E01)
    centroids = {}
    castaway_ids = {}
    for castaway in labeled_e1["castaway"].unique():
        castaway_clusters = labeled_e1[labeled_e1["castaway"] == castaway]
        # Average all embeddings for this castaway
        centroid = np.mean([emb for emb in castaway_clusters["embedding"]], axis=0)
        centroids[castaway] = centroid
        # Store castaway_id
        castaway_ids[castaway] = castaway_clusters.iloc[0]["castaway_id"]

    logger.info(f"Initial centroids: {len(centroids)} castaways\n")

    # Load existing auto-labels (for incremental updates)
    if AUTO_LABELS_PATH.exists():
        auto_labels_df = pd.read_csv(AUTO_LABELS_PATH)
        logger.info(f"Loaded {len(auto_labels_df)} existing auto-labels")
    else:
        auto_labels_df = pd.DataFrame(
            columns=[
                "version_season",
                "episode",
                "speaker_label",
                "castaway_id",
                "castaway",
                "similarity",
                "notes",
            ]
        )

    all_new_labels = []

    # Process each episode sequentially
    for target_ep in episodes_to_label:
        logger.info(f"\n{'─' * 60}")
        logger.info(f"Episode {target_ep}")
        logger.info(f"{'─' * 60}")

        # Get unlabeled clusters for this episode
        episode_embeddings = all_embeddings[
            (all_embeddings["episode"] == target_ep)
            & (all_embeddings["castaway"] == "UNKNOWN")
        ]

        if len(episode_embeddings) == 0:
            logger.info(f"  No unlabeled clusters in Episode {target_ep}")
            continue

        logger.info(f"  Unlabeled clusters: {len(episode_embeddings)}")

        # Auto-label each unlabeled cluster
        episode_labels = []
        for _, cluster_row in episode_embeddings.iterrows():
            cluster_emb = cluster_row["embedding"]
            best_similarity = -1
            best_castaway = None

            # Compare to each castaway centroid
            for castaway, centroid in centroids.items():
                # Cosine similarity
                similarity = np.dot(cluster_emb, centroid) / (
                    np.linalg.norm(cluster_emb) * np.linalg.norm(centroid)
                )

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_castaway = castaway

            # Auto-apply if above threshold
            if best_similarity >= threshold:
                episode_labels.append(
                    {
                        "version_season": cluster_row["version_season"],
                        "episode": target_ep,
                        "speaker_label": cluster_row["speaker_label"],
                        "castaway_id": castaway_ids[best_castaway],
                        "castaway": best_castaway,
                        "similarity": best_similarity,
                        "notes": f"Auto-labeled (centroid similarity {best_similarity:.3f})",
                    }
                )
                logger.info(
                    f"    {cluster_row['speaker_label']} → {best_castaway} "
                    f"(similarity: {best_similarity:.3f})"
                )

        if episode_labels:
            all_new_labels.extend(episode_labels)
            logger.info(f"  ✅ Auto-labeled {len(episode_labels)} clusters")

            # Update parquet file with new labels
            parquet_path = (
                DIARIZED_PARQUET_DIR
                / f"{VERSION_COUNTRY}{season:02d}_S{season:02d}_E{target_ep:02d}_diarized.parquet"
            )
            if parquet_path.exists():
                df = pd.read_parquet(parquet_path)

                # Apply auto-labels to this episode's parquet
                labels_dict = {row["speaker_label"]: row for row in episode_labels}
                for idx, row in df.iterrows():
                    if row["speaker_label"] in labels_dict:
                        df.at[idx, "castaway"] = labels_dict[row["speaker_label"]][
                            "castaway"
                        ]
                        df.at[idx, "castaway_id"] = labels_dict[row["speaker_label"]][
                            "castaway_id"
                        ]

                df.to_parquet(parquet_path, index=False)
                logger.info(f"  ✅ Updated {parquet_path.name}")
        else:
            logger.info("  ⚠️  No clusters above threshold")

        # Optionally refine centroids with high-confidence auto-labels
        if refine_centroids and episode_labels:
            high_conf_labels = [
                label for label in episode_labels if label["similarity"] >= 0.90
            ]
            if high_conf_labels:
                logger.info(
                    f"  🔄 Refining centroids with {len(high_conf_labels)} high-confidence labels"
                )

                # Update centroids by averaging with new high-confidence clusters
                for label in high_conf_labels:
                    castaway = label["castaway"]
                    cluster_emb = all_embeddings[
                        (all_embeddings["episode"] == target_ep)
                        & (all_embeddings["speaker_label"] == label["speaker_label"])
                    ]["embedding"].iloc[0]

                    # Weighted average (give more weight to existing centroid)
                    centroids[castaway] = 0.7 * centroids[castaway] + 0.3 * cluster_emb
                    # Re-normalize
                    centroids[castaway] = centroids[castaway] / np.linalg.norm(
                        centroids[castaway]
                    )

    # Save all new auto-labels to CSV
    if all_new_labels:
        new_labels_df = pd.DataFrame(all_new_labels)

        # Remove old labels for these episodes (if incremental update)
        version_season = f"{VERSION_COUNTRY}{season:02d}"
        auto_labels_df = auto_labels_df[
            ~(
                (auto_labels_df["version_season"] == version_season)
                & (auto_labels_df["episode"].isin(episodes_to_label))
            )
        ]

        # Append new labels
        auto_labels_df = pd.concat([auto_labels_df, new_labels_df], ignore_index=True)
        auto_labels_df.to_csv(AUTO_LABELS_PATH, index=False)

        logger.info(
            f"\n✅ Saved {len(all_new_labels)} auto-labels to {AUTO_LABELS_PATH.name}"
        )
        logger.info(f"   Total auto-labels in file: {len(auto_labels_df)}")
    else:
        logger.warning("\n⚠️  No labels generated (all clusters below threshold)")

    logger.info(f"\n{'=' * 80}")
    logger.info(f"AUTO-LABELING COMPLETE for Season {season}")
    logger.info(f"{'=' * 80}\n")


def full_workflow(season: int, episode: int | None = None, threshold: float = 0.80):
    """
    FULLY AUTOMATED workflow: Label Episode 1 → Auto-label all other episodes.

    NO HUMAN REVIEW REQUIRED after Episode 1 labeling!

    Steps:
    1. Apply Episode 1 manual labels (from manual CSV)
    2. Compute embeddings for all episodes
    3. Auto-label Episodes 2-N using Episode 1 centroids
    4. Update all parquet files with castaway/castaway_id
    5. Save auto-labels to separate CSV

    Args:
        season: Season number
        episode: If specified, incremental mode (process only this episode)
        threshold: Similarity threshold for auto-labeling (default 0.80)
    """
    if episode is not None:
        logger.info(f"\n🚀 INCREMENTAL WORKFLOW: Season {season}, Episode {episode}")
    else:
        logger.info(f"\n🚀 FULL WORKFLOW: Season {season}")

    # Step 1: Apply Episode 1 manual labels
    logger.info("\n" + "=" * 80)
    logger.info("STEP 1: Apply Episode 1 Manual Labels")
    logger.info("=" * 80)
    apply_labels_to_parquet_files(season=season, episode=1)

    # Step 2: Compute embeddings for all episodes
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Compute Embeddings")
    logger.info("=" * 80)
    if episode is not None:
        # Incremental: only compute for new episode
        compute_embeddings_for_season(season=season, episode=episode)
    else:
        # Full: compute for all episodes
        compute_embeddings_for_season(season=season)

    # Step 3: Auto-label episodes
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Auto-Label Episodes")
    logger.info("=" * 80)
    auto_label_season(
        season=season, episode=episode, threshold=threshold, refine_centroids=True
    )

    logger.info("\n" + "=" * 80)
    logger.info("✅ WORKFLOW COMPLETE!")
    logger.info("=" * 80)
    logger.info("\nAll episodes labeled and ready for feature extraction.")
    logger.info(f"Manual labels (E01 only): {MANUAL_LABELS_PATH}")
    logger.info(f"Auto labels (E02+): {AUTO_LABELS_PATH}")
    logger.info(f"Labeled parquet files: {DIARIZED_PARQUET_DIR}")


def main():
    parser = argparse.ArgumentParser(
        description="Fully automated speaker labeling for diarized episodes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full workflow for entire season (label E01 manually first!)
  python scripts/manage_speaker_labels.py full-workflow --season 1

  # Incremental mode for new episode
  python scripts/manage_speaker_labels.py full-workflow --season 1 --episode 14

  # Individual steps (advanced usage):
  python scripts/manage_speaker_labels.py apply-labels --season 1
  python scripts/manage_speaker_labels.py compute-embeddings --season 1
  python scripts/manage_speaker_labels.py auto-label --season 1
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Apply Episode 1 manual labels
    apply_parser = subparsers.add_parser(
        "apply-labels",
        help="Apply Episode 1 manual labels to parquet file",
    )
    apply_parser.add_argument("--season", type=int, required=True, help="Season number")

    # Compute embeddings
    compute_parser = subparsers.add_parser(
        "compute-embeddings",
        help="Compute voice embeddings for all episodes",
    )
    compute_parser.add_argument(
        "--season", type=int, required=True, help="Season number"
    )
    compute_parser.add_argument(
        "--episode", type=int, help="Optional: compute only for this episode"
    )

    # Auto-label episodes
    auto_parser = subparsers.add_parser(
        "auto-label",
        help="Automatically label Episodes 2+ using Episode 1 centroids",
    )
    auto_parser.add_argument("--season", type=int, required=True, help="Season number")
    auto_parser.add_argument(
        "--episode",
        type=int,
        help="Optional: label only this episode (incremental mode)",
    )
    auto_parser.add_argument(
        "--threshold",
        type=float,
        default=0.80,
        help="Minimum similarity threshold (default: 0.80)",
    )
    auto_parser.add_argument(
        "--no-refine",
        action="store_true",
        help="Disable centroid refinement with high-confidence labels",
    )

    # Full automated workflow
    workflow_parser = subparsers.add_parser(
        "full-workflow",
        help="FULLY AUTOMATED: Label E01 manually, then run this once (no review needed!)",
    )
    workflow_parser.add_argument(
        "--season", type=int, required=True, help="Season number"
    )
    workflow_parser.add_argument(
        "--episode",
        type=int,
        help="Optional: process only this episode (incremental mode)",
    )
    workflow_parser.add_argument(
        "--threshold",
        type=float,
        default=0.80,
        help="Minimum similarity threshold (default: 0.80)",
    )

    args = parser.parse_args()
    setup_logging()

    if args.command == "apply-labels":
        apply_labels_to_parquet_files(season=args.season, episode=1)

    elif args.command == "compute-embeddings":
        compute_embeddings_for_season(season=args.season, episode=args.episode)

    elif args.command == "auto-label":
        auto_label_season(
            season=args.season,
            episode=args.episode,
            threshold=args.threshold,
            refine_centroids=not args.no_refine,
        )

    elif args.command == "full-workflow":
        full_workflow(
            season=args.season,
            episode=args.episode,
            threshold=args.threshold,
        )


if __name__ == "__main__":
    main()
