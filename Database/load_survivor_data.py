import logging
import sys
from pathlib import Path

# Add the base directory to sys.path
base_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(base_dir))

#Repo imports
import params
from Database.db_utils import connect_to_db, load_sheet_to_table
from utils import setup_logging

setup_logging(logging.DEBUG)  # Use the desired logging level
logger = logging.getLogger(__name__)


# Main script
if __name__ == "__main__":
    # Establish a database connection
    logger.info("Establishing db connection")
    conn = connect_to_db()
    
    try:
        logger.info("Loading sheets into db")
        for config in params.load_order:
            sheet_name = config["sheet_name"]
            table_name = config["table_name"]
            logger.info(f"Loading sheet '{sheet_name}' into table '{table_name}'...")
            load_sheet_to_table(sheet_name=sheet_name, table_name=table_name, conn=conn)

    except Exception as e:
        logger.error("An error occurred: %s", e)
    finally:
        conn.close()
        logger.info("Database connection closed.")
