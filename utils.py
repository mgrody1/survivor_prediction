import logging

def setup_logging(log_level=logging.INFO):
    """
    Set up logging configuration for the entire repository.
    Logs will be displayed in the terminal.
    
    :param log_level: Logging level (e.g., logging.DEBUG, logging.INFO, etc.)
    """
    # Define the basic configuration for logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()]  # Logs to terminal
    )

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Suppress overly verbose logs from third-party libraries (optional)
    for lib in ["urllib3", "botocore", "s3transfer"]:
        logging.getLogger(lib).setLevel(logging.WARNING)