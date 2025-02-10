# Survivor Prediction Repo
Repo for analysis of CBS reality show Survivor and predicting the outcomes of each season data can be found [here](https://docs.google.com/spreadsheets/d/1Xhod9FdVFr69hrX7No40WZAz0ZmhO_5x6WghxawuSno/edit?gid=1849373991#gid=1849373991)

This program is currently set-up to ingest the excel workbook version of the data to process and load into a Postgres SQL database

## Virtual Environment
Make sure you have pipenv installed, if not, run 
```
pip install pipenv
```

Once pipenv is installed, install the dependencies by running 
```
pipenv install
```

Activate the virtual environment by running 
```
pipenv shell
```

## Create Database and Load Data
Create your own PostgreSQL database and update the .env file with the appropriate parameters

In your sql editor, run the script create_tables.sql to create the tables

To load the data, run: 
```
python Database/load_survivor_data.py
```
