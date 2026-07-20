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
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from performer_repository import SqlitePerformerRepository

logger = logging.getLogger(__name__)

from constants import USER_AGENTS
DELAY_RANGE = (4.0, 10.0)
STALE_DAYS = 30  # Re-crawl after 30 days
MAX_RETRIES = 2


def _scrape_profile(url: str) -> Optional[Dict]:
    """
    Scrape performer profile page.

    Returns dict with nationality, age, tags, scenes, or None on error.
    """
    for attempt in range(MAX_RETRIES):
        try:
            ua = random.choice(USER_AGENTS)
            resp = requests.get(
                url,
                headers={"User-Agent": ua, "Accept": "text/html"},
                timeout=20,
            )
            if resp.status_code == 404:
                logger.warning(f"HTTP 404 (deleted profile) for {url}")
                return None
            if resp.status_code != 200:
                logger.warning(f"HTTP {resp.status_code} for {url} (attempt {attempt+1}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(random.uniform(2, 5))
                    continue
                return None
            break
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(random.uniform(2, 5))
                continue
            return None
    else:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    body_text = soup.get_text()

    # Nationality + Age from body text
    nationality = ""
    age = None
    nat_match = re.search(r'Nationality\s*:\s*([A-Za-z]+?)(?=Age|$)', body_text)
    if nat_match:
        nationality = nat_match.group(1).strip()
    age_match = re.search(r'Age\s*:\s*(\d+)', body_text)
    if age_match:
        age = int(age_match.group(1))

    # AKA / Also known as
    akas = []
    aka_match = re.search(r"Also known as:\s*([A-Za-z0-9,\.\s\-]+?)(?=Tags|$)", body_text)
    if aka_match:
        aka_raw = aka_match.group(1).strip()
        akas = [a.strip() for a in aka_raw.split(',') if a.strip()]

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

    # Deduplicate scenes by URL
    seen_urls = set()
    unique_scenes = []
    for s in scenes:
        if s["url"] not in seen_urls:
            seen_urls.add(s["url"])
            unique_scenes.append(s)

    return {
        "nationality": nationality,
        "age": age,
        "tags": tags,
        "scenes": unique_scenes,
        "scene_count": len(unique_scenes),
        "akas": akas,
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
    repo = SqlitePerformerRepository(db_path)
    profiles = repo.get_profiles_needing_scrape()
    total = len(profiles)

    if total == 0:
        logger.info('✓ Alle Performer-Profile sind aktuell (jünger als 30 Tage).')
        return

    if max_profiles:
        profiles = profiles[:max_profiles]

    logger.info(f'📥 Scrape {len(profiles)}/{total} Performer-Profile...')
    logger.info(f'   (Verzögerung {delay_range[0]}-{delay_range[1]}s zufällig)\n')

    scraped = 0
    errors = 0

    for i, prof in enumerate(profiles, 1):
        logger.info(f"  [{i}/{len(profiles)}] {prof['name']} ... ")

        data = _scrape_profile(prof["url"])
        if data is None:
            logger.info('❌')
            errors += 1
            time.sleep(random.uniform(*delay_range))
            continue

        # Save features
        tags_str = ", ".join(data["tags"])
        repo.upsert_features(
            prof["id"],
            nationality=data["nationality"],
            age=data["age"],
            tags=tags_str,
            scene_count=data["scene_count"],
        )

        # Merge AKAs into performers table
        if data["akas"]:
            current = repo.get_by_id(prof["id"])
            existing_aka = (current.get("aka") or "") if current else ""
            canonical_name = current["name"] if current else prof["name"]

            new_akas = []
            for aka in data["akas"]:
                if aka.lower() != canonical_name.lower() and aka.lower() not in existing_aka.lower():
                    new_akas.append(aka)

            if new_akas:
                merged = (existing_aka + " | " + " | ".join(new_akas)).strip(" | ")
                repo.update_aka(prof["id"], merged)

        # Save scenes
        scenes = [(s["url"], s["title"]) for s in data["scenes"]]
        repo.upsert_scenes(prof["id"], scenes)

        scraped += 1

        # Compact line
        age_str = str(data['age']) if data['age'] is not None else "?"
        aka_str = f" AKA: {', '.join(data['akas'])}" if data['akas'] else ""
        logger.info(f"✓ {data['nationality']:12s} {age_str:>2s}  ({len(data['tags'])} tags, {data['scene_count']} scenes){aka_str}")

        if i < len(profiles):
            time.sleep(random.uniform(*delay_range))

    # Summary
    if scraped:
        logger.info(f'\n✅ {scraped} Profile gescraped, {errors} Fehler')
        logger.info(f'   Daten in performer_features + performer_scenes Tabellen.')


from logutils import setup_logging

if __name__ == "__main__":
    setup_logging()
    fetch_profiles()
