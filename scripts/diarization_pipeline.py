#!/usr/bin/env python3
"""
Survivor speaker diarization pipeline.

This script can be run:
1. Manually: python scripts/diarization_pipeline.py
2. By Airflow: Called from survivor_diarization_dag.py

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
)
from gamebot_core.media_diarization.config import ENABLE_DIARIZATION  # noqa: E402

import logging  # noqa: E402

logger = logging.getLogger(__name__)


def main():
    """Run diarization pipeline."""
    parser = argparse.ArgumentParser(description="Survivor diarization pipeline")
    parser.add_argument(
        "--features-only",
        action="store_true",
        help="Only build NLP features from existing parquet",
    )
    parser.add_argument(
        "--range",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        help="Process episode range (1-indexed, for splitting work)",
    )
    args = parser.parse_args()

    setup_logging()

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
    episodes = list_all_episode_videos()
    logger.info(f"Found {len(episodes)} episodes")

    # Filter range if specified
    if args.range:
        start, end = args.range
        episodes = episodes[start - 1 : end]
        logger.info(f"Processing episodes {start}-{end}: {len(episodes)} episodes")

    run_id = register_ingestion_run(
        conn,
        environment="survivor_diarization",
        git_branch=None,
        git_commit=None,
        source_url=f"local_media_{len(episodes)}_episodes",
    )

    total_segments = 0
    for i, video_path in enumerate(episodes, 1):
        logger.info(f"[{i}/{len(episodes)}] {Path(video_path).name}")
        rows, parquet = process_single_episode(video_path, conn, run_id)
        total_segments += rows
        logger.info(f"  ✅ {rows} segments -> {Path(parquet).name}")

    finalize_ingestion_run(conn, run_id, "success", total_segments)
    logger.info(f"\n✅ Complete: {len(episodes)} episodes, {total_segments} segments")
    logger.info("Next: python scripts/diarization_pipeline.py --features-only")


if __name__ == "__main__":
    main()
