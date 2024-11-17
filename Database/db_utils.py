import pandas as pd
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
import logging
import sys
from pathlib import Path

# Add the base directory to sys.path
base_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(base_dir))

#Repo imports
import params
from utils import setup_logging

setup_logging(logging.DEBUG)  # Use the desired logging level
logger = logging.getLogger(__name__)


# Function to connect to the PostgreSQL database
def connect_to_db():
    try:
        conn = psycopg2.connect(
            host=params.db_host,
            dbname=params.db_name,
            user=params.db_user,
            password=params.db_pass
        )
        logger.info("Database Conncetion Successful")

        return conn

    except Exception as e:
        logger.error("Error in connecting to database: %s", e)
        return None


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

    # Update column names to avoid sql errors
    df.rename(columns={
        "order": f"{table_name}_order",
        "result": f"{table_name}_result"
    }, inplace=True)
    
    # Handle nullable foreign keys by replacing NaN with None
    df = df.where(pd.notnull(df), None)

    df = preprocess_dataframe(df.copy(), params.timestamp_columns, params.boolean_columns)
    
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


def preprocess_dataframe(df, timestamp_columns, boolean_columns):
    """
    Replace problematic placeholders (e.g., NaT, NaN) with proper NULLs for SQL compatibility.
    """
    for col in timestamp_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')  # Convert invalid dates to NaT
            df[col].replace({pd.NaT: None}, inplace=True)       # Replace NaT with None

    # Convert numeric values to boolean for known boolean columns
    for col in boolean_columns:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: bool(x) if pd.notnull(x) else None)

    df.replace({np.nan: None, pd.NaT: None}, inplace=True)
    
    return df

# Function to import an entire table into a pandas DataFrame
def import_table_to_df(table_name):
    """
    Imports an entire table from the PostgreSQL database into a pandas DataFrame.

    Parameters:
    table_name (str): Name of the table to import.

    Returns:
    pd.DataFrame: A pandas DataFrame containing the table data.
    """
    logger.info("Executing SQL query")
    try:
        # Establish connection using the provided connection function
        conn = connect_to_db()
        # Load the entire table into a DataFrame
        query = f"SELECT * FROM {table_name}"
        df = pd.read_sql(query, conn)
        logger.info("Query successfully loaded into dataframe")
        conn.close()
        return df
    except Exception as e:
        logger.info(f"Error importing table {table_name}: {e}")
        return None

# Function to import a custom SQL query into a pandas DataFrame
def import_query_to_df(query):
    """
    Imports the result of a custom SQL query from the PostgreSQL database into a pandas DataFrame.

    Parameters:
    query (str): The SQL query to execute.

    Returns:
    pd.DataFrame: A pandas DataFrame containing the query results.
    """
    logger.info("Executing SQL query")
    try:
        # Establish connection using the provided connection function
        conn = connect_to_db()
        # Execute the query and load the results into a DataFrame
        df = pd.read_sql(query, conn)
        logger.info("Query successfully loaded into dataframe")
        conn.close()
        return df
    except Exception as e:
        logger.info(f"Error executing query: {e}")
        return None


