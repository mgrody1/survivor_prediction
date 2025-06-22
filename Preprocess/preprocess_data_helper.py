
import pandas as pd
import logging
import sys
from pathlib import Path

# Add the base directory to sys.path
base_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(base_dir))

#Repo imports
import params
from Utils.log_utils import setup_logging
from Utils.db_utils import connect_to_db

setup_logging(logging.DEBUG)  # Use the desired logging level
logger = logging.getLogger(__name__)

def get_castaway_features(version_season=None, episode_filter=None):
    """
    Imports the result of a custom SQL query for Castaway features from the PostgreSQL database into a pandas DataFrame,
    with optional filtering by version_season and episode number.

    Parameters:
    version_season (str, optional): The version_season to filter the query by. Default is None (no filtering).
    episode_filter (tuple, optional): A tuple containing a comparison operator ('=', '<', '>') and an episode number.
                                       Example: ('>', 5). Default is None (no filtering).

    Returns:
    pd.DataFrame: A pandas DataFrame containing the query results.
    """
    logger.info("Executing custom SQL query")
    
    # Base SQL query
    base_query = """
    WITH CastawayOccurrences AS (
        SELECT
            c.version_season,
            c.castaway_id,
            ROW_NUMBER() OVER (PARTITION BY c.castaway_id ORDER BY c.version_season) AS occurrence_order,
            COUNT(*) OVER (PARTITION BY c.castaway_id) AS occurrence_count
        FROM
            Castaways c
    )
    SELECT
        c.version_season,
        c.castaway_id,
        c.age,
        c.state,
        d.gender,
        d.african,
        d.asian,
        d.latin_american,
        d.native_american,
        d.bipoc,
        d.lgbt,
        d.personality_type,
        d.occupation,
        CASE
            WHEN o.occurrence_count > 1 AND o.occurrence_order > 1 THEN TRUE
            ELSE FALSE
        END AS returning_player
    FROM
        Castaways c
    LEFT JOIN
        Castaway_Details d
    ON
        c.castaway_id = d.castaway_id
    LEFT JOIN
        CastawayOccurrences o
    ON
        c.version_season = o.version_season
        AND c.castaway_id = o.castaway_id
    """

    # Adding filters dynamically
    filters = []
    
    if version_season:
        filters.append(f"c.version_season = '{version_season}'")
    
    if episode_filter:
        operator, episode = episode_filter
        if operator not in ['=', '<', '>']:
            logger.error("Invalid operator for episode_filter. Must be '=', '<', or '>'")
            return None
        filters.append(f"c.episode {operator} {episode}")
    
    if filters:
        filter_clause = "WHERE " + " AND ".join(filters)
        query = f"{base_query} {filter_clause}"
    else:
        query = base_query
    
    try:
        # Establish connection using the provided connection function
        conn = connect_to_db()
        # Execute the query and load the results into a DataFrame
        df = pd.read_sql(query, conn)
        logger.info("Query successfully loaded into dataframe")
        conn.close()
        return df
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return None
