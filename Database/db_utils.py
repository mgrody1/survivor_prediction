import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import logging

#Repo imports
import params
from utils import setup_logging

setup_logging(logging.DEBUG)  # Use the desired logging level
logger = logging.getLogger(__name__)


# Function to connect to the PostgreSQL database
def connect_to_db():
    try:
        conn = psycopg2.connect(
            host=params.DB_HOST,
            dbname=params.DB_NAME,
            user=params.DB_USER,
            password=params.DB_PASSWORD
        )
        logger.info("Database Conncetion Successful")

    except Exception as e:
        logger.error("Error in connecting to database: %s", e)

    return conn


# Function to truncate the table before loading new data
def truncate_table(table_name, conn):
    logger.info(f"Truncating table '{table_name}'...")
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;")
        conn.commit()
    logger.info(f"Table '{table_name}' truncated successfully.")

# Function to load data into PostgreSQL with truncation
def load_sheet_to_table(sheet_name, table_name, conn, primary_key_columns=None):
    logger.info(f"Loading sheet '{sheet_name}' into table '{table_name}'...")
    
    # Load the sheet into a DataFrame
    df = pd.read_excel(params.survivor_wb_path, sheet_name=sheet_name)
    
    # Transform column names to lowercase and underscores for SQL compatibility
    df.columns = df.columns.str.lower().str.replace(" ", "_")
    
    # Handle nullable foreign keys by replacing NaN with None
    df = df.where(pd.notnull(df), None)
    
    # Truncate the table before loading
    truncate_table(table_name, conn)
    
    # Create a list of tuples from the DataFrame for bulk insert
    data = [tuple(row) for row in df.itertuples(index=False)]
    
    # Build the INSERT query
    columns = ", ".join(df.columns)
    if primary_key_columns:
        # Composite primary keys handling
        pk_clause = ", ".join(primary_key_columns)
        query = f"""
            INSERT INTO {table_name} ({columns}) VALUES %s
            ON CONFLICT ({pk_clause}) DO NOTHING
        """
    else:
        # Simple INSERT for tables without primary keys
        query = f"INSERT INTO {table_name} ({columns}) VALUES %s"
    
    # Execute the query
    with conn.cursor() as cur:
        execute_values(cur, query, data)
        conn.commit()
    logger.info(f"Sheet '{sheet_name}' successfully loaded into '{table_name}'.")

