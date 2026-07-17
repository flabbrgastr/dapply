"""
Extract thumbnail URLs from scraped sxyprn HTML files and store in items table.
"""
import os, re, sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "performers.db")
SCRAPES_DIR = os.path.join(os.path.dirname(__file__), "data", "scrapes")

def extract_thumbnails():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Add thumbnail_url column if missing
    try:
        c.execute("ALTER TABLE items ADD COLUMN thumbnail_url TEXT")
        conn.commit()
        print("Added thumbnail_url column")
    except sqlite3.OperationalError:
        pass  # already exists
    
    # Get all items with a source file and no thumbnail yet
    items = c.execute(
        "SELECT id, item_url, source_file FROM items WHERE source_file IS NOT NULL AND source_file != '' AND (thumbnail_url IS NULL OR thumbnail_url = '')"
    ).fetchall()
    
    total = len(items)
    found = 0
    errors = 0
    cache = {}  # source_file -> thumbnails dict
    
    for i, (item_id, item_url, source_file) in enumerate(items):
        if i % 1000 == 0:
            print(f"  [{i}/{total}] ...")
        
        # Extract post ID from URL (e.g., /post/696dc7c045138.html)
        m = re.search(r'/post/([a-f0-9]+)', item_url)
        if not m:
            errors += 1
            continue
        post_id = m.group(1)
        
        full_path = os.path.join(os.path.dirname(__file__), source_file)
        if not os.path.exists(full_path):
            errors += 1
            continue
        
        # Cache parsed thumbnails per source file
        if source_file not in cache:
            try:
                with open(full_path, 'r', errors='ignore') as f:
                    html = f.read()
                thumbs = re.findall(
                    r'(https?:)?//([^"\']*vidthumb\.(?:mp4|jpg|png))',
                    html
                )
                cache[source_file] = {
                    re.search(r'/([a-f0-9]+)/vidthumb', t[1]).group(1): f"https://{t[1]}"
                    for t in thumbs
                    if re.search(r'/([a-f0-9]+)/vidthumb', t[1])
                }
            except Exception:
                cache[source_file] = {}
        
        thumb_url = cache[source_file].get(post_id)
        if thumb_url:
            c.execute("UPDATE items SET thumbnail_url = ? WHERE id = ?", (thumb_url, item_id))
            found += 1
        else:
            errors += 1
    
    conn.commit()
    conn.close()
    print(f"\nDone: {found} thumbnails found, {errors} missing, {total} total")

if __name__ == "__main__":
    extract_thumbnails()
