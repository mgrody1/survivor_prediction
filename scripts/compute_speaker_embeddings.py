#!/usr/bin/env python3
"""
Compute speaker embeddings for diarized episodes.

This script extracts cluster-level speaker embeddings from diarized audio segments
and saves them to parquet files for downstream label propagation.

Usage:
    # Compute embeddings for a single episode
    python scripts/compute_speaker_embeddings.py --season US01 --episode 1

    # Compute embeddings for all episodes in a season
    python scripts/compute_speaker_embeddings.py --season US01 --all

    # Compute embeddings for a range of episodes
    python scripts/compute_speaker_embeddings.py --season US01 --range 1 5

Requirements:
    - Diarization must be run first (creates parquet files)
    - Audio files must exist in SURVIVOR_AUDIO_OUT_DIR
    - HF_TOKEN must be set for pyannote embedding model
"""

import argparse
import logging
import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
if REPO_ROOT not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gamebot_core.log_utils import setup_logging  # noqa: E402
from gamebot_core.media_diarization import (  # noqa: E402
    compute_cluster_embeddings_for_episode,
    save_cluster_embeddings,
    ENABLE_DIARIZATION,
    DIARIZED_PARQUET_DIR,
)

logger = logging.getLogger(__name__)


def find_all_diarized_episodes(version_season: str) -> list[int]:
    """Find all episode numbers that have diarized parquet files."""
    pattern = f"{version_season}_E*_diarized.parquet"
    files = list(DIARIZED_PARQUET_DIR.glob(pattern))

    episodes = []
    for f in files:
        # Extract episode number from filename like "US01_E01_diarized.parquet"
        try:
            episode_str = f.stem.split("_E")[1].split("_")[0]
            episodes.append(int(episode_str))
        except (IndexError, ValueError) as e:
            logger.warning(f"Could not parse episode number from {f.name}: {e}")
            continue

    return sorted(episodes)


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description="Compute speaker embeddings from diarized episodes"
    )
    parser.add_argument(
        "--season",
        required=True,
        help="Season identifier (e.g., US01, AU02)",
    )
    parser.add_argument(
        "--episode",
        type=int,
        help="Episode number to process",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all diarized episodes in the season",
    )
    parser.add_argument(
        "--range",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        help="Process episodes in range (inclusive)",
    )

    args = parser.parse_args()
    setup_logging()

    if not ENABLE_DIARIZATION:
        logger.error(
            "ENABLE_DIARIZATION=false. Set to true in .env to use this script."
        )
        sys.exit(1)

    # Determine which episodes to process
    if args.all:
        episodes = find_all_diarized_episodes(args.season)
        if not episodes:
            logger.error(
                f"No diarized episodes found for {args.season}. "
                "Run diarization_pipeline.py first."
            )
            sys.exit(1)
        logger.info(f"Found {len(episodes)} diarized episodes: {episodes}")
    elif args.range:
        start, end = args.range
        episodes = list(range(start, end + 1))
        logger.info(f"Processing episodes {start}-{end}")
    elif args.episode:
        episodes = [args.episode]
        logger.info(f"Processing episode {args.episode}")
    else:
        logger.error("Must specify --episode, --all, or --range. Use --help for usage.")
        sys.exit(1)

    # Process each episode
    total_clusters = 0
    for i, episode in enumerate(episodes, 1):
        logger.info(
            f"[{i}/{len(episodes)}] Computing embeddings for "
            f"{args.season} E{episode:02d}..."
        )

        try:
            # Compute embeddings
            emb_df = compute_cluster_embeddings_for_episode(args.season, episode)

            # Save to parquet
            output_path = save_cluster_embeddings(emb_df, args.season, episode)

            total_clusters += len(emb_df)
            logger.info(f"  ✅ {len(emb_df)} speaker clusters → {output_path.name}")

        except FileNotFoundError as e:
            logger.error(f"  ❌ {e}")
            continue
        except Exception as e:
            logger.error(f"  ❌ Failed to process episode {episode}: {e}")
            continue

    logger.info(
        f"\n✅ Complete: {len(episodes)} episodes, {total_clusters} speaker clusters"
    )
    logger.info(
        "Next: python scripts/suggest_castaway_labels.py --season " + args.season
    )


if __name__ == "__main__":
    main()
