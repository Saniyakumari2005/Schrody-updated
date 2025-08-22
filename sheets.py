import os
import json
import gspread
import pandas as pd
from oauth2client.file import Storage
from oauth2client.client import flow_from_clientsecrets
from oauth2client.tools import run_flow
from datetime import datetime
import pytz
import tempfile

# Step 1: Authenticate with your Google Account using OAuth
def get_worksheet():
    CLIENT_SECRET = 'client_secret.json'
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    TOKEN_FILE = 'token.json'  # credentials store as secret in Replit

    # load token from Secrets
    if os.getenv("GOOGLE_TOKEN"):
        token_data = json.loads(os.getenv("GOOGLE_TOKEN"))
        temp_token_file = tempfile.NamedTemporaryFile(delete=False)
        with open(temp_token_file.name, 'w') as f:
            json.dump(token_data, f)
        storage = Storage(temp_token_file.name)
    else:
        # Local run (creates token.json if not found)
        storage = Storage(TOKEN_FILE)

    creds = storage.get()

    if not creds or creds.invalid:
        flow = flow_from_clientsecrets(CLIENT_SECRET, SCOPES)
        creds = run_flow(flow, storage)

    gc = gspread.authorize(creds)

    # Step 2: Open the spreadsheet from your Google Drive
    sh = gc.open('discord bot reminder')  # Replace with actual spreadsheet name
    worksheet = sh.sheet1
    return worksheet

# Step 3: Load spreadsheet data into a DataFrame
def load_google_sheet():
    worksheet = get_worksheet()
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

# Update task status
def update_status(discord_id, task_name, new_status):
    worksheet = get_worksheet()
    records = worksheet.get_all_records()
    for i, row in enumerate(records):
        if str(row["discord_id"]) == str(discord_id) and row["task"] == task_name:
            worksheet.update_cell(i + 2, get_column_index(worksheet, "status"), new_status)
            break

# Update task due date if new due date provided
def update_due_date(discord_id, task_name, new_due_date):
    worksheet = get_worksheet()
    records = worksheet.get_all_records()
    for i, row in enumerate(records):
        if str(row["discord_id"]) == str(discord_id) and row["task"] == task_name:
            worksheet.update_cell(i + 2, get_column_index(worksheet, "due_date"), new_due_date)
            break

# Helper function to get column index
def get_column_index(worksheet, column_name):
    headers = worksheet.row_values(1)
    return headers.index(column_name) + 1

# A helper function that ensures deadlines are in the correct format
def parse_due_date(date_str: str):
    """Try to parse a date string in multiple formats and localize to Pacific Time."""
    formats = ["%d-%m-%Y %H:%M", "%d-%m-%Y %I:%M %p", "%d-%m-%Y"]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            tz = pytz.timezone("US/Pacific") #change to your timezone
            return tz.localize(dt)
        except ValueError:
            continue
    raise ValueError(
        f"Invalid date format: {date_str}. Please use DD-MM-YYYY HH:MM (24h or 12h with AM/PM)"
    )

if __name__ == "__main__":
    df = load_google_sheet()
    print(df.head())
