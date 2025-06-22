import pandas as pd
import numpy as np
import psycopg2
from psycopg2.extensions import connection
from typing import Optional
from sqlalchemy import create_engine
import logging
import sys
from pathlib import Path

# Add the base directory to sys.path
base_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(base_dir))

# Repo imports
import params
from Utils.log_utils import setup_logging

setup_logging(logging.DEBUG)
logger = logging.getLogger(__name__)


def connect_to_db() -> Optional[connection]:
    try:
        conn = psycopg2.connect(
            host=params.db_host,
            dbname=params.db_name,
            user=params.db_user,
            password=params.db_pass
        )
        logger.info("Database Connection Successful")
        return conn
    except Exception as e:
        logger.error("Error in connecting to database: %s", e)
        return None


def create_sql_engine():
    return create_engine(
        f"postgresql://{params.db_user}:{params.db_pass}@{params.db_host}/{params.db_name}"
    )


def truncate_table(table_name, conn):
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;")
        conn.commit()


def get_db_column_types(table_name, conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = %s;
            """, (table_name,))
        return {row[0]: row[1] for row in cur.fetchall()}


def preprocess_dataframe(df, db_schema):
    df = df.copy()
    coerced_log = {}

    for col in df.columns:
        db_col_type = db_schema.get(col)
        if db_col_type:
            try:
                original_non_null = df[col].notna()

                if db_col_type == 'boolean':
                    df[col] = df[col].astype(str).str.strip().str.lower().map({
                        'true': True, 't': True, 'yes': True, '1': True,
                        'false': False, 'f': False, 'no': False, '0': False
                    }).astype('boolean')
                elif db_col_type == 'integer':
                    df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
                elif db_col_type == 'double precision':
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                elif db_col_type == 'date':
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                else:
                    df[col] = df[col].astype(str)

                coerced_rows = original_non_null & df[col].isna()
                if coerced_rows.any():
                    coerced_log[col] = df[coerced_rows].index.tolist()
            except Exception as e:
                logger.warning(f"Could not convert column {col} to {db_col_type}: {e}")

    # Explicitly convert NaT → None for PostgreSQL compatibility
    datetime_cols = df.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns
    for col in datetime_cols:
        df[col] = df[col].astype(object).where(pd.notnull(df[col]), None)

    for col, indices in coerced_log.items():
        logger.warning(f"Coercion occurred in column '{col}' for rows: {indices[:10]}{'...' if len(indices) > 10 else ''}")

    # Handle string "NaT", "nan", etc. to real None
    df.replace(["NaT", "nan", "NaN"], np.nan, inplace=True)
    df = df.where(pd.notnull(df), None)

    return df


def fetch_existing_keys(table_name, conn, key_columns):
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(key_columns)} FROM {table_name};")
        return pd.DataFrame(cur.fetchall(), columns=key_columns)


def validate_schema(sheet_df, table_name, conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 
                column_name, 
                data_type,
                EXISTS (
                    SELECT 1 
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    WHERE tc.table_name = %s 
                    AND tc.constraint_type = 'PRIMARY KEY'
                    AND kcu.column_name = c.column_name
                ) AS is_primary_key
            FROM information_schema.columns c
            WHERE table_name = %s;
            """,
            (table_name, table_name)
        )
        db_schema_info = cur.fetchall()

    sheet_df.columns = [c.lower().strip().replace(" ", "_") for c in sheet_df.columns]
    sheet_cols = set(sheet_df.columns)

    db_schema = {}
    db_pks = set()
    for col, dtype, is_pk in db_schema_info:
        db_schema[col] = dtype
        if is_pk:
            db_pks.add(col)

    db_cols = set(db_schema.keys())
    missing = {col for col in db_cols - sheet_cols if col not in db_pks}
    extra = sheet_cols - db_cols

    if missing:
        logger.warning(f"Missing columns for {table_name}: {missing}")
    if extra:
        logger.warning(f"Extra columns in sheet {table_name}: {extra}")

    type_issues = {}
    type_map = {
        'character varying': 'object',
        'text': 'object',
        'boolean': 'bool',
        'integer': 'int64',
        'double precision': 'float64',
        'date': 'datetime64[ns]'
    }
    for col in sheet_df.columns:
        if col in db_schema:
            expected = type_map.get(db_schema[col], None)
            actual = str(sheet_df[col].dtype)
            if expected:
                actual_lower = actual.lower()
                expected_lower = expected.lower()
                if expected_lower not in actual_lower:
                    if expected_lower == 'datetime64[ns]' and actual_lower == 'object':
                        continue
                    type_issues[col] = (expected, actual)

    if type_issues:
        logger.warning(f"Data type mismatches in {table_name}: {type_issues}")

    return not extra and not type_issues


