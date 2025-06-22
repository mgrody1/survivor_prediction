import logging
import os
import sys
import traceback

def setup_logging(log_level=logging.INFO, log_filename="pipeline.log"):
    """
    Set up logging configuration for the entire repository.
    Logs are written to both the terminal and a log file in the current directory.
    """
    log_path = os.path.join(os.getcwd(), log_filename)

    # Set up handlers
    stream_handler = logging.StreamHandler()
    file_handler = logging.FileHandler(log_path, mode='w')  # Overwrite on each run

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    stream_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.setLevel(log_level)

    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

    # Suppress overly verbose logs from third-party libraries
    for lib in ["urllib3", "botocore", "s3transfer"]:
        logging.getLogger(lib).setLevel(logging.WARNING)

    # Hook into uncaught exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            # Let Ctrl+C exit cleanly
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
        # Flush all handlers to ensure logs are written
        for handler in logger.handlers:
            handler.flush()
            handler.close()

    sys.excepthook = handle_exception
