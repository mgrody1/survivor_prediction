# Survivor Prediction Repo
Repo for analysis of CBS reality show Survivor and predicting the outcomes of each season data can be found [here](https://docs.google.com/spreadsheets/d/1Xhod9FdVFr69hrX7No40WZAz0ZmhO_5x6WghxawuSno/edit?gid=1849373991#gid=1849373991)

This program is currently set-up to ingest the excel workbook version of the data to process and load into a Postgres SQL database


Repo for analyzing CBS's reality show Survivor and predicting outcomes using machine learning.  
Includes data ingestion, database setup, feature engineering, and modeling tools.

## 📦 Virtual Environment

Make sure pipenv is installed:
pip install pipenv

Then install dependencies:
pipenv install

Activate the virtual environment:
pipenv shell

## 🗃️ Database Setup

###     1. Create PostgreSQL Database

    - Create a new PostgreSQL database manually
    - Update the .env file with your DB credentials:

    DB_HOST=your-db-host  
    DB_NAME=your-db-name  
    DB_USER=your-username  
    DB_PASSWORD=your-password  
    PORT=5432

    ### 2. Configure App Settings

    Update config.json with:

    {
    "excel_path": "/path/to/survivoR.xlsx",
    "first_run": true,
    "truncate_on_load": false
    }

###     3. Create Tables and Load Data

    Run the full loader:
    python load_survivor_data.py

    - If first_run is true, it will auto-create all tables from Database/create_table.sql
    - Then it will load data incrementally from the Excel workbook
    - On future runs, set first_run back to false and just update weekly data

###     ✅ Features

    - Auto-creates relational schema
    - Supports incremental row-level updates
    - Schema validation and type coercion
    - Logs failed row inserts for debugging
    - Weekly episode updates supported

###     📁 File Overview

    load_survivor_data.py  
    → Orchestrates first-run table creation and incremental data loading

    Database/db_utils.py  
    → Contains DB connection logic, schema validation, and loading functions

    Database/create_table.sql  
    → Full SQL schema for all Survivor data tables

    Database/table_config.json  
    → Table metadata: load order, primary keys, boolean + timestamp columns

    config.json  
    → Excel file path and loader flags (first_run, truncate_on_load)

    .env  
    → DB credentials


To load the data, run: 
```
python Database/load_survivor_data.py
```

