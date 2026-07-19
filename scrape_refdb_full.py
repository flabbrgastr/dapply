"""
Full analvids model directory scraper.

Scrapes all directory pages (1-N) and extracts every model name + slug + ID + nationality.
Populates refdb_models with the complete set.

Usage:
    uv run python scrape_refdb_full.py [--pages=1-600] [--delay=1.0]
"""

import os
import re
import sys
import time
import sqlite3
import random
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

import requests
from bs4 import BeautifulSoup

DB_PATH = os.path.join(os.path.dirname(__file__), "performers.db")
from constants import USER_AGENTS


def _ensure_tables(db_path: str = DB_PATH):
    """Ensure refdb tables exist."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS refdb_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            profile_url TEXT,
            scene_count INTEGER DEFAULT 0,
            nationality TEXT DEFAULT '',
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        -- Add nationality column if missing (migration)
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
        CREATE TABLE IF NOT EXISTS refdb_validated_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag TEXT NOT NULL,
            refdb_model_id INTEGER REFERENCES refdb_models(id) ON DELETE CASCADE,
            match_type TEXT DEFAULT 'manual',
            added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Check if nationality column exists
    cols = [r[1] for r in c.execute("PRAGMA table_info(refdb_models)").fetchall()]
    if 'nationality' not in cols:
        c.execute("ALTER TABLE refdb_models ADD COLUMN nationality TEXT DEFAULT ''")
    if 'scene_count' not in cols:
        c.execute("ALTER TABLE refdb_models ADD COLUMN scene_count INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


def parse_page(html: str) -> List[Dict]:
    """
    Parse a directory page and extract ALL model entries.

    Each model appears as a model-top card with:
      - model-top__name: the model's name
      - A link to /model/ID/slug
      - A flag image showing nationality
      - A scene count
      - A scene thumbnail (latest scene)

    Returns list of {name, model_id, slug, profile_url, nationality, scene_count}
    """
    soup = BeautifulSoup(html, 'html.parser')
    results = []

    # Find all model name elements
    name_elems = soup.find_all(class_='model-top__name')
    if not name_elems:
        # Fallback: find all model-top divs
        tops = soup.find_all('div', class_='model-top')
        name_elems = []
        for top in tops:
            name_elem = top.find(class_='model-top__name')
            if name_elem:
                name_elems.append(name_elem)

    for name_elem in name_elems:
        name = name_elem.get_text(strip=True)
        if not name:
            continue

        # Find the parent model-top and its link
        model_top = name_elem.find_parent('div', class_='model-top')
        if not model_top:
            continue

        # Get model link: /model/ID/slug
        link = model_top.find('a', class_='model-top__img')
        href = link.get('href', '') if link else ''
        m = re.search(r'/model/(\d+)/([a-z0-9_-]+)', href)
        if not m:
            continue

        model_id = int(m.group(1))
        slug = m.group(2)
        profile_url = f"https://www.analvids.com/model/{model_id}/{slug}"

        # Get nationality from flag image
        nationality = ''
        flag_img = model_top.find('img', src=re.compile(r'flags/'))
        if flag_img:
            src = flag_img.get('src', '')
            flag_m = re.search(r'flags/([a-z]{2})\.png', src)
            if flag_m:
                nationality = flag_m.group(1).upper()

        # Get scene count
        scene_count = 0
        scene_elem = model_top.find(class_='model-top__scene')
        if scene_elem:
            sc_m = re.search(r'(\d+)', scene_elem.get_text())
            if sc_m:
                scene_count = int(sc_m.group(1))

        results.append({
            'name': name,
            'model_id': model_id,
            'slug': slug,
            'profile_url': profile_url,
            'nationality': nationality,
            'scene_count': scene_count,
        })

    return results


def scrape_directory_range(start_page: int = 1, end_page: int = 600,
                           delay: float = 1.0, db_path: str = DB_PATH) -> Tuple[int, int, int]:
    """
    Scrape a range of directory pages and store results in refdb_models.

    Returns (new_models, updated_models, errors)
    """
    _ensure_tables(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Count existing
    c.execute('SELECT COUNT(*) FROM refdb_models')
    before = c.fetchone()[0]
    c.execute('SELECT MIN(discovered_at) FROM refdb_models')
    discovered_since = c.fetchone()[0]

    new_models = 0
    updated_models = 0
    errors = 0
    total_pages = end_page - start_page + 1

    print(f"\n📋 Scraping pages {start_page}-{end_page} ({total_pages} pages, ~{delay}s delay)...")
    print(f"   Existing refdb models: {before}")

    for page in range(start_page, end_page + 1):
        url = f"https://www.analvids.com/models?page={page}"
        page_num = page - start_page + 1

        try:
            ua = random.choice(USER_AGENTS)
            resp = requests.get(url, headers={"User-Agent": ua}, timeout=30)

            if resp.status_code != 200:
                print(f"\r  [{page_num}/{total_pages}] Page {page}: HTTP {resp.status_code}     ")
                errors += 1
                time.sleep(delay)
                continue

            models = parse_page(resp.text)
            now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

            page_new = 0
            page_upd = 0
            for m in models:
                c.execute("""
                    INSERT INTO refdb_models (name, profile_url, scene_count, nationality, discovered_at, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        profile_url = CASE WHEN refdb_models.profile_url = '' OR refdb_models.profile_url IS NULL
                            THEN excluded.profile_url ELSE refdb_models.profile_url END,
                        scene_count = excluded.scene_count,
                        nationality = CASE WHEN refdb_models.nationality = '' OR refdb_models.nationality IS NULL
                            THEN excluded.nationality ELSE refdb_models.nationality END,
                        last_updated = excluded.last_updated
                """, (m['name'], m['profile_url'], m['scene_count'], m['nationality'], now, now))

                if c.rowcount == 1:
                    page_new += 1
                elif c.rowcount == 0:
                    # Check if it was an update (not insert)
                    page_upd += 1

            conn.commit()
            new_models += page_new
            updated_models += page_upd

            # Progress
            total = before + new_models
            sys.stdout.write(f"\r  [{page_num}/{total_pages}] Page {page}: {len(models)} models "
                           f"(+{page_new} new, ~{page_upd} upd) → {total} total   ")
            sys.stdout.flush()

        except requests.RequestException as e:
            print(f"\r  [{page_num}/{total_pages}] Page {page}: Error: {e}                        ")
            errors += 1
        except Exception as e:
            print(f"\r  [{page_num}/{total_pages}] Page {page}: Parse error: {e}                  ")
            errors += 1

        time.sleep(delay)

    c.execute('SELECT COUNT(*) FROM refdb_models')
    after = c.fetchone()[0]
    conn.close()

    print(f"\n✅ Done: {total_pages} pages, +{after - before} net new models, "
          f"{new_models} inserts, {updated_models} updates, {errors} errors")
    print(f"   Total refdb models: {after}")
    return new_models, updated_models, errors


def find_last_page(start: int = 600) -> int:
    """Binary search to find the last directory page with models."""
    session = requests.Session()
    session.headers.update({'User-Agent': random.choice(USER_AGENTS)})

    def has_models(page: int) -> bool:
        try:
            r = session.get(f'https://www.analvids.com/models?page={page}', timeout=15)
            if r.status_code != 200:
                return False
            return len(re.findall(r'class="model-top__name"', r.text)) > 0
        except Exception:
            return False

    print(f"Binary searching for last page (starting from {start})...")
    
    # First find an upper bound
    upper = start
    while has_models(upper):
        print(f"  Page {upper}: has models")
        upper *= 2
        if upper > 2000:
            print(f"  Reached {upper}, stopping search")
            break
    
    # But we also need to check the starting point
    if not has_models(start):
        # Search down
        lo, hi = 1, start - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if has_models(mid):
                lo = mid
            else:
                hi = mid - 1
        print(f"  Last page with models: {lo}")
        return lo
    
    # Search up
    lo, hi = start, upper
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if has_models(mid):
            lo = mid
        else:
            hi = mid - 1
    
    print(f"  Last page with models: {lo}")
    return lo


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Scrape full analvids model directory')
    parser.add_argument('--pages', default='1-600', help='Page range to scrape (e.g. 1-600)')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay between requests (seconds)')
    parser.add_argument('--find-last', action='store_true', help='Find the last directory page')
    parser.add_argument('--dry-run', action='store_true', help='Parse pages without saving to DB')
    args = parser.parse_args()

    if args.find_last:
        last = find_last_page(int(args.pages.split('-')[0]) if '-' in args.pages else int(args.pages))
        print(f"Last page: {last}")
        return

    # Parse range
    if '-' in args.pages:
        start, end = map(int, args.pages.split('-'))
    else:
        start = int(args.pages)
        end = start

    if args.dry_run:
        # Just test one page
        url = f"https://www.analvids.com/models?page={start}"
        r = requests.get(url, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=30)
        models = parse_page(r.text)
        print(f"Page {start}: {len(models)} models")
        for m in models[:10]:
            print(f"  {m['name']:30s} {m['nationality']:4s} {m['scene_count']:4d} {m['slug']}")
        return

    scrape_directory_range(start, end, delay=args.delay)


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    main()