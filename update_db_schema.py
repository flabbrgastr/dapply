#!/usr/bin/env python3
"""
Script to update the database schema to include the new items table
and migrate existing data if needed.
"""

import sqlite3
import os
from dbadd import create_db

def update_database_schema():
    """Update the database schema to include the new items table"""

    # Check if database exists
    db_path = "performers.db"

    if os.path.exists(db_path):
        print(f"Found existing database: {db_path}")

        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if items table already exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='items';")
        table_exists = cursor.fetchone()

        if table_exists:
            print("Items table already exists.")
        else:
            print("Creating items table...")
            # Create the items table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    performer_id INTEGER,
                    item_url TEXT NOT NULL,
                    title TEXT,
                    item_date TEXT,  -- Date from the source if available
                    hits INTEGER,
                    source_file TEXT,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (performer_id) REFERENCES performers (id)
                )
            ''')
            print("Items table created successfully.")

        conn.commit()
        conn.close()
        print("Database schema updated successfully!")
    else:
        print(f"Database {db_path} does not exist. Creating a new one...")
        create_db(db_path)
        print("New database created with updated schema!")

if __name__ == "__main__":
    update_database_schema()
