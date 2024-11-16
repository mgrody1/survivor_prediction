from dotenv import load_dotenv
import pandas as pd
import os
import json

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

### DB Config
with open("table_config.json", "r") as f:
    table_config = json.load(f)
