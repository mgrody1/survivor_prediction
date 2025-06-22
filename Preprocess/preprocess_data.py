import logging
import sys
from pathlib import Path

# Add the base directory to sys.path
base_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(base_dir))

#Repo imports
import params
from Utils.db_utils import create_sql_engine
from Utils.log_utils import setup_logging
from preprocess_data_helper import get_castaway_features

setup_logging(logging.DEBUG)  # Use the desired logging level
logger = logging.getLogger(__name__)


# Main script
if __name__ == "__main__":
    # Establish a database connection
    logger.info("Establishing db connection")
    
    try:
        castaway_features = get_castaway_features()
        logger.info("castaway_features read-in")
    except Exception as e:
        logger.error("An error occurred: %s", e)