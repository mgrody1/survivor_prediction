#!/usr/bin/env python3
"""
Survivor speaker diarization pipeline.

This script can be run:
1. Manually: python scripts/diarization_pipeline.py [options]
2. By Airflow: Called from survivor_diarization_dag.py

Examples:
  # Process all episodes
  python scripts/diarization_pipeline.py

  # Process only Episode 1 of all seasons
  python scripts/diarization_pipeline.py --episode 1

  # Process all episodes of Season 1
  python scripts/diarization_pipeline.py --season 1

  # Process specific episode range (e.g., episodes 5-10 in order)
  python scripts/diarization_pipeline.py --range 5 10

  # Process specific season and episodes
  python scripts/diarization_pipeline.py --season 1 --episodes 1 2 3

Processes episodes and saves to both parquet (with text) and database (metadata only).
"""

import argparse
import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
if REPO_ROOT not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gamebot_core.db_utils import (  # noqa: E402
    connect_to_db,
    register_ingestion_run,
    finalize_ingestion_run,
)
from gamebot_core.log_utils import setup_logging  # noqa: E402
from gamebot_core.media_diarization import (  # noqa: E402
    list_all_episode_videos,
    process_single_episode,
    build_speech_features_from_parquet,
    extract_episode_id,
    parse_episode_numbers,
)
from gamebot_core.media_diarization.config import ENABLE_DIARIZATION  # noqa: E402

import logging  # noqa: E402

logger = logging.getLogger(__name__)


def filter_episodes(
    episodes: list[str],
    season: int | None = None,
    episode: int | None = None,
    episodes_list: list[int] | None = None,
) -> list[str]:
    """
    Filter episode list by season and/or episode number(s).

    Args:
        episodes: List of video file paths
        season: Filter to specific season number (e.g., 1 for Season 1)
        episode: Filter to specific episode number across all seasons
        episodes_list: Filter to specific episode numbers within a season

    Returns:
        Filtered list of episode paths
    """
    filtered = []

    for ep_path in episodes:
        try:
            ep_id = extract_episode_id(Path(ep_path))
            season_num, episode_num = parse_episode_numbers(ep_id)

            # Apply filters
            if season is not None and season_num != season:
                continue
            if episode is not None and episode_num != episode:
                continue
            if episodes_list is not None and episode_num not in episodes_list:
                continue

            filtered.append(ep_path)
        except ValueError as e:
            logger.warning(f"Skipping {ep_path}: {e}")
            continue

    return filtered


def main():
    """Run diarization pipeline."""
    parser = argparse.ArgumentParser(
        description="Survivor diarization pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process all episodes
  %(prog)s

  # Process only Episode 1 of all seasons (for initial manual labeling)
  %(prog)s --episode 1

  # Process all episodes of Season 1
  %(prog)s --season 1

  # Process episodes 1-3 of Season 1
  %(prog)s --season 1 --episodes 1 2 3

  # Process episodes 5-10 in the sorted file list
  %(prog)s --range 5 10

  # Build NLP features from existing parquet files
  %(prog)s --features-only
        """,
    )
    parser.add_argument(
        "--features-only",
        action="store_true",
        help="Only build NLP features from existing parquet",
    )
    parser.add_argument(
        "--season",
        type=int,
        metavar="NUM",
        help="Process only episodes from specific season (e.g., 1 for Season 1)",
    )
    parser.add_argument(
        "--episode",
        type=int,
        metavar="NUM",
        help="Process only specific episode number across all seasons (e.g., 1 for all Episode 1s)",
    )
    parser.add_argument(
        "--episodes",
        nargs="+",
        type=int,
        metavar="NUM",
        help="Process specific episode numbers (use with --season). Example: --episodes 1 2 3",
    )
    parser.add_argument(
        "--range",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        help="Process episode range from sorted file list (1-indexed). Example: --range 5 10",
    )
    args = parser.parse_args()

    setup_logging()

    # Validation
    if args.episodes and not args.season:
        parser.error("--episodes requires --season to be specified")

    if not ENABLE_DIARIZATION:
        logger.error("ENABLE_DIARIZATION=false. Set to true in .env")
        sys.exit(1)

    conn = connect_to_db()
    if not conn:
        logger.error("Failed to connect to database")
        sys.exit(1)

    # Build features only
    if args.features_only:
        logger.info("Building NLP features from parquet files")
        run_id = register_ingestion_run(
            conn, "survivor_speech_features", "Building features"
        )
        try:
            rows = build_speech_features_from_parquet(conn, run_id)
            finalize_ingestion_run(conn, run_id, "success", rows)
            logger.info(f"✅ {rows} feature records saved")
        except Exception as e:
            finalize_ingestion_run(conn, run_id, "failure", notes=str(e))
            raise
        return

    # Diarization
    all_episodes = list_all_episode_videos()
    logger.info(f"Found {len(all_episodes)} total episodes")

    # Apply filters
    episodes = all_episodes
    filter_description = "all episodes"

    if args.season or args.episode or args.episodes:
        episodes = filter_episodes(
            episodes,
            season=args.season,
            episode=args.episode,
            episodes_list=args.episodes,
        )
        filter_parts = []
        if args.season:
            filter_parts.append(f"Season {args.season}")
        if args.episode:
            filter_parts.append(f"Episode {args.episode}")
        if args.episodes:
            filter_parts.append(f"Episodes {','.join(map(str, args.episodes))}")
        filter_description = " ".join(filter_parts)
        logger.info(f"Filtered to {len(episodes)} episodes: {filter_description}")

    # Apply range filter (after season/episode filters)
    if args.range:
        start, end = args.range
        episodes = episodes[start - 1 : end]
        filter_description += f" (range {start}-{end})"
        logger.info(
            f"Further filtered to range {start}-{end}: {len(episodes)} episodes"
        )

    if not episodes:
        logger.warning("No episodes match the specified filters")
        return

    run_id = register_ingestion_run(
        conn,
        environment="survivor_diarization",
        git_branch=None,
        git_commit=None,
        source_url=f"local_media_{filter_description}",
    )

    total_segments = 0
    for i, video_path in enumerate(episodes, 1):
        logger.info(f"[{i}/{len(episodes)}] {Path(video_path).name}")
        rows, parquet = process_single_episode(video_path, conn, run_id)
        total_segments += rows
        logger.info(f"  ✅ {rows} segments -> {Path(parquet).name}")

    finalize_ingestion_run(conn, run_id, "success", total_segments)
    logger.info(
        f"\n✅ Complete: {len(episodes)} episodes ({filter_description}), {total_segments} segments"
    )
    logger.info("Next: python scripts/diarization_pipeline.py --features-only")


if __name__ == "__main__":
    main()
