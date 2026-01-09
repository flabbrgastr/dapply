"""
Remover Module - Removes items from CSV and DB based on site filter.
"""

import csv
import sqlite3
import os
from pathlib import Path

def remove_site_data(site_name, csv_path="extracted.csv", db_path="performers.db"):
    """
    Remove items from both CSV and DB that match the site_name.
    
    Args:
        site_name (str): The name of the site to remove (found in source_file path)
        csv_path (str): Path to extracted.csv
        db_path (str): Path to performers.db
    """
    if not os.path.exists(csv_path):
        print(f"CSV file {csv_path} not found.")
        return

    # 1. Process CSV
    removed_urls_set = set()
    with open(csv_path, 'r', encoding='utf-8') as f:
        # We'll use csv.reader to be independent of header inconsistencies
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return

        remaining_rows = []
        for row in reader:
            if not row:
                continue
            
            # Check if any column contains the site name
            match_found = any(site_name in col for col in row if col)
            
            if match_found:
                # Add ALL values from this row to the set of things to remove from DB
                # This handles cases where columns were swapped
                for col in row:
                    if col and col.strip():
                        # Remove fragment from URLs if it looks like one
                        val = col.strip().split('#')[0]
                        removed_urls_set.add(val)
                removed_count_in_csv = len(removed_urls_set) # Just to track progress
            else:
                remaining_rows.append(row)
    
    if not removed_urls_set and not remaining_rows:
        print(f"No items found for site '{site_name}' in {csv_path}.")
    else:
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(remaining_rows)
        print(f"Removed site-related items from {csv_path} (identified {len(removed_urls_set)} potential DB references).")

    # 2. Process DB
    if not os.path.exists(db_path):
        print(f"DB file {db_path} not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Safety: Even if CSV rows are gone, try to find site-related items in DB by site_name
    cursor.execute("SELECT urls FROM performers WHERE urls LIKE ?", (f'%{site_name}%',))
    for (p_urls_str,) in cursor.fetchall():
        if p_urls_str:
            for u in p_urls_str.split('|'):
                if site_name in u:
                    removed_urls_set.add(u.strip())

    if not removed_urls_set:
        print(f"No references to site '{site_name}' found in DB.")
        conn.close()
        return

    removed_count = 0
    performer_deleted_count = 0
    
    # To be efficient, we'll get all performers and process in Python
    cursor.execute("SELECT id, name, urls, crawls FROM performers")
    performers = cursor.fetchall()
    
    for p_id, p_name, p_urls_str, p_crawls in performers:
        if not p_urls_str:
            continue
            
        p_urls = [u.strip() for u in p_urls_str.split('|') if u.strip()]
        new_urls = [u for u in p_urls if u not in removed_urls_set]
        
        if len(new_urls) < len(p_urls):
            # This performer had some removed URLs
            diff = len(p_urls) - len(new_urls)
            removed_count += diff
            
            if not new_urls:
                # No URLs left, delete performer
                cursor.execute("DELETE FROM performers WHERE id = ?", (p_id,))
                performer_deleted_count += 1
            else:
                # Update performer
                new_urls_str = '|'.join(new_urls)
                new_crawls = max(0, p_crawls - diff)
                cursor.execute(
                    "UPDATE performers SET urls = ?, crawls = ?, last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_urls_str, new_crawls, p_id)
                )
    
    conn.commit()
    conn.close()
    
    print(f"Removed {removed_count} URL references from {db_path}.")
    if performer_deleted_count:
        print(f"Deleted {performer_deleted_count} performers with no remaining videos.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        remove_site_data(sys.argv[1])
    else:
        print("Usage: python remover.py <site_name>")
