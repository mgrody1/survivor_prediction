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
db_pass = os.getenv("DB_PASSWORD")

### Local Paths
survivor_wb_path = os.getenv("SURVIVOR_WB_PATH")

### DB Config
with open("Database/table_config.json", "r") as f:
    table_config = json.load(f)

# Define the load order for tables based on dependencies
load_order = [
    {"sheet_name": "Season Summary", "table_name": "season_summary"},
    {"sheet_name": "Castaways", "table_name": "castaways"},
    {"sheet_name": "Castaway Details", "table_name": "castaway_details"},
    {"sheet_name": "Episodes", "table_name": "episodes"},
    {"sheet_name": "Advantage Details", "table_name": "advantage_details"},
    {"sheet_name": "Advantage Movement", "table_name": "advantage_movement"},
    {"sheet_name": "Boot Mapping", "table_name": "boot_mapping"},
    {"sheet_name": "Challenge Description", "table_name": "challenge_description"},
    {"sheet_name": "Challenge Results", "table_name": "challenge_results"},
    {"sheet_name": "Vote History", "table_name": "vote_history"},
    {"sheet_name": "Confessionals", "table_name": "confessionals"},
    {"sheet_name": "Jury Votes", "table_name": "jury_votes"},
    {"sheet_name": "Tribe Mapping", "table_name": "tribe_mapping"},
    {"sheet_name": "Episode Summary", "table_name": "episode_summary"},
]

timestamp_columns = ['premiered', 'ended', 'filming_started', 'filming_ended', 'episode_date']
boolean_columns = [
    # Castaway Details
    'african', 'asian', 'latin_american', 'native_american', 'bipoc', 'lgbt',

    # Castaways
    'jury', 'finalist', 'winner', 'acknowledge', 'ack_look', 'ack_speak', 
    'ack_gesture', 'ack_smile',

    # Advantage Movement
    'success',

    # Challenge Results
    'chosen_for_reward', 'sit_out',

    # Vote History
    'immunity', 'split_vote', 'nullified', 'tie',

    # Challenge Details
    'balance', 'balance_ball', 'balance_beam', 'endurance', 'fire', 'food', 'knowledge', 
    'memory', 'mud', 'obstacle_blindfolded', 'obstacle_cargo_net', 'obstacle_chopping',
    'obstacle_digging', 'obstacle_knots', 'obstacle_padlocks', 'obstacle_combination_lock', 'precision', 'precision_catch',
    'precision_roll_ball', 'precision_slingshot', 'precision_throw_balls', 'precision_throw_coconuts',
    'precision_throw_rings', 'precision_throw_sandbags', 'puzzle', 'puzzle_slide', 'puzzle_word',
    'race', 'strength', 'turn_based', 'water', 'water_paddling', 'water_swim'
]


