"""
Database Add Module for Performer Data

This module adds performer data to a SQLite database with:
- Unique performer names as keys
- Unique URLs tracking
- Last updated timestamp
- Crawls counter (starts at 0, increments with each crawl)
"""

import csv
import sqlite3
from datetime import datetime
from pathlib import Path


def create_db(db_path):
    """
    Create the performers database with required schema
    Includes migration logic to add new columns if they exist.

    Args:
        db_path (str): Path to the SQLite database file
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create performers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS performers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            urls TEXT,  -- Pipe-separated string of unique URLs
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            crawls INTEGER DEFAULT 0,
            aka TEXT,
            rating TEXT
        )
    ''')

    # Create items table to store individual items with performer association and add date
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

    # Migration: Add aka and rating if they are missing from an old database
    cursor.execute("PRAGMA table_info(performers)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'aka' not in columns:
        cursor.execute("ALTER TABLE performers ADD COLUMN aka TEXT")
    if 'rating' not in columns:
        cursor.execute("ALTER TABLE performers ADD COLUMN rating TEXT")

    conn.commit()
    conn.close()


def add_performers_from_items(items, db_path="performers.db"):
    """
    Add performers from a list of items to SQLite database

    Args:
        items (list): List of dictionaries containing item data
        db_path (str): Path to the SQLite database file
    """
    # Create database if it doesn't exist
    create_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    new_performers_added = []
    updated_performers = []

    for row in items:
        item_url = row.get('item_url', '').strip()
        performers_str = row.get('performers', '').strip()
        title = row.get('title', '').strip()
        item_date = row.get('item_date', '').strip()
        hits = row.get('hits', '').strip()
        source_file = row.get('source_file', '').strip()

        if not item_url:
            continue

        # Handle missing performers by using a default name
        if not performers_str:
            performers = ["NO_NAME"]
        else:
            # Split performers if multiple exist
            performers = [p.strip() for p in performers_str.split(';') if p.strip()]
            # If splitting results in an empty list somehow
            if not performers:
                performers = ["NO_NAME"]

        for performer in performers:
            # Check if performer already exists in database
            cursor.execute("SELECT id, urls, crawls FROM performers WHERE name = ?", (performer,))
            result = cursor.fetchone()

            if result:
                # Performer exists, update their record
                performer_id, existing_urls_str, current_crawls = result

                # Use a set to maintain uniqueness of URLs
                if existing_urls_str:
                    # Split and filter out empty strings
                    existing_urls = {u.strip() for u in existing_urls_str.split('|') if u.strip()}
                else:
                    existing_urls = set()

                # Check if this is a new URL
                is_new_url = item_url not in existing_urls

                if is_new_url:
                    existing_urls.add(item_url)
                    # Only increment crawls if we actually found a new video for this performer
                    new_crawl_count = current_crawls + 1
                    updated_performers.append((performer, item_url))
                else:
                    new_crawl_count = current_crawls

                # Update the record
                updated_urls_str = '|'.join(sorted(list(existing_urls)))

                cursor.execute("""
                    UPDATE performers
                    SET urls = ?,
                        last_updated = CURRENT_TIMESTAMP,
                        crawls = ?
                    WHERE name = ?
                """, (updated_urls_str, new_crawl_count, performer))

            else:
                # Performer doesn't exist, insert new record with initial crawl count of 1
                # aka and rating are initialized as empty
                cursor.execute("""
                    INSERT INTO performers (name, urls, last_updated, crawls, aka, rating)
                    VALUES (?, ?, CURRENT_TIMESTAMP, 1, '', '')
                """, (performer, item_url))

                # Get the ID of the newly inserted performer
                performer_id = cursor.lastrowid
                new_performers_added.append((performer, item_url))

            # Insert the item into the items table
            # Convert hits to integer if possible
            hits_int = None
            if hits:
                try:
                    hits_int = int(hits.replace(',', ''))
                except ValueError:
                    hits_int = None

            cursor.execute("""
                INSERT INTO items (performer_id, item_url, title, item_date, hits, source_file)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (performer_id, item_url, title, item_date, hits_int, source_file))

    # Commit changes and close connection
    conn.commit()
    conn.close()

    # Print summary information
    if new_performers_added:
        print(f"Added {len(new_performers_added)} new performers to the database:")
        for name, url in new_performers_added[:20]:  # Show first 20 new performers
            print(f"  - {name} ({url})")
        if len(new_performers_added) > 20:
            print(f"  ... and {len(new_performers_added) - 20} more")

    if updated_performers:
        print(f"Updated {len(updated_performers)} existing performers with new content:")
        for name, url in updated_performers[:20]:  # Show first 20 updated performers
            print(f"  - {name} ({url})")
        if len(updated_performers) > 20:
            print(f"  ... and {len(updated_performers) - 20} more")

    if not new_performers_added and not updated_performers:
        print("No new performers or updates found.")


def add_performers_from_csv(csv_file_path, db_path="performers.db"):
    """
    Add performers from extracted.csv to SQLite database

    Args:
        csv_file_path (str): Path to the extracted CSV file
        db_path (str): Path to the SQLite database file
    """
    # Read the CSV file
    items = []
    with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        items = list(reader)

    add_performers_from_items(items, db_path)
    print(f"Added performer data from {csv_file_path} to {db_path}")


def main():
    """Main function to run the database add module"""
    csv_file_path = "extracted.csv"
    db_file_path = "performers.db"

    # Check if CSV file exists
    if not Path(csv_file_path).exists():
        print(f"CSV file {csv_file_path} not found!")
        return

    add_performers_from_csv(csv_file_path, db_file_path)
    print("Database update completed!")


if __name__ == "__main__":
    main()
