import logging

#Repo imports
import params
from Database.db_utils import connect_to_db, load_sheet_to_table
from utils import setup_logging

setup_logging(logging.DEBUG)  # Use the desired logging level
logger = logging.getLogger(__name__)


# Main script
if __name__ == "__main__":
    # Establish a database connection
    conn = connect_to_db()
    
    try:
        # Iterate over the sheets and load them into the corresponding tables
        for sheet_name, config in params.table_config.items():
            load_sheet_to_table(
                sheet_name=sheet_name,
                table_name=config["table_name"],
                conn=conn,
                primary_key_columns=config.get("primary_key_columns")
    )

    except Exception as e:
        logger.error("An error occurred: %s", e)
    finally:
        conn.close()
        logger.info("Database connection closed.")
