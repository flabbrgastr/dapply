"""
Database Add Module for Performer Data

This module adds performer data to a SQLite database with:
- Unique performer names as keys
- Unique URLs tracking
- Last updated timestamp
- Crawls counter (starts at 0, increments with each crawl)
"""

import csv
import difflib
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

    # Load all existing performers for fuzzy matching
    cursor.execute("SELECT id, name, urls, crawls, aka FROM performers")
    all_rows = cursor.fetchall()
    perf_by_name: dict = {row[1]: {"id": row[0], "urls": row[2], "crawls": row[3], "aka": row[4] or ""} for row in all_rows}
    perf_names: list = list(perf_by_name.keys())

    new_performers_added = []
    updated_performers = []
    fuzzy_merged: list = []  # Track fuzzy merges for aka updates

    def _find_performer(name: str):
        """Find performer by exact or fuzzy name match."""
        if name in perf_by_name:
            return name, perf_by_name[name]
        # Fuzzy match
        matches = difflib.get_close_matches(name, perf_names, n=1, cutoff=0.85)
        if matches:
            matched = matches[0]
            return matched, perf_by_name[matched]
        return None, None

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
            performers = [p.strip() for p in performers_str.split(';') if p.strip()]
            if not performers:
                performers = ["NO_NAME"]

        for performer in performers:
            # Find existing performer (exact or fuzzy match)
            matched_name, result = _find_performer(performer)

            if result:
                # Performer exists, update their record
                performer_id = result["id"]
                existing_urls_str = result["urls"]
                current_crawls = result["crawls"]

                # If fuzzy match, update AKA to track alternative spelling
                if matched_name != performer:
                    current_aka = result["aka"]
                    if performer.lower() not in current_aka.lower():
                        new_aka = (current_aka + " | " + performer).strip(" | ")
                        cursor.execute("UPDATE performers SET aka = ? WHERE id = ?", (new_aka, performer_id))
                        perf_by_name[matched_name]["aka"] = new_aka
                        fuzzy_merged.append((performer, matched_name))

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
                    WHERE id = ?
                """, (updated_urls_str, new_crawl_count, performer_id))

            else:
                # New performer
                cursor.execute("""
                    INSERT INTO performers (name, urls, last_updated, crawls, aka, rating)
                    VALUES (?, ?, CURRENT_TIMESTAMP, 1, '', '')
                """, (performer, item_url))

                performer_id = cursor.lastrowid
                new_performers_added.append((performer, item_url))

                # Update cache so subsequent rows find this performer
                perf_by_name[performer] = {"id": performer_id, "urls": item_url, "crawls": 1, "aka": ""}
                perf_names.append(performer)

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

    # Print summary (quiet — orchestator shows its own per-site summary)
    if fuzzy_merged:
        for alt, canon in fuzzy_merged:
            print(f"  ~ merged '{alt}' -> '{canon}' (AKA)")


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
