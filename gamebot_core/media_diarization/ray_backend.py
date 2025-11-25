"""Ray backend for distributed diarization processing.

This module provides optional Ray-based distributed processing. When USE_RAY
is false or Ray is not installed, falls back to local sequential processing.

The public API (run_diarization) is designed to be called from Airflow without
any Ray imports in the DAG file itself.
"""

import logging

from .config import RAY_ADDRESS, USE_RAY

logger = logging.getLogger(__name__)


def should_use_ray() -> bool:
    """
    Check if Ray distributed processing should be used.

    Returns:
        True if USE_RAY=true and Ray is installed, False otherwise
    """
    if not USE_RAY:
        return False

    try:
        import ray  # Lazy import to avoid DAG parse overhead  # noqa: F401

        return True
    except ImportError:
        logger.warning(
            "USE_RAY=true but ray is not installed. Install with: pip install ray"
        )
        return False


def run_diarization(
    episode_paths: list[str], conn, ingest_run_id: int
) -> tuple[list[int], list[str]]:
    """
    Run diarization on a list of episode video paths.

    If USE_RAY=true and Ray is available, distributes work across Ray cluster.
    Otherwise, runs locally in a simple loop.

    AMBIGUITY NOTE: Ray initialization happens inside this function, not at
    module import time. This keeps Airflow DAG parsing lightweight.

    AMBIGUITY NOTE: Local fallback is sequential, not multiprocessing. For
    CPU-based parallelism without Ray, users could enhance this with
    concurrent.futures.ProcessPoolExecutor.

    Args:
        episode_paths: List of absolute paths to video files (as strings)
        conn: Database connection object from db_utils
        ingest_run_id: Ingest run ID for tracking

    Returns:
        Tuple of (list of row counts inserted per episode, list of parquet paths)

    Raises:
        ImportError: If USE_RAY=true but Ray not installed
        RuntimeError: If Ray initialization fails
        Various exceptions from pipeline.process_single_episode
    """
    if not episode_paths:
        logger.info("No episodes to process")
        return [], []

    if should_use_ray():
        return _run_with_ray(episode_paths, conn, ingest_run_id)
    else:
        return _run_locally(episode_paths, conn, ingest_run_id)


def _run_locally(
    episode_paths: list[str], conn, ingest_run_id: int
) -> tuple[list[int], list[str]]:
    """
    Process episodes locally in a simple sequential loop.

    AMBIGUITY NOTE: This is the simplest implementation. For better performance
    without Ray, consider using multiprocessing or concurrent.futures.

    Args:
        episode_paths: List of video paths
        conn: Database connection object
        ingest_run_id: Ingest run ID for tracking

    Returns:
        Tuple of (list of row counts, list of parquet paths)
    """
    from .pipeline import process_single_episode  # Import here to avoid circular deps

    logger.info(f"Processing {len(episode_paths)} episodes locally (sequential)")

    row_counts: list[int] = []
    parquet_paths: list[str] = []

    for i, video_path in enumerate(episode_paths, 1):
        logger.info(f"Processing episode {i}/{len(episode_paths)}: {video_path}")
        try:
            rows, parquet_path = process_single_episode(video_path, conn, ingest_run_id)
            row_counts.append(rows)
            parquet_paths.append(parquet_path)
        except Exception as exc:
            logger.error(f"Failed to process {video_path}: {exc}", exc_info=True)
            # AMBIGUITY: Continue processing other episodes even if one fails
            # Alternative: raise immediately to halt pipeline on first error

    logger.info(
        f"Local processing complete: {len(row_counts)}/{len(episode_paths)} succeeded"
    )
    return row_counts, parquet_paths


def _run_with_ray(
    episode_paths: list[str], conn, ingest_run_id: int
) -> tuple[list[int], list[str]]:
    """
    Process episodes using Ray for distributed execution.

    AMBIGUITY NOTE: Ray is initialized with RAY_ADDRESS (default "auto").
    Users running a multi-machine Ray cluster should start ray head/workers
    externally and provide the cluster address via RAY_ADDRESS env var.

    AMBIGUITY NOTE: If Ray is already initialized (e.g., by another component),
    ray.init() will connect to the existing instance. Otherwise, it starts
    a new local cluster.

    AMBIGUITY NOTE: Database connection objects are typically not serializable
    for Ray remote functions. This implementation assumes the connection
    parameters can be reconstructed in remote workers. Users may need to pass
    connection strings instead of connection objects, or use Ray's put/get
    for shared objects.

    Args:
        episode_paths: List of video paths
        conn: Database connection object (may need adaptation for Ray)
        ingest_run_id: Ingest run ID for tracking

    Returns:
        Tuple of (list of row counts, list of parquet paths)

    Raises:
        ImportError: If ray not installed
        RuntimeError: If Ray initialization fails
    """
    try:
        import ray  # Lazy import
    except ImportError as exc:
        raise ImportError(
            "Ray is not installed but USE_RAY=true. "
            "Install with: pip install ray or set USE_RAY=false"
        ) from exc

    from .pipeline import process_single_episode  # Import here to avoid circular deps

    logger.info(
        f"Processing {len(episode_paths)} episodes with Ray (address: {RAY_ADDRESS})"
    )

    # Initialize Ray cluster connection
    try:
        # Check if already initialized
        if not ray.is_initialized():
            # AMBIGUITY: address="auto" means local cluster or existing cluster
            # For multi-machine setup, user should set RAY_ADDRESS to cluster URL
            ray.init(address=RAY_ADDRESS if RAY_ADDRESS else "auto")
            logger.info(f"Ray initialized: {ray.cluster_resources()}")
        else:
            logger.info("Ray already initialized, using existing instance")
    except Exception as exc:
        raise RuntimeError(f"Failed to initialize Ray: {exc}") from exc

    # Create remote version of process_single_episode
    @ray.remote
    def process_episode_remote(
        video_path: str, conn_obj, run_id: int
    ) -> tuple[int, str]:
        """
        Ray remote wrapper around process_single_episode.

        AMBIGUITY NOTE: Ray serializes function arguments. Database connections
        may not serialize properly. This function may need to recreate the
        connection using environment variables or connection strings.

        Args:
            video_path: Video file path as string
            conn_obj: Database connection object
            run_id: Ingest run ID

        Returns:
            Tuple of (row count, parquet path)
        """
        return process_single_episode(video_path, conn_obj, run_id)

    # Submit all tasks to Ray
    logger.info(f"Submitting {len(episode_paths)} tasks to Ray cluster...")
    futures = [
        process_episode_remote.remote(path, conn, ingest_run_id)
        for path in episode_paths
    ]

    # Wait for all tasks to complete and gather results
    logger.info("Waiting for Ray tasks to complete...")
    try:
        results = ray.get(futures)  # List of (row_count, parquet_path) tuples
    except Exception as exc:
        logger.error(f"Ray task execution failed: {exc}", exc_info=True)
        # AMBIGUITY: Re-raise to halt pipeline on Ray failures
        # Alternative: Could return partial results from successful tasks
        raise

    # Unzip results into separate lists
    row_counts = [r[0] for r in results]
    parquet_paths = [r[1] for r in results]

    logger.info(
        f"Ray processing complete: {len(results)}/{len(episode_paths)} episodes processed"
    )

    # AMBIGUITY: We don't call ray.shutdown() here because:
    # 1. Other tasks might be using the same Ray cluster
    # 2. Airflow workers might want to reuse the Ray connection
    # Users can shutdown Ray manually if needed

    return row_counts, parquet_paths
