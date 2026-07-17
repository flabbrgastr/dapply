"""
Extract and download video thumbnails from freshly scraped sxyprn HTML files.
CDN URLs expire within hours, so this must run immediately after scraping.
"""
import os
import re
import sqlite3
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from PIL import Image as PIL_Image
except ImportError:
    PIL_Image = None

import requests

DB_PATH = os.path.join(os.path.dirname(__file__), "performers.db")
THUMBS_DIR = os.path.join(os.path.dirname(__file__), "static", "thumbnails")
os.makedirs(THUMBS_DIR, exist_ok=True)

# Match the CDN thumbnail URL and the post ID from the HTML snippet
# Format: <a href="/post/{POST_ID}.html ...>...<img data-src='//.../{POST_ID}/small.jpg'...>
# or:  <video ... src='//.../{POST_ID}/vidthumb.mp4'...>
THUMB_RE = re.compile(
    r"""data-src=['"](//[^'"]*trafficdeposit[^'"]*small\.jpg)['"]"""
)
POST_RE = re.compile(r"""href=['"](/post/([a-f0-9]+)\.html)['"]""")
VIDEO_SRC_RE = re.compile(
    r"""src=['"](//[^'"]*trafficdeposit[^'"]*vidthumb\.mp4)['"]"""
)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Referer": "https://sxyprn.com/",
    "Accept": "image/webp,image/jpeg,image/*,*/*;q=0.8",
})


def extract_thumbs_from_file(html_path):
    """Extract (post_id, thumb_url, video_url) tuples from an HTML file."""
    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Find all post IDs
    # POST_RE captures (full_href, post_id)
    post_matches = POST_RE.findall(content)
    posts = [p[1] for p in post_matches]  # Extract post_id from tuple
    # Find all thumbnail URLs
    thumbs = THUMB_RE.findall(content)
    # Find all video URLs (fallback if small.jpg not found)
    videos = VIDEO_SRC_RE.findall(content)

    # Match post IDs to thumbnails (they appear in order, same as posts)
    results = []
    for i, post_id in enumerate(posts):
        thumb = thumbs[i] if i < len(thumbs) else ""
        video = videos[i] if i < len(videos) else ""
        if thumb or video:
            results.append((post_id, thumb, video))
    return results


def download_thumbnail(post_id, thumb_url):
    """Download a thumbnail and save as webp. Returns local path or None."""
    if not thumb_url:
        return None

    if thumb_url.startswith("//"):
        thumb_url = "https:" + thumb_url

    local_path = os.path.join(THUMBS_DIR, f"{post_id}.webp")
    if os.path.exists(local_path):
        return f"/static/thumbnails/{post_id}.webp"  # Already exists

    try:
        resp = session.get(thumb_url, timeout=10)
        resp.raise_for_status()

        if PIL_Image:
            img = PIL_Image.open(BytesIO(resp.content))
            # Resize to small thumbnail
            max_w = 160
            if img.width > max_w:
                ratio = max_w / img.width
                new_h = int(img.height * ratio)
                img = img.resize((max_w, new_h), PIL_Image.LANCZOS)
            img.save(local_path, "WEBP", quality=70)
        else:
            # Save as-is if PIL not available
            with open(local_path, "wb") as f:
                f.write(resp.content)

        return f"/static/thumbnails/{post_id}.webp"
    except Exception as e:
        # print(f"  Failed to download {post_id}: {e}")
        return None


def process_crawl(crawl_dir, workers=4, dry_run=False):
    """Process all sxyprn HTML files in a crawl directory."""
    sxyprn_dir = os.path.join(crawl_dir, "sxyprn")
    if not os.path.isdir(sxyprn_dir):
        return 0, 0

    html_files = sorted(f for f in os.listdir(sxyprn_dir) if f.endswith(".html"))
    if not html_files:
        return 0, 0

    print(f"  Processing {len(html_files)} files in {os.path.basename(crawl_dir)}/sxyprn/")

    all_thumbs = []
    for fname in html_files:
        fpath = os.path.join(sxyprn_dir, fname)
        results = extract_thumbs_from_file(fpath)
        all_thumbs.extend(results)

    if not all_thumbs:
        print(f"  No thumbnails found")
        return 0, 0

    print(f"  Found {len(all_thumbs)} thumbnails")

    if dry_run:
        return len(all_thumbs), 0

    # Download thumbnails
    downloaded = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(download_thumbnail, post_id, thumb_url): post_id
            for post_id, thumb_url, _ in all_thumbs
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                downloaded += 1

    print(f"  Downloaded {downloaded} thumbnails")

    # Update items table
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    updated = 0
    for post_id, thumb_url, _ in all_thumbs:
        local_path = f"/static/thumbnails/{post_id}.webp"
        if os.path.exists(os.path.join(THUMBS_DIR, f"{post_id}.webp")):
            c.execute(
                "UPDATE items SET thumbnail_url = ? WHERE item_url LIKE ?",
                (local_path, f"%{post_id}%"),
            )
            if c.rowcount:
                updated += c.rowcount

    conn.commit()
    conn.close()
    print(f"  Updated {updated} items in DB")
    return len(all_thumbs), downloaded


def process_latest_crawl(workers=4, dry_run=False):
    """Find and process the latest crawl directory."""
    scrapes_dir = os.path.join(os.path.dirname(__file__), "data", "scrapes")
    if not os.path.isdir(scrapes_dir):
        print("No data/scrapes directory")
        return

    crawls = sorted(
        [d for d in os.listdir(scrapes_dir) if d.startswith("crawl_")],
        reverse=True,
    )
    if not crawls:
        print("No crawl directories")
        return

    latest = os.path.join(scrapes_dir, crawls[0])
    print(f"Processing latest crawl: {crawls[0]}")
    return process_crawl(latest, workers=workers, dry_run=dry_run)


if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    workers = 8
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for arg in sys.argv[1:]:
        if arg.startswith("--workers="):
            workers = int(arg.split("=")[1])

    if args:
        crawl_dir = args[0]
        if not os.path.isdir(crawl_dir):
            crawl_dir = os.path.join(
                os.path.dirname(__file__), "data", "scrapes", crawl_dir
            )
        if os.path.isdir(crawl_dir):
            process_crawl(crawl_dir, workers=workers, dry_run=dry_run)
        else:
            print(f"Crawl directory not found: {crawl_dir}")
    else:
        process_latest_crawl(workers=workers, dry_run=dry_run)
