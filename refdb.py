"""
Reference Database (refdb) for performer/model data from analvids.com.

Provides scraping, validation, and sync functions.
"""

import logging
import os
import random
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from io import BytesIO
from typing import Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

# ── Constants ──

DB_PATH = os.path.join(os.path.dirname(__file__), "performers.db")
from constants import USER_AGENTS
logger = logging.getLogger(__name__)
PER_PAGE = 12  # Models per directory page
TOTAL_PAGES = 660  # Approximate total directory pages
FETCH_DELAY = (2.0, 4.0)  # Min/max delay between profile fetches (seconds)
STALE_DAYS = 30  # Re-fetch profiles after this many days
STATIC_IMAGES_DIR = os.path.join(os.path.dirname(__file__), "static", "images")


def ensure_dirs():
    os.makedirs(STATIC_IMAGES_DIR, exist_ok=True)


def _ensure_tables(db_path: str = DB_PATH):
    """Ensure reference database tables exist."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS refdb_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            profile_url TEXT,
            scene_count INTEGER,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS refdb_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER REFERENCES refdb_models(id) ON DELETE CASCADE,
            nationality TEXT,
            age INTEGER,
            years_active TEXT,
            tags TEXT,
            scene_count INTEGER,
            last_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS refdb_scenes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER REFERENCES refdb_models(id) ON DELETE CASCADE,
            scene_url TEXT NOT NULL UNIQUE,
            scene_title TEXT,
            scene_date TEXT,
            added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS refdb_validated_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag TEXT NOT NULL,
            refdb_model_id INTEGER REFERENCES refdb_models(id) ON DELETE CASCADE,
            match_type TEXT DEFAULT 'manual',
            added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS performer_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            performer_id INTEGER,
            model_id INTEGER,
            image_url TEXT,
            local_path TEXT,
            type TEXT DEFAULT 'profile',
            added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


# ── URL Generation ──

def generate_directory_urls(
    base_url: str = "https://www.analvids.com/models",
    start_page: int = 1,
    end_page: int = TOTAL_PAGES,
) -> List[str]:
    """
    Generate URLs for the analvids model directory pages.
    """
    urls = []
    for page in range(start_page, end_page + 1):
        urls.append(f"{base_url}?page={page}")
    return urls


def generate_profile_url(model_id: int, slug: str) -> str:
    """Generate a profile URL for a model."""
    return f"https://www.analvids.com/model/{model_id}/{slug}"


# ── Directory Scraping ──

def _parse_directory_page(html: str) -> List[Dict]:
    """
    Parse a directory page and extract model info + thumbnail URLs.

    The HTML has a consistent pattern:
      model/ID/SLUG
      img src="...w=303..." alt
      model/ID/SLUG

    Returns list of {name, id, slug, profile_url, image_url}
    """
    results = []
    # Find all model/ID/SLUG + img pairs
    # Pattern: a model link followed by an image
    pattern = re.compile(
        r'model/(\d+)/([a-z0-9_-]+)[^<]*'
        r'<img[^>]*src="([^"]*cdn77[^"]*w=303[^"]*)"'
    )
    pairs = re.findall(pattern, html)

    for model_id, slug, image_url in pairs:
        profile_url = generate_profile_url(int(model_id), slug)
        results.append({
            "model_id": int(model_id),
            "slug": slug,
            "profile_url": profile_url,
            "image_url": image_url.replace("&amp;", "&"),
        })

    return results


def scrape_directory(
    db_path: str = DB_PATH,
    start_page: int = 1,
    end_page: int = TOTAL_PAGES,
    delay: float = 1.0,
):
    """
    Fetch and save model thumbnail images from the analvids directory pages
    into performer_images. (Population of refdb_models is handled by
    scrape_refdb_full.py, which is the canonical directory scraper.)

    Args:
        start_page: First page to scrape (1-indexed)
        end_page: Last page to scrape (inclusive)
        delay: Delay between requests (seconds)
    """
    ensure_dirs()
    _ensure_tables(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    urls = generate_directory_urls(start_page=start_page, end_page=end_page)

    total = len(urls)
    scraped = 0
    new_names = 0
    new_images = 0
    errors = 0

    logger.info(f'\n📋 Scraping {total} directory pages (page {start_page}-{end_page})...\n')

    for i, url in enumerate(urls, 1):
        page_num = start_page + i - 1
        logger.info(f'\r  [{i}/{total}] Page {page_num} ... ')
        sys.stdout.flush()

        try:
            ua = random.choice(USER_AGENTS)
            resp = requests.get(url, headers={"User-Agent": ua}, timeout=20)
            if resp.status_code != 200:
                logger.info(f'HTTP {resp.status_code}')
                errors += 1
                time.sleep(delay)
                continue

            html = resp.text

            # Extract thumbnails from directory page (refdb_models is populated
            # by scrape_refdb_full.py; this path only fetches thumbnail images).
            thumbnails = _parse_directory_page(html)
            for t in thumbnails:
                # Download and save thumbnail
                image_path = _save_thumbnail(t["model_id"], t["image_url"])
                if image_path:
                    # Record in DB
                    c.execute(
                        "INSERT OR IGNORE INTO performer_images (model_id, image_url, local_path, type) VALUES (?, ?, ?, ?)",
                        (t["model_id"], t["image_url"], image_path, "profile"),
                    )
                    if c.rowcount > 0:
                        new_images += 1

            scraped += 1
            conn.commit()

        except Exception as e:
            logger.info(f'Error: {e}')
            errors += 1

        time.sleep(delay)

    conn.close()
    logger.info(f'\n✅ Done: {scraped} pages, {new_names} new models, {new_images} new images, {errors} errors')


def _save_thumbnail(model_id: int, image_url: str) -> Optional[str]:
    """Download an image and save as a small webp thumbnail. Returns local path or None."""
    fname = f"{model_id}.webp"
    local_path = os.path.join(STATIC_IMAGES_DIR, fname)
    if os.path.exists(local_path):
        return f"/performers/static/images/{fname}"

    try:
        from PIL import Image as PIL_Image

        resp = requests.get(image_url, timeout=10, headers={"User-Agent": random.choice(USER_AGENTS)})
        if resp.status_code != 200:
            return None

        img = PIL_Image.open(BytesIO(resp.content))
        # Resize to max 300px width
        max_w = 300
        if img.width > max_w:
            ratio = max_w / img.width
            new_h = int(img.height * ratio)
            img = img.resize((max_w, new_h), PIL_Image.LANCZOS)

        img.save(local_path, "WEBP", quality=75)
        return f"/performers/static/images/{fname}"
    except Exception:
        return None


def fetch_all_images(
    db_path: str = DB_PATH,
    max_workers: int = 8,
    max_pages: Optional[int] = None,
):
    """
    Fetch images for all models from analvids directory pages.
    Uses concurrent requests for speed.
    Idempotent: skips models that already have images.
    """
    ensure_dirs()
    _ensure_tables(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Get models without images
    c.execute("""
        SELECT m.id, m.name, m.profile_url
        FROM refdb_models m
        LEFT JOIN performer_images pi ON pi.model_id = m.id
        WHERE pi.id IS NULL
    """)
    pending = c.fetchall()
    conn.close()

    total = len(pending)
    if total == 0:
        logger.info('✓ All models already have images.')
        return

    logger.info(f'\n📥 Fetching images for {total} models...')

    # Strategy: fetch directory pages which contain multiple model images
    # We need to know which page each model is on. Since models are alphabetical,
    # estimate page number.
    # Actually, let's just fetch directory pages 1..660 and extract all images.

    first_page = 1
    last_page = TOTAL_PAGES
    if max_pages:
        last_page = min(first_page + max_pages - 1, TOTAL_PAGES)

    pages_to_fetch = list(range(first_page, last_page + 1))
    logger.info(f'  Scanning {len(pages_to_fetch)} directory pages with {max_workers} workers...')

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    new_images = 0
    errors = 0

    def fetch_page(page_num: int) -> int:
        """Fetch one directory page and save thumbnails. Returns count of new images."""
        count = 0
        local_conn = None
        try:
            url = f"https://www.analvids.com/models?page={page_num}"
            ua = random.choice(USER_AGENTS)
            resp = requests.get(url, headers={"User-Agent": ua}, timeout=20)
            if resp.status_code != 200:
                return -1

            html = resp.text
            # Extract model_id + image_url pairs
            pairs = re.findall(
                r'model/(\d+)/([a-z0-9_-]+)[^<]*<img[^>]*src="([^"]*cdn77[^"]*w=303[^"]*)"',
                html
            )
            seen = set()
            for model_id_str, slug, img_url in pairs:
                mid = int(model_id_str)
                if mid in seen:
                    continue
                seen.add(mid)

                img_url_clean = img_url.replace('&amp;', '&')
                image_path = _save_thumbnail(mid, img_url_clean)
                if image_path:
                    local_conn = sqlite3.connect(db_path)
                    local_conn.execute(
                        "INSERT OR IGNORE INTO performer_images (model_id, image_url, local_path, type) VALUES (?, ?, ?, ?)",
                        (mid, img_url_clean, image_path, "profile"),
                    )
                    local_conn.commit()
                    local_conn.close()
                    local_conn = None
                    count += 1

            return count
        except Exception as e:
            if local_conn:
                try:
                    local_conn.close()
                except Exception:
                    pass
            return -1

    batch_size = max_workers * 2
    for batch_start in range(0, len(pages_to_fetch), batch_size):
        batch = pages_to_fetch[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(pages_to_fetch) + batch_size - 1) // batch_size
        logger.info(f'\r  Batch {batch_num}/{total_batches} (pages {batch[0]}-{batch[-1]}) ... ')

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_page, p): p for p in batch}
            for future in as_completed(futures):
                result = future.result()
                if result > 0:
                    new_images += result
                    conn.commit()
                elif result < 0:
                    errors += 1

        # Small delay between batches
        time.sleep(0.5)

    conn.close()
    logger.info(f'\n✅ Done: {new_images} new images, {errors} errors')
    logger.info(f"   Total images: {(new_images + conn.execute('SELECT COUNT(*) FROM performer_images').fetchone()[0] if False else '? (reconnect needed)')}")


# ── Profile Scraping ──

def _scrape_profile(url: str) -> Optional[Dict]:
    """
    Scrape an analvids performer profile page.

    Returns dict with nationality, age, years_active, tags, scenes,
    or None on error.
    """
    for attempt in range(2):
        try:
            ua = random.choice(USER_AGENTS)
            resp = requests.get(url, headers={"User-Agent": ua}, timeout=20)
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                time.sleep(random.uniform(2, 4))
                continue
            break
        except requests.RequestException:
            time.sleep(random.uniform(2, 4))
            continue
    else:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    body = soup.get_text(separator="\n")

    # Nationality
    nationality = ""
    m = re.search(r'Nationality\s*:\s*(\w+)', body)
    if m:
        nationality = m.group(1)

    # Age
    age = None
    m = re.search(r'Age\s*:\s*(\d+)', body)
    if m:
        age = int(m.group(1))

    # Years active
    years_active = ""
    m = re.search(r'Years\s*active\s*:\s*(.+)', body)
    if m:
        years_active = m.group(1).strip()

    # Tags
    tags = []
    tag_section = re.search(r'Tags\s*:(.*?)(?:Nationality|Age|Years active|$)', body, re.DOTALL)
    if tag_section:
        raw = tag_section.group(1)
        tags = [t.strip() for t in raw.split(",") if t.strip()]

    # Scene count from profile
    scenes = None
    m = re.search(r'Total\s+scenes?\s*:?\s*(\d+)', body, re.IGNORECASE)
    if m:
        scenes = int(m.group(1))

    return {
        "nationality": nationality,
        "age": age,
        "years_active": years_active,
        "tags": tags,
        "scene_count": scenes,
    }


def fetch_profiles(db_path: str = DB_PATH, max_profiles: Optional[int] = None,
                   stale_days: int = STALE_DAYS):
    """
    Fetch/update profile details for all models in refdb_models.
    Only fetches profiles that are stale (older than stale_days) or missing.

    Args:
        max_profiles: Limit number of profiles to fetch (for testing)
        stale_days: Re-fetch after this many days
    """
    ensure_dirs()
    _ensure_tables(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Get models needing profiles (new or stale)
    cutoff = (datetime.now() - timedelta(days=stale_days)).isoformat()
    c.execute("""
        SELECT m.id, m.name, m.profile_url
        FROM refdb_models m
        LEFT JOIN refdb_profiles p ON p.model_id = m.id
        WHERE (p.model_id IS NULL OR p.last_scraped < ?)
          AND m.profile_url != ''
        ORDER BY m.name
    """, (cutoff,))
    pending = c.fetchall()
    conn.close()

    total = len(pending)
    if total == 0:
        logger.info('✓ All profiles are current (< 30 days old).')
        return

    if max_profiles:
        pending = pending[:max_profiles]

    logger.info(f'\n📥 Fetching {len(pending)}/{total} profiles (delay {FETCH_DELAY[0]}-{FETCH_DELAY[1]}s)...\n')

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    scraped = 0
    errors = 0

    for i, (model_id, name, url) in enumerate(pending, 1):
        logger.info(f'  [{i}/{len(pending)}] {name} ... ')

        data = _scrape_profile(url)
        if data is None:
            logger.info('❌ (profile not found)')
            errors += 1
            time.sleep(random.uniform(*FETCH_DELAY))
            continue

        # Upsert profile
        c.execute("""
            INSERT INTO refdb_profiles (model_id, nationality, age, years_active, tags, scene_count, last_scraped)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(model_id) DO UPDATE SET
                nationality = excluded.nationality,
                age = excluded.age,
                years_active = excluded.years_active,
                tags = excluded.tags,
                scene_count = excluded.scene_count,
                last_scraped = CURRENT_TIMESTAMP
        """, (
            model_id,
            data["nationality"],
            data["age"],
            data["years_active"],
            ", ".join(data["tags"]),
            data["scene_count"],
        ))
        conn.commit()

        age_str = str(data['age']) if data['age'] is not None else '?'
        yrs = f" ({data['years_active']})" if data['years_active'] else ""
        logger.info(f"✓ {data['nationality']:12s} age={age_str:>2s}{yrs}  {len(data['tags'])} tags, {data['scene_count']} scenes")

        scraped += 1
        if i < len(pending):
            time.sleep(random.uniform(*FETCH_DELAY))

    conn.close()
    logger.info(f'\n✅ {scraped} profiles fetched, {errors} errors')


# ── Validation ──

def _load_known_names(db_path: str = DB_PATH) -> Tuple[Set[str], Dict[str, int]]:
    """
    Load all known performer names from refdb_models.
    Returns (exact_names_set, {lowercase_name: id}).
    """
    _ensure_tables(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, name FROM refdb_models")
    exact = set()
    lower_map = {}
    for mid, name in c.fetchall():
        exact.add(name)
        lower_map[name.lower()] = mid
    conn.close()
    return exact, lower_map


def validate_name(name: str, threshold: int = 88) -> Tuple[bool, Optional[str], str]:
    """
    Validate a potential performer name against the reference DB.

    Uses fuzzy matching (rapidfuzz token_sort_ratio) to handle variations.

    Args:
        name: The name to validate (e.g., data-subkey from sxyprn)
        threshold: Fuzzy match cutoff (0-100, default 88)

    Returns:
        (is_valid, matched_name, match_type) where match_type is
        'exact', 'fuzzy', or 'none'
    """
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        # Fallback: simple exact match
        exact, _ = _load_known_names()
        if name in exact:
            return True, name, 'exact'
        return False, None, 'none'

    exact, lower_map = _load_known_names()

    if name in exact:
        return True, name, 'exact'

    lower_name = name.lower()
    if lower_name in lower_map:
        return True, next(n for n in exact if n.lower() == lower_name), 'exact'

    # Fuzzy match against all known names
    all_names = list(exact)
    result = process.extractOne(name, all_names, scorer=fuzz.token_sort_ratio, score_cutoff=threshold)
    if result:
        matched_name, score = result[0], result[1]
        return True, matched_name, 'fuzzy'

    return False, None, 'none'


# ── Sync to Performers Table ──

def sync_to_performers(db_path: str = DB_PATH):
    """
    Sync refdb_models into the main performers table.
    This adds validated = 1 entries for all analvids models.
    """
    from dbadd import add_performers_from_items

    ensure_dirs()
    _ensure_tables(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Get all refdb models NOT yet in performers as validated
    c.execute("""
        SELECT m.name, m.profile_url, m.scene_count
        FROM refdb_models m
        LEFT JOIN performers p ON LOWER(p.name) = LOWER(m.name) AND p.validated = 1
        WHERE p.id IS NULL
    """)
    new_models = c.fetchall()
    conn.close()

    if not new_models:
        logger.info('✓ All refdb models already synced to performers.')
        return

    logger.info(f'\n🔄 Syncing {len(new_models)} new models to performers table...')

    # Build items list
    items = []
    for name, url, sc in new_models:
        items.append({
            "item_url": url or "",
            "title": f"Model: {name}",
            "performers": name,
            "item_date": "",
            "hits": str(sc) if sc else "0",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
        })

    sync_count = add_performers_from_items(items)
    logger.info(f'✅ Synced {sync_count} performers')


# ── Stats ──

def show_stats(db_path: str = DB_PATH):
    """Display statistics about the reference database."""
    ensure_dirs()
    _ensure_tables(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    logger.info('\n📊 Reference Database Stats')
    logger.info('=' * 50)

    c.execute("SELECT COUNT(*) FROM refdb_models")
    logger.info(f'  Models in directory:   {c.fetchone()[0]:>6}')

    c.execute("SELECT COUNT(*) FROM refdb_profiles")
    logger.info(f'  Profiles scraped:      {c.fetchone()[0]:>6}')

    c.execute("SELECT COUNT(*) FROM refdb_scenes")
    logger.info(f'  Scenes indexed:        {c.fetchone()[0]:>6}')

    c.execute("SELECT COUNT(*) FROM refdb_validated_tags")
    logger.info(f'  Validated tags:        {c.fetchone()[0]:>6}')

    c.execute("SELECT COUNT(*) FROM performer_images")
    logger.info(f'  Images stored:         {c.fetchone()[0]:>6}')

    # Nationality distribution
    c.execute("""
        SELECT nationality, COUNT(*) as cnt
        FROM refdb_profiles
        WHERE nationality != ''
        GROUP BY nationality
        ORDER BY cnt DESC
        LIMIT 10
    """)
    logger.info(f'\n  Top nationalities:')
    for nat, cnt in c.fetchall():
        logger.info(f'    {nat:20s} {cnt:>4d}')

    # Age distribution
    c.execute("""
        SELECT
            CASE
                WHEN age < 20 THEN 'under 20'
                WHEN age BETWEEN 20 AND 24 THEN '20-24'
                WHEN age BETWEEN 25 AND 29 THEN '25-29'
                WHEN age BETWEEN 30 AND 34 THEN '30-34'
                WHEN age BETWEEN 35 AND 39 THEN '35-39'
                WHEN age >= 40 THEN '40+'
            END as age_group,
            COUNT(*) as cnt
        FROM refdb_profiles
        WHERE age IS NOT NULL
        GROUP BY age_group
        ORDER BY age_group
    """)
    logger.info(f'\n  Age distribution:')
    for grp, cnt in c.fetchall():
        logger.info(f'    {grp:12s} {cnt:>4d}')

    # Sync status
    c.execute("""
        SELECT COUNT(*) FROM refdb_models m
        LEFT JOIN performers p ON LOWER(p.name) = LOWER(m.name) AND p.validated = 1
        WHERE p.id IS NULL
    """)
    not_synced = c.fetchone()[0]
    logger.info(f'\n  Not yet synced to performers: {not_synced}')

    # Images on disk
    img_count = len([f for f in os.listdir(STATIC_IMAGES_DIR) if f.endswith('.webp')])
    logger.info(f'  Image files on disk:   {img_count:>6}')

    conn.close()


# ── CLI ──

def main():
    help_text = """