def load_sheet_to_table(sheet_name, table_name, conn, unique_constraint_columns=None, truncate=True):
    df = pd.read_excel(params.excel_path, sheet_name=sheet_name)
    df.columns = df.columns.str.lower().str.replace(" ", "_")
    if sheet_name == "Castaways":
        df.rename(columns={"order": "castaways_order"}, inplace=True)

        valid_ids = fetch_existing_keys("castaway_details", conn, ["castaway_id"])["castaway_id"].tolist()

        before = len(df)
        dropped_df = df[~df["castaway_id"].isin(valid_ids)]
        df = df[df["castaway_id"].isin(valid_ids)]
        dropped = before - len(df)

        if dropped:
            logger.warning(f"Skipped {dropped} castaways due to missing castaway_id in castaway_details.")
            logger.debug(f"Dropped rows (first 20 shown):\n{dropped_df.head(20).to_string(index=False)}")

    if sheet_name == "Boot Mapping":
        df.rename(columns={"order": "boot_mapping_order"}, inplace=True)
    if sheet_name == "Vote History":
        df.rename(columns={"order": "vote_history_order"}, inplace=True)
    #TODO: Handle share4d advantages, filter out for now
    if sheet_name == "Advantage Movement":
        df = df[~df["castaway_id"].str.contains(",")]
    db_schema = get_db_column_types(table_name, conn)
    df = preprocess_dataframe(df, db_schema)

    if not validate_schema(df, table_name, conn):
        raise ValueError(f"Schema mismatch in {table_name}, halting load.")

    if truncate:
        truncate_table(table_name, conn)
        logger.info(f"Truncated table {table_name}")

    if unique_constraint_columns and not truncate:
        existing = fetch_existing_keys(table_name, conn, unique_constraint_columns)
        df = df.merge(existing, on=unique_constraint_columns, how='left', indicator=True)
        df = df[df['_merge'] == 'left_only'].drop(columns=['_merge'])

    if df.empty:
        logger.info(f"No new rows to insert for {table_name}.")
        return

    try:
        engine = create_sql_engine()
        df.to_sql(
            name=table_name,
            con=engine,
            if_exists='append',
            index=False,
            method='multi'
        )
        logger.info(f"Inserted {len(df)} rows into {table_name}")
    except Exception as e:
        logger.error(f"Bulk insert failed for {table_name}: {e}")
        raise RuntimeError(f"Row insertion failed for {table_name}") from e


def run_schema_sql(conn):
    if schema_exists(conn):
        logger.warning("Existing schema detected — dropping all public tables.")
        with conn.cursor() as cur:
            cur.execute("""
                DO $$ DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END $$;
            """)
            conn.commit()

    logger.info("Creating new schema from SQL script...")
    with open("Database/create_tables.sql", "r") as f:
        schema_sql = f.read()

    with conn.cursor() as cur:
        statements = [s.strip() for s in schema_sql.split(';') if s.strip()]
        for stmt in statements:
            try:
                cur.execute(stmt + ';')
            except Exception as e:
                logger.error(f"Failed to execute SQL statement:\n{stmt}\nError: {e}")
                raise
        conn.commit()

    logger.info("Schema creation complete.")


def get_unique_constraint_cols_from_table_name(table_name):
    table_config_keys = [key for key, value in params.table_config.items()
                         if isinstance(value, dict) and value.get("table_name") == table_name]

    assert len(table_config_keys), "There should only be one key per table in the table_config"
    table_config_key = table_config_keys[0]

    return params.table_config[table_config_key]["unique_constraint_columns"]


def schema_exists(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                LIMIT 1
            );
        """)
        return cur.fetchone()[0]
    
# Function to import an entire table into a pandas DataFrame
def import_table_to_df(table_name: str) -> pd.DataFrame | None:
    """
    Imports a PostgreSQL table into a pandas DataFrame.
    """
    logger.info("Executing SQL query")
    try:
        engine = create_sql_engine()
        query = f"SELECT * FROM {table_name}"
        df = pd.read_sql(query, con=engine)
        logger.info("Query successfully loaded into dataframe")
        return df
    except Exception as e:
        logger.error(f"Error importing table {table_name}: {e}")
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
        engine = create_sql_engine()
        # Execute the query and load the results into a DataFrame
        df = pd.read_sql(query, con=engine)
        logger.info("Query successfully loaded into dataframe")
        return df
    except Exception as e:
        logger.info(f"Error executing query: {e}")
        return None
