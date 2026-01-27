#!/usr/bin/env python3
"""
Script to migrate existing performer data to the new items table
"""

import sqlite3
import csv
from pathlib import Path

def migrate_existing_data():
    """Migrate existing data from performers table to the new items table"""

    # Connect to the database
    conn = sqlite3.connect("performers.db")
    cursor = conn.cursor()

    # Read the CSV file to get the item details
    csv_file_path = "extracted.csv"

    if not Path(csv_file_path).exists():
        print(f"CSV file {csv_file_path} not found!")
        return

    # Read the CSV file
    items = []
    with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        items = list(reader)

    print(f"Processing {len(items)} items from CSV...")

    # Track migrated items
    migrated_count = 0

    for row in items:
        item_url = row.get('item_url', '').strip()
        performers_str = row.get('performers', '').strip()
        title = row.get('title', '').strip()
        item_date = row.get('item_date', '').strip()
        hits = row.get('hits', '').strip()
        source_file = row.get('source_file', '').strip()

        if not item_url or not performers_str:
            continue

        # Split performers if multiple exist
        performers = [p.strip() for p in performers_str.split(';') if p.strip()]
        if not performers:
            continue

        for performer in performers:
            # Get the performer ID from the performers table
            cursor.execute("SELECT id FROM performers WHERE name = ?", (performer,))
            result = cursor.fetchone()

            if result:
                performer_id = result[0]

                # Check if this item already exists for this performer
                cursor.execute("""
                    SELECT id FROM items
                    WHERE performer_id = ? AND item_url = ?
                """, (performer_id, item_url))

                existing_item = cursor.fetchone()

                if not existing_item:
                    # Convert hits to integer if possible
                    hits_int = None
                    if hits:
                        try:
                            hits_int = int(hits.replace(',', ''))
                        except ValueError:
                            hits_int = None

                    # Insert the item into the items table
                    cursor.execute("""
                        INSERT INTO items (performer_id, item_url, title, item_date, hits, source_file)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (performer_id, item_url, title, item_date, hits_int, source_file))

                    migrated_count += 1
                else:
                    # Item already exists for this performer
                    continue
            else:
                print(f"Warning: Performer '{performer}' not found in database")

    # Commit changes
    conn.commit()
    conn.close()

    print(f"Migrated {migrated_count} items to the items table.")

if __name__ == "__main__":
    migrate_existing_data()
