import logging
import sys
from pathlib import Path

# Add the base directory to sys.path
base_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(base_dir))

# Repo imports
import params
from Utils.db_utils import (
    connect_to_db,
    load_sheet_to_table,
    run_schema_sql,
    get_unique_constraint_cols_from_table_name
)
from Utils.log_utils import setup_logging

setup_logging(logging.DEBUG)
logger = logging.getLogger(__name__)


def main():
    conn = connect_to_db()
    if not conn:
        logger.error("Database connection failed. Exiting.")
        return

    if params.first_run:
        logger.info("First run detected — creating schema.")
        run_schema_sql(conn)

    for table in params.load_order:
        sheet_name = table["sheet_name"]
        table_name = table["table_name"]
        unique_cols = get_unique_constraint_cols_from_table_name(table_name)

        logger.info(f"Loading sheet '{sheet_name}' into table '{table_name}'...")
        try:
            load_sheet_to_table(
                sheet_name=sheet_name,
                table_name=table_name,
                conn=conn,
                unique_constraint_columns=unique_cols,
                truncate=params.truncate_on_load
            )
        except Exception as e:
            logger.error(f"Error loading table '{table_name}': {e}")
            conn.close()
            raise

    conn.close()
    logger.info("ETL process complete.")


if __name__ == "__main__":
    main()
