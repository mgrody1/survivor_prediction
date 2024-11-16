from dotenv import load_dotenv
import pandas as pd
import os

### Environmental Variabls

# Load environment variables from the .env file
load_dotenv()

# Create python variables from .env variables
db_host = os.getenv("DB_HOST")
db_name = os.getenv("DB_NAME")
db_user = os.getenv("DB_USER")
db_pass = os.getenv("DB_PASS")

### Local Paths
survivor_wb_path = r"/home/mhgr/Downloads/survivoR.xlsx"

# Sheets to Tables Mapping
SHEET_TO_TABLE = {
    "Advantage Details": "Advantages",
    "Advantage Movement": "Advantage_Movement",
    "Boot Mapping": "Vote_History",
    "Castaway Details": "Castaways",
    "Castaways": "Tribe_Memberships",
    "Challenge Description": "Challenges",
    "Challenge Results": "Challenge_Results",
    "Vote History": "Vote_History",
    "Episodes": "Episodes",
    "Confessionals": "Confessionals",
    "Jury Votes": "Jury_Votes",
    "Season Summary": "Seasons",
    "Tribe Mapping": "Tribe_Memberships",
    "Screen Time": "Screen_Time",
    "Episode Summary": "Episodes"
}