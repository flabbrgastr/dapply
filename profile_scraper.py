"""
Profile Scraper — crawlt einzelne Performer-Profilseiten von analvids.com.

Extrahiert:
  - Nationalität, Alter
  - Tags (Haarfarbe, Augen, Body-Typ, etc.)
  - Scene-Liste (für Co-Performer-Analyse)
  - AKA-Namen (aus unserer DB)

Nutzung:
  uv run python orchestator.py --fetch-profiles           # alle neuen
  uv run python orchestator.py --fetch-profiles --max-profiles 5  # nur 5
"""

import logging
import random
import re
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
DELAY_RANGE = (4.0, 10.0)
STALE_DAYS = 30  # Re-crawl after 30 days


def _ensure_tables(db_path: str):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS performer_features (
            performer_id INTEGER PRIMARY KEY,
            nationality TEXT DEFAULT '',
            age INTEGER DEFAULT NULL,
            tags TEXT DEFAULT '',
            scene_count INTEGER DEFAULT 0,
            last_scraped TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (performer_id) REFERENCES performers(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS performer_scenes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            performer_id INTEGER,
            scene_url TEXT,
            scene_title TEXT,
            FOREIGN KEY (performer_id) REFERENCES performers(id)
        )
    """)
    conn.commit()
    conn.close()


def get_pending_profiles(db_path: str, stale_days: int = STALE_DAYS) -> List[Dict]:
    """Get validated performers whose profile is new or stale."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=stale_days)).isoformat()
    c.execute("""
        SELECT p.id, p.name, i.item_url
        FROM performers p
        JOIN items i ON i.performer_id = p.id AND i.title LIKE 'Model: %'
        WHERE p.validated = 1
          AND i.item_url LIKE '%analvids.com/model/%'
          AND (
            p.id NOT IN (SELECT performer_id FROM performer_features)
            OR (
              SELECT last_scraped FROM performer_features
              WHERE performer_id = p.id
            ) < ?
          )
        GROUP BY p.id
        ORDER BY p.name
    """, (cutoff,))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "url": r[2]} for r in rows]


def _scrape_profile(url: str) -> Optional[Dict]:
    """
    Scrape performer profile page.

    Returns dict with nationality, age, tags, scenes, or None on error.
    """
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            timeout=20,
        )
        if resp.status_code != 200:
            logger.warning(f"HTTP {resp.status_code} for {url}")
            return None
    except requests.RequestException as e:
        logger.error(f"Request failed for {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    body_text = soup.get_text()

    # Nationality + Age from body text (text is continuous, no spaces between fields)
    nationality = ""
    age = None
    nat_match = re.search(r'Nationality\s*:\s*([A-Za-z]+?)(?=Age|$)', body_text)
    if nat_match:
        nationality = nat_match.group(1).strip()
    age_match = re.search(r'Age\s*:\s*(\d+)', body_text)
    if age_match:
        age = int(age_match.group(1))

    # Tags from <td class="model__tags">
    tags = []
    tag_td = soup.select_one("td.model__tags")
    if tag_td:
        for a in tag_td.find_all("a"):
            t = a.get_text(strip=True)
            if t:
                tags.append(t)
    else:
        # Fallback: extract from body text after "Tags:"
        tags_section = re.search(r'Tags\s*:\s*(.+?)(?:\nSCENES|\n\n|\Z)', body_text, re.DOTALL)
        if tags_section:
            raw = tags_section.group(1)
            tags = [t.strip() for t in re.split(r',\s*', raw) if t.strip()]

    # Scene cards
    scenes = []
    scene_links = soup.select("a[href*='/watch/']")
    seen_urls = set()
    for a in scene_links:
        href = a.get("href", "")
        title = a.get("title") or a.get_text(strip=True)
        if href and title and href not in seen_urls:
            full_url = href if href.startswith("http") else f"https://www.analvids.com{href}"
            scenes.append({"url": full_url, "title": title})
            seen_urls.add(href)

    return {
        "nationality": nationality,
        "age": age,
        "tags": tags,
        "scenes": scenes,
        "scene_count": len(scenes),
    }


def fetch_profiles(
    db_path: str = "performers.db",
    delay_range: tuple = DELAY_RANGE,
    max_profiles: Optional[int] = None,
):
    """
    Crawl performer profile pages slowly in background.

    Args:
        db_path: Path to SQLite DB
        delay_range: (min, max) random delay
        max_profiles: Limit (None = all)
    """
    _ensure_tables(db_path)
    profiles = get_pending_profiles(db_path)
    total = len(profiles)

    if total == 0:
        print("✓ Alle Performer-Profile sind aktuell (jünger als 30 Tage).")
        return

    if max_profiles:
        profiles = profiles[:max_profiles]

    print(f"📥 Scrape {len(profiles)}/{total} Performer-Profile...")
    print(f"   (Verzögerung {delay_range[0]}-{delay_range[1]}s zufällig)\n")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    scraped = 0
    errors = 0

    for i, prof in enumerate(profiles, 1):
        print(f"  [{i}/{len(profiles)}] {prof['name']} ... ", end="", flush=True)

        data = _scrape_profile(prof["url"])
        if data is None:
            print("❌")
            errors += 1
            time.sleep(random.uniform(*delay_range))
            continue

        tags_str = ", ".join(data["tags"])
        c.execute("""
            INSERT OR REPLACE INTO performer_features
            (performer_id, nationality, age, tags, scene_count, last_scraped)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (prof["id"], data["nationality"], data["age"], tags_str, data["scene_count"]))

        # Save scenes
        c.execute("DELETE FROM performer_scenes WHERE performer_id = ?", (prof["id"],))
        for scene in data["scenes"]:
            c.execute("""
                INSERT INTO performer_scenes (performer_id, scene_url, scene_title)
                VALUES (?, ?, ?)
            """, (prof["id"], scene["url"], scene["title"]))

        conn.commit()
        scraped += 1

        # Compact line
        age_str = str(data['age']) if data['age'] is not None else "?"
        print(f"✓ {data['nationality']:12s} {age_str:>2s}  ({len(data['tags'])} tags, {data['scene_count']} scenes)")

        if i < len(profiles):
            time.sleep(random.uniform(*delay_range))

    conn.close()

    # Summary
    if scraped:
        print(f"\n✅ {scraped} Profile gescraped, {errors} Fehler")
        print(f"   Daten in performer_features + performer_scenes Tabellen.")


if __name__ == "__main__":
    fetch_profiles()
