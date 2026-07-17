"""
Refresh thumbnails for a performer by scraping their sxyprn page with Rodney.
Downloads fresh thumbnails and stores them locally under static/thumbnails/.
"""
import os, re, sqlite3, subprocess, sys, time
from io import BytesIO

DB_PATH = os.path.join(os.path.dirname(__file__), "performers.db")
THUMBS_DIR = os.path.join(os.path.dirname(__file__), "static", "thumbnails")
os.makedirs(THUMBS_DIR, exist_ok=True)

def refresh_performer_thumbs(performer_name):
    """Scrape sxyprn performer page, download fresh thumbnails."""
    from PIL import Image as PIL_Image
    
    slug = performer_name.replace(" ", "-").replace("'", "").replace(".", "")
    url = f"https://sxyprn.com/{slug}.html"
    print(f"  Opening {url} ...")
    
    # Start rodney
    subprocess.run(["rodney", "start"], capture_output=True, timeout=10)
    
    try:
        # Navigate
        subprocess.run(["rodney", "open", url], capture_output=True, timeout=15)
        time.sleep(5)  # Wait for JS to render
        
        # Get all thumbnails data-src attributes
        result = subprocess.run(
            ["rodney", "attr", ".mini_post_vid_thumb", "data-src"],
            capture_output=True, text=True, timeout=15
        )
        thumb_urls = result.stdout.strip().split("\n") if result.stdout.strip() else []
        
        # Also try getting the post IDs from the links
        result2 = subprocess.run(
            ["rodney", "attr", ".js-pop", "href"],
            capture_output=True, text=True, timeout=10
        )
        post_links = result2.stdout.strip().split("\n") if result2.stdout.strip() else []
        
    finally:
        subprocess.run(["rodney", "stop"], capture_output=True, timeout=10)
    
    if not thumb_urls or thumb_urls == ['']:
        print(f"  No thumbnails found for {performer_name}")
        return 0
    
    # Match post IDs to thumbnails
    post_ids = []
    for link in post_links:
        m = re.search(r'/post/([a-f0-9]+)', link)
        if m:
            post_ids.append(m.group(1))
    
    print(f"  Found {len(thumb_urls)} thumbnails, {len(post_ids)} post IDs")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    updated = 0
    
    for i, thumb_url in enumerate(thumb_urls):
        if not thumb_url or thumb_url == '':
            continue
        
        # Make URL absolute
        if thumb_url.startswith("//"):
            thumb_url = "https:" + thumb_url
        
        post_id = post_ids[i] if i < len(post_ids) else None
        
        # Download and save locally
        try:
            import requests
            resp = requests.get(thumb_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            
            fname = f"{post_id or i}.webp"
            local_path = os.path.join(THUMBS_DIR, fname)
            
            img = PIL_Image.open(BytesIO(resp.content))
            # Resize to thumbnail
            max_w = 120
            if img.width > max_w:
                ratio = max_w / img.width
                new_h = int(img.height * ratio)
                img = img.resize((max_w, new_h), PIL_Image.LANCZOS)
            img.save(local_path, "WEBP", quality=70)
            
            local_url = f"/static/thumbnails/{fname}"
            
            # Update DB - match by post_id or by performer
            if post_id:
                c.execute(
                    "UPDATE items SET thumbnail_url = ? WHERE item_url LIKE ?",
                    (local_url, f"%{post_id}%")
                )
                if c.rowcount > 0:
                    updated += c.rowcount
            
        except Exception as e:
            print(f"    Error downloading {thumb_url[:50]}: {e}")
    
    conn.commit()
    conn.close()
    print(f"  Updated {updated} items")
    return updated


if __name__ == "__main__":
    name = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Rebel Rhyder"
    refresh_performer_thumbs(name)
