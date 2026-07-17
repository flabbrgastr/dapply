"""
Extract video thumbnails from analvids scene pages.
CDN URLs are stable (1-year cache), fetched from raw HTML (no JS needed).
"""
import os
import re
import sqlite3
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

DB_PATH = os.path.join(os.path.dirname(__file__), "performers.db")
THUMBS_DIR = os.path.join(os.path.dirname(__file__), "static", "thumbnails")
os.makedirs(THUMBS_DIR, exist_ok=True)

# Match analvids CDN image URLs in scene page HTML
CDN_IMAGE_RE = re.compile(r"cdn77-image\.gtflixtv\.com[^\"'\\s]+?\.jpg")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Referer": "https://www.analvids.com/",
})


def fetch_scene_thumbnail(scene_url: str) -> str | None:
    """
    Fetch an analvids scene page, extract the CDN thumbnail URL, and return it.
    Returns the CDN URL string, or None if not found.
    """
    resp = session.get(scene_url, timeout=15)
    resp.raise_for_status()
    match = CDN_IMAGE_RE.search(resp.text)
    if not match:
        return None
    return "https://" + match.group(0)


def download_thumbnail(cdn_url: str, local_name: str) -> str | None:
    """
    Download a CDN thumbnail and save as webp. Returns local URL path or None.
    Skips if already exists.
    """
    local_path = os.path.join(THUMBS_DIR, local_name)
    if os.path.exists(local_path):
        return f"/static/thumbnails/{local_name}"

    resp = session.get(cdn_url, timeout=15)
    resp.raise_for_status()

    try:
        from PIL import Image

        img = Image.open(BytesIO(resp.content))
        max_w = 120
        if img.width > max_w:
            ratio = max_w / img.width
            new_h = int(img.height * ratio)
            img = img.resize((max_w, new_h), Image.LANCZOS)
        img.save(local_path, "WEBP", quality=70)
    except ImportError:
        with open(local_path, "wb") as f:
            f.write(resp.content)

    return f"/static/thumbnails/{local_name}"


def process_scene(scene_id: int, performer_id: int, scene_url: str,
                  scene_title: str, performer_name: str) -> dict:
    """Process one scene: fetch page, extract CDN URL, download thumbnail."""
    vid_match = re.search(r"/watch/(\d+)", scene_url)
    vid_id = vid_match.group(1) if vid_match else str(scene_id)
    local_name = f"av_{vid_id}.webp"

    try:
        cdn_url = fetch_scene_thumbnail(scene_url)
        if not cdn_url:
            return {
                "ok": False,
                "reason": "no_cdn_url",
                "scene_id": scene_id,
                "vid_id": vid_id,
                "performer": performer_name,
            }

        local_path = download_thumbnail(cdn_url, local_name)
        if not local_path:
            return {
                "ok": False,
                "reason": "download_failed",
                "scene_id": scene_id,
                "vid_id": vid_id,
                "performer": performer_name,
            }

        return {
            "ok": True,
            "scene_id": scene_id,
            "vid_id": vid_id,
            "performer": performer_name,
            "local_path": local_path,
        }
    except Exception as e:
        return {
            "ok": False,
            "reason": f"{type(e).__name__}: {e}",
            "scene_id": scene_id,
            "vid_id": vid_id,
            "performer": performer_name,
        }


def run_batch(limit: int = 100, workers: int = 8):
    """Process N performer_scenes and download thumbnails."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT ps.id, ps.performer_id, ps.scene_url, ps.scene_title, p.name
        FROM performer_scenes ps
        JOIN performers p ON p.id = ps.performer_id
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    print(f"Processing {len(rows)} scenes with {workers} workers...")

    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(process_scene, *r): r for r in rows
        }
        for f in as_completed(futures):
            results.append(f.result())

    ok = [r for r in results if r["ok"]]
    no_url = [r for r in results if not r["ok"] and r["reason"] == "no_cdn_url"]
    errors = [r for r in results if not r["ok"] and r["reason"] != "no_cdn_url"]

    print(f"\nResults: {len(ok)} OK, {len(no_url)} no CDN URL, {len(errors)} errors")
    if ok:
        print(f"\nFirst {min(5, len(ok))} OK:")
        for r in ok[:5]:
            print(f"  #{r['vid_id']} {r['performer']}: {r['local_path']}")
    if errors:
        print(f"\nFirst {min(3, len(errors))} errors:")
        for r in errors[:3]:
            print(f"  #{r['vid_id']} {r['performer']}: {r['reason']}")

    total_size = sum(
        os.path.getsize(os.path.join(THUMBS_DIR, f"av_{r['vid_id']}.webp"))
        for r in ok
        if os.path.exists(os.path.join(THUMBS_DIR, f"av_{r['vid_id']}.webp"))
    )
    if ok:
        print(f"\nTotal size: {total_size / 1024:.0f} KB for {len(ok)} thumbs")

    return results


if __name__ == "__main__":
    import sys
    limit = 100
    workers = 8
    for arg in sys.argv[1:]:
        if arg.isdigit():
            limit = int(arg)
        elif arg.startswith("--workers="):
            workers = int(arg.split("=")[1])
    run_batch(limit=limit, workers=workers)