Usage: uv run python refdb.py [COMMAND]

Commands:
  --fetch-images       Fetch thumbnails from directory pages (batch)
  --fetch-profiles     Fetch detailed profiles for all models
  --sync               Sync refdb models into main performers table
  --stats              Show refdb statistics
  --scrape-dir         Scrape model directory (add --pages=1-10 to limit)
  --build              Full build: scrape + profiles + sync
"""
    if len(sys.argv) < 2 or "--help" in sys.argv or "-h" in sys.argv:
        logger.info(help_text)
        return

    if "--fetch-images" in sys.argv:
        max_pages = None
        max_workers = 8
        for i, a in enumerate(sys.argv):
            if a.startswith("--max-pages="):
                max_pages = int(a.split("=")[1])
            if a.startswith("--workers="):
                max_workers = int(a.split("=")[1])
        fetch_all_images(max_pages=max_pages, max_workers=max_workers)
    elif "--build" in sys.argv:
        scrape_directory()
        fetch_profiles()
        sync_to_performers()
    elif "--fetch-profiles" in sys.argv:
        max_p = None
        for i, a in enumerate(sys.argv):
            if a.startswith("--max="):
                max_p = int(a.split("=")[1])
        fetch_profiles(max_profiles=max_p)
    elif "--stats" in sys.argv:
        show_stats()
    elif "--sync" in sys.argv:
        sync_to_performers()
    elif "--scrape-dir" in sys.argv:
        start = 1
        end = TOTAL_PAGES
        for i, a in enumerate(sys.argv):
            if a.startswith("--pages="):
                parts = a.split("=")[1].split("-")
                start = int(parts[0])
                end = int(parts[-1])
        scrape_directory(start_page=start, end_page=end)
    else:
        logger.info(help_text)


from logutils import setup_logging

if __name__ == "__main__":
    setup_logging(level=logging.WARNING)
    ensure_dirs()
    main()
