"""
Database Add Module for Performer Data

This module adds performer data to a SQLite database with:
- Unique performer names as keys
- Unique URLs tracking
- Last updated timestamp
- Crawls counter (starts at 0, increments with each crawl)
"""

import csv
import difflib
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from constants import STOP


def parse_item_date(item_date: str, crawl_ts: int) -> str:
    """
    Convert a relative item_date (e.g. "2 months ago", "Yesterday", "15 min")
    to an absolute ISO timestamp using the crawl timestamp as anchor.

    Returns YYYY-MM-DD HH:MM:SS string, or the current timestamp if parsing fails.
    """
    anchor = datetime.fromtimestamp(crawl_ts, tz=timezone.utc)

    if not item_date or not item_date.strip():
        return anchor.strftime("%Y-%m-%d %H:%M:%S")

    d = item_date.strip()

    # ── Special keywords ──
    if d == "Yesterday":
        return (anchor - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    if d == "Last month":
        m = anchor.month - 1
        y = anchor.year
        if m == 0:
            m = 12
            y -= 1
        return anchor.replace(year=y, month=m).strftime("%Y-%m-%d %H:%M:%S")
    if d == "Last year":
        return anchor.replace(year=anchor.year - 1).strftime("%Y-%m-%d %H:%M:%S")
    if d == "Hour ago":
        return (anchor - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    # ── "X min" (truncated) or "X min ago" ──
    m = re.match(r"^(\d+)\s*min", d)
    if m:
        return (anchor - timedelta(minutes=int(m.group(1)))).strftime("%Y-%m-%d %H:%M:%S")

    # ── "X hours ago" or "X h" or "X h Y min" ──
    m = re.match(r"^(\d+)\s*h(?:ours?)?(?:\s+(\d+)\s*min)?", d)
    if m:
        hours = int(m.group(1))
        minutes = int(m.group(2)) if m.group(2) else 0
        return (anchor - timedelta(hours=hours, minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")

    # ── "X days ago" ──
    m = re.match(r"^(\d+)\s+days?\s+ago", d)
    if m:
        return (anchor - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d %H:%M:%S")

    # ── "X weeks ago" ──
    m = re.match(r"^(\d+)\s+weeks?\s+ago", d)
    if m:
        return (anchor - timedelta(weeks=int(m.group(1)))).strftime("%Y-%m-%d %H:%M:%S")

    # ── "X months ago" ──
    m = re.match(r"^(\d+)\s+months?\s+ago", d)
    if m:
        months = int(m.group(1))
        m_target = anchor.month - months
        y = anchor.year
        while m_target <= 0:
            m_target += 12
            y -= 1
        return anchor.replace(year=y, month=m_target).strftime("%Y-%m-%d %H:%M:%S")

    # ── "X years ago" ──
    m = re.match(r"^(\d+)\s+years?\s+ago", d)
    if m:
        return anchor.replace(year=anchor.year - int(m.group(1))).strftime("%Y-%m-%d %H:%M:%S")

    # Fallback: use crawl timestamp
    return anchor.strftime("%Y-%m-%d %H:%M:%S")


def _crawl_ts_from_source(source_file: str) -> int:
    """Extract crawl unix timestamp from a source_file path."""
    m = re.search(r"crawl_(\d+)", source_file)
    if m:
        return int(m.group(1))
    return int(datetime.now(timezone.utc).timestamp())


def create_db(db_path):
    """
    Create the performers database with required schema
    Includes migration logic to add new columns if they exist.

    Args:
        db_path (str): Path to the SQLite database file
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create performers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS performers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            urls TEXT,  -- Pipe-separated string of unique URLs
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            crawls INTEGER DEFAULT 0,
            aka TEXT,
            rating TEXT
        )
    ''')

    # Create items table to store individual items with performer association and add date
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            performer_id INTEGER,
            item_url TEXT NOT NULL,
            title TEXT,
            item_date TEXT,  -- Date from the source if available
            hits INTEGER,
            source_file TEXT,
            thumbnail_url TEXT,
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (performer_id) REFERENCES performers (id)
        )
    ''')

    # Migration: Add aka, rating, validated if missing
    cursor.execute("PRAGMA table_info(performers)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'aka' not in columns:
        cursor.execute("ALTER TABLE performers ADD COLUMN aka TEXT")
    if 'rating' not in columns:
        cursor.execute("ALTER TABLE performers ADD COLUMN rating TEXT")
    if 'validated' not in columns:
        cursor.execute("ALTER TABLE performers ADD COLUMN validated INTEGER DEFAULT 0")
    if 'first_seen' not in columns:
        cursor.execute("ALTER TABLE performers ADD COLUMN first_seen TIMESTAMP")
    if 'last_seen' not in columns:
        cursor.execute("ALTER TABLE performers ADD COLUMN last_seen TIMESTAMP")
    if 'refdb_status' not in columns:
        cursor.execute("ALTER TABLE performers ADD COLUMN refdb_status TEXT DEFAULT NULL")

    # ── Non-performer tags table (blocklist for sxyprn data-subkey values) ──
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS non_performer_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag TEXT UNIQUE NOT NULL,
            reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ── Cached profile images (written by the webapp after an analvids lookup) ──
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS performer_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            performer_id INTEGER,
            model_id INTEGER,
            image_url TEXT,
            local_path TEXT,
            type TEXT DEFAULT "profile",
            added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ── Performer features / scenes ──
    # Previously had NO CREATE statement anywhere in the repo, so a fresh
    # database would fail get_stats()/upsert_features(). Owned here now.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS performer_features (
            performer_id INTEGER PRIMARY KEY,
            nationality TEXT,
            age INTEGER,
            tags TEXT,
            scene_count INTEGER DEFAULT 0,
            last_scraped TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS performer_scenes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            performer_id INTEGER,
            scene_url TEXT,
            scene_title TEXT
        )
    ''')

    # Seed initial values if table is empty
    cursor.execute("SELECT COUNT(*) FROM non_performer_tags")
    if cursor.fetchone()[0] == 0:
        _seed_non_performer_tags(cursor)
        print("  ~ seeded non_performer_tags table")

def _seed_non_performer_tags(cursor):
    """Seed the non_performer_tags table with initial blocklist values."""
    conn = cursor.connection
    seeds = [
        # Nationalities / demonyms
        ("Chilean", "nationality descriptor"),
        ("Brazilian", "nationality descriptor"),
        ("Russian", "nationality descriptor"),
        ("American", "nationality descriptor"),
        ("British", "nationality descriptor"),
        ("German", "nationality descriptor"),
        ("French", "nationality descriptor"),
        ("Spanish", "nationality descriptor"),
        ("Italian", "nationality descriptor"),
        ("Japanese", "nationality descriptor"),
        ("Chinese", "nationality descriptor"),
        ("Indian", "nationality descriptor"),
        ("Mexican", "nationality descriptor"),
        ("Colombian", "nationality descriptor"),
        ("Argentinian", "nationality descriptor"),
        ("Australian", "nationality descriptor"),
        ("Canadian", "nationality descriptor"),
        ("Dutch", "nationality descriptor"),
        ("Polish", "nationality descriptor"),
        ("Swedish", "nationality descriptor"),
        ("Norwegian", "nationality descriptor"),
        ("Danish", "nationality descriptor"),
        ("Finnish", "nationality descriptor"),
        ("Hungarian", "nationality descriptor"),
        ("Romanian", "nationality descriptor"),
        ("Czech", "nationality descriptor"),
        ("Ukrainian", "nationality descriptor"),
        ("Greek", "nationality descriptor"),
        ("Turkish", "nationality descriptor"),
        ("Portuguese", "nationality descriptor"),
        ("Swiss", "nationality descriptor"),
        ("Austrian", "nationality descriptor"),
        ("Belgian", "nationality descriptor"),
        ("Irish", "nationality descriptor"),
        ("Scottish", "nationality descriptor"),
        # Descriptive / category tags
        ("Anal Queen", "descriptive title, not a performer"),
        ("Anal Queens", "descriptive title, not a performer"),
        ("Dirty", "descriptive tag"),
        ("Kinky", "descriptive tag"),
        ("Slut", "descriptive tag"),
        ("Sluts", "descriptive tag"),
        ("Gangbang", "category tag"),
        ("GangBang", "category tag"),
        ("Hardcore", "category tag"),
        ("Interracial", "category tag"),
        ("Pissing", "category tag"),
        ("Casting", "category tag"),
        # Studio / brand names
        ("Yummy", "studio name (Yummy Estudio)"),
        ("LegalPorno", "studio name"),
        ("PornBox", "studio name"),
        ("PornoBB", "studio name"),
        # Platform / site names
        ("OnlyFans", "platform name"),
        ("BFFS", "site/studio name"),
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO non_performer_tags (tag, reason) VALUES (?, ?)",
        seeds
    )

    # Backfill first_seen / last_seen using computed publish dates from items
    # (We do this in Python using parse_item_date to handle relative date strings)
    from collections import defaultdict

    cursor.execute('''
        SELECT i.performer_id, i.item_date, i.source_file
        FROM items i
        ORDER BY i.performer_id
    ''')
    rows = cursor.fetchall()
    perf_dates: dict = defaultdict(list)
    for pid, item_date, source_file in rows:
        crawl_ts = _crawl_ts_from_source(source_file or "")
        pub_date = parse_item_date(item_date, crawl_ts)
        perf_dates[pid].append(pub_date)

    for pid, dates in perf_dates.items():
        dates.sort()
        cursor.execute(
            "UPDATE performers SET first_seen = ?, last_seen = ? WHERE id = ?",
            (dates[0], dates[-1], pid),
        )

    conn.commit()
    conn.close()


def add_performers_from_items(items, db_path="performers.db"):
    """
    Add performers from a list of items to SQLite database

    Args:
        items (list): List of dictionaries containing item data
        db_path (str): Path to the SQLite database file
    """
    # Create database if it doesn't exist
    create_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Load all existing performers for fuzzy matching
    cursor.execute("SELECT id, name, urls, crawls, aka, validated FROM performers")
    all_rows = cursor.fetchall()
    perf_by_name: dict = {row[1]: {"id": row[0], "urls": row[2], "crawls": row[3], "aka": row[4] or "", "validated": bool(row[5])} for row in all_rows}
    perf_names: list = list(perf_by_name.keys())

    new_performers_added = []
    updated_performers = []
    fuzzy_merged: list = []  # Track fuzzy merges for aka updates

    def _find_performer(name: str):
        """Find performer by exact or fuzzy name match."""
        if name in perf_by_name:
            return name, perf_by_name[name]
        # Fuzzy match
        matches = difflib.get_close_matches(name, perf_names, n=1, cutoff=0.85)
        if matches:
            matched = matches[0]
            return matched, perf_by_name[matched]
        return None, None

    for row in items:
        item_url = row.get('item_url', '').strip()
        performers_str = row.get('performers', '').strip()
        title = row.get('title', '').strip()
        item_date = row.get('item_date', '').strip()
        hits = row.get('hits', '').strip()
        source_file = row.get('source_file', '').strip()

        if not item_url:
            continue

        # Handle missing performers by using a default name
        if not performers_str:
            performers = ["NO_NAME"]
        else:
            performers = [p.strip() for p in performers_str.split(';') if p.strip()]
            if not performers:
                performers = ["NO_NAME"]

        for performer in performers:
            # Find existing performer (exact or fuzzy match)
            matched_name, result = _find_performer(performer)

            if result:
                # Performer exists, update their record
                performer_id = result["id"]
                existing_urls_str = result["urls"]
                current_crawls = result["crawls"]

                # If fuzzy match, update AKA to track alternative spelling
                if matched_name != performer:
                    current_aka = result["aka"]
                    if performer.lower() not in current_aka.lower():
                        new_aka = (current_aka + " | " + performer).strip(" | ")
                        cursor.execute("UPDATE performers SET aka = ? WHERE id = ?", (new_aka, performer_id))
                        perf_by_name[matched_name]["aka"] = new_aka
                        fuzzy_merged.append((performer, matched_name))

                # Use a set to maintain uniqueness of URLs
                if existing_urls_str:
                    # Split and filter out empty strings
                    existing_urls = {u.strip() for u in existing_urls_str.split('|') if u.strip()}
                else:
                    existing_urls = set()

                # Check if this is a new URL
                is_new_url = item_url not in existing_urls

                if is_new_url:
                    existing_urls.add(item_url)
                    # Only increment crawls if we actually found a new video for this performer
                    new_crawl_count = current_crawls + 1
                    updated_performers.append((performer, item_url))
                else:
                    new_crawl_count = current_crawls

                # Update the record
                updated_urls_str = '|'.join(sorted(list(existing_urls)))

                # Check if model entry → validate performer
                is_model = title.startswith("Model: ")
                if is_model and not result["validated"]:
                    cursor.execute("UPDATE performers SET validated = 1 WHERE id = ?", (performer_id,))
                    perf_by_name[matched_name]["validated"] = True

                # Compute last_seen from the item's publication date
                crawl_ts = _crawl_ts_from_source(source_file)
                pub_date = parse_item_date(item_date, crawl_ts)
                cursor.execute("""
                    UPDATE performers
                    SET urls = ?,
                        last_updated = CURRENT_TIMESTAMP,
                        last_seen = CASE WHEN ? > last_seen OR last_seen IS NULL THEN ? ELSE last_seen END,
                        first_seen = CASE WHEN ? < first_seen OR first_seen IS NULL THEN ? ELSE first_seen END,
                        crawls = ?
                    WHERE id = ?
                """, (updated_urls_str, pub_date, pub_date, pub_date, pub_date, new_crawl_count, performer_id))

            else:
                # New performer
                is_model = title.startswith("Model: ")
                val = 1 if is_model else 0
                # Compute first_seen from the item's publication date
                crawl_ts = _crawl_ts_from_source(source_file)
                pub_date = parse_item_date(item_date, crawl_ts)
                cursor.execute("""
                    INSERT INTO performers (name, urls, last_updated, crawls, aka, rating, validated, first_seen, last_seen)
                    VALUES (?, ?, CURRENT_TIMESTAMP, 1, '', '', ?, ?, ?)
                """, (performer, item_url, val, pub_date, pub_date))

                performer_id = cursor.lastrowid
                new_performers_added.append((performer, item_url))

                # Update cache so subsequent rows find this performer
                perf_by_name[performer] = {"id": performer_id, "urls": item_url, "crawls": 1, "aka": "", "validated": bool(val)}
                perf_names.append(performer)

            # Insert the item into the items table
            # Convert hits to integer if possible
            hits_int = None
            if hits:
                try:
                    hits_int = int(hits.replace(',', ''))
                except ValueError:
                    hits_int = None

            cursor.execute("""
                INSERT INTO items (performer_id, item_url, title, item_date, hits, source_file)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (performer_id, item_url, title, item_date, hits_int, source_file))

    # Commit changes and close connection
    conn.commit()
    conn.close()

    # Print summary (quiet — orchestator shows its own per-site summary)
    if fuzzy_merged:
        for alt, canon in fuzzy_merged:
            print(f"  ~ merged '{alt}' -> '{canon}' (AKA)")


def add_performers_from_csv(csv_file_path, db_path="performers.db"):
    """
    Add performers from extracted.csv to SQLite database

    Args:
        csv_file_path (str): Path to the extracted CSV file
        db_path (str): Path to the SQLite database file
    """
    # Read the CSV file
    items = []
    with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        items = list(reader)

    add_performers_from_items(items, db_path)


def dedup_performers(db_path="performers.db", force=False):
    """
    Fuzzy dedup: merge ähnliche Performer-Namen in der Datenbank.

    Nutzt difflib.get_close_matches (cutoff 0.85) um alternative
    Schreibweisen zu erkennen und zusammenzuführen.
    Überspringt Paare bei denen beide Seiten viele Items haben (>5),
    da das wahrscheinlich echte verschiedene Leute sind.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('SELECT id, name, urls, crawls, aka, validated FROM performers WHERE name != "NO_NAME" ORDER BY name')
    rows = cursor.fetchall()

    name_to_entry = {r[1]: r for r in rows}
    all_names = list(name_to_entry.keys())

    # Pre-count items per performer
    item_counts = {}
    cursor.execute('SELECT performer_id, COUNT(*) FROM items GROUP BY performer_id')
    for pid, cnt in cursor.fetchall():
        item_counts[pid] = cnt

    merged = 0
    skipped_high = 0
    processed = set()

    for name in all_names:
        if name in processed:
            continue

        matches = difflib.get_close_matches(name, all_names, n=5, cutoff=0.85)
        matches = [m for m in matches if m != name and m not in processed]

        if not matches:
            processed.add(name)
            continue

        # Canonical name: prefer longer, proper-cased
        candidates = [name] + matches
        canonical = max(candidates, key=lambda x: (len(x), x[0].isupper()))

        for match in matches:
            if match in processed:
                continue

            keep = canonical
            remove = match
            if keep == remove:
                continue

            keep_entry = name_to_entry.get(keep)
            remove_entry = name_to_entry.get(remove)
            if not keep_entry or not remove_entry:
                continue

            keep_id = keep_entry[0]
            remove_id = remove_entry[0]

            k_valid = bool(keep_entry[5])
            r_valid = bool(remove_entry[5])

            # Both validated → different canonical names, skip
            if k_valid and r_valid:
                skipped_high += 1
                continue

            # One validated → merge (unvalidated is alias/typo)
            if (k_valid or r_valid) and not force:
                # Ensure validated name is the one we keep
                if r_valid and not k_valid:
                    keep, remove = remove, keep
                    keep_entry, remove_entry = remove_entry, keep_entry
                    keep_id, remove_id = remove_id, keep_id
                # Will merge below — no further check needed
            else:
                k_count = item_counts.get(keep_id, 0)
                r_count = item_counts.get(remove_id, 0)
                # Skip if both have >5 items (likely different people)
                if not force and k_count > 5 and r_count > 5:
                    skipped_high += 1
                    continue

            cursor.execute('SELECT urls, crawls, aka FROM performers WHERE id = ?', (keep_id,))
            r = cursor.fetchone()
            if not r:
                continue
            k_urls, k_crawls, k_aka = r

            cursor.execute('SELECT urls, crawls, aka FROM performers WHERE id = ?', (remove_id,))
            r = cursor.fetchone()
            if not r:
                continue
            r_urls, r_crawls, r_aka = r

            all_urls = set()
            if k_urls:
                all_urls.update(k_urls.split('|'))
            if r_urls:
                all_urls.update(r_urls.split('|'))

            total_crawls = (k_crawls or 0) + (r_crawls or 0)

            akas = set()
            for a in [k_aka, r_aka]:
                if a:
                    for part in a.split('|'):
                        akas.add(part.strip())
            akas.add(remove)
            akas.discard(keep)
            new_aka = ' | '.join(sorted(akas))

            cursor.execute('UPDATE items SET performer_id = ? WHERE performer_id = ?', (keep_id, remove_id))
            cursor.execute('''UPDATE performers
                SET urls = ?, crawls = ?, aka = ?, last_updated = CURRENT_TIMESTAMP
                WHERE id = ?''', ('|'.join(sorted(all_urls)), total_crawls, new_aka, keep_id))
            cursor.execute('DELETE FROM performers WHERE id = ?', (remove_id,))

            # Update item count cache
            combined_count = k_count + r_count
            item_counts[keep_id] = combined_count
            item_counts.pop(remove_id, None)

            processed.add(remove)
            merged += 1
            print(f'  {remove:30s} → {keep:30s}  ({r_count} items → merged)')

        processed.add(name)

    conn.commit()
    conn.close()

    if merged:
        print(f'\n{merged} Dubletten gemerged.')
    if skipped_high:
        print(f'{skipped_high} Paare übersprungen (beide >5 Items, --force zum mergen).')
    if not merged and not skipped_high:
        print('Keine Dubletten gefunden.')


def resolve_nonames(db_path="performers.db", dry_run=False, limit=None):
    """
    NO_NAME-Items durch Scene-URLs + konservatives WRatio-Fuzzy-Matching auflösen.

    Args:
        dry_run: Nur zeigen, nichts speichern
        limit: Nur N Items testen
    """
    import re
    from rapidfuzz import fuzz, process
    from urllib.parse import urlparse

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Noise-Wörter (nie Teil von Performer-Namen)

    # Performernamen laden
    c.execute("""SELECT id, name FROM performers
        WHERE name != 'NO_NAME' ORDER BY validated DESC, LENGTH(name) DESC""")
    known = c.fetchall()
    known_names = [r[1] for r in known]
    known_ids = {r[1]: r[0] for r in known}

    # NO_NAME ID
    c.execute("SELECT id FROM performers WHERE name = 'NO_NAME'")
    no_name_id = c.fetchone()
    if not no_name_id:
        print("Kein NO_NAME-Eintrag.")
        conn.close()
        return
    no_name_id = no_name_id[0]

    def _normalize(s):
        """Normalize string for matching: lowercase, strip, collapse spaces."""
        s = s.lower().strip()
        s = re.sub(r"[^a-z0-9' ]", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    def _assign(pid, item_id, item_url):
        if dry_run:
            return
        c.execute("UPDATE items SET performer_id = ? WHERE id = ?", (pid, item_id))
        c.execute("SELECT urls, crawls FROM performers WHERE id = ?", (pid,))
        row = c.fetchone()
        if row:
            urls_str, crawls = row[0] or "", row[1] or 0
            urls_set = set(urls_str.split("|")) if urls_str else set()
            if item_url and item_url not in urls_set:
                urls_set.add(item_url)
                c.execute("UPDATE performers SET urls = ?, crawls = ? WHERE id = ?",
                          ("|".join(sorted(urls_set)), crawls + 1, pid))

    def _fuzzy(cand, cutoff=90):
        """token_sort_ratio-based fuzzy match. Nur ganze Strings, kein Partial."""
        if len(cand) < 4:
            return None
        result = process.extractOne(cand, known_names, scorer=fuzz.token_sort_ratio, score_cutoff=cutoff)
        if result:
            return (result[0], result[1])
        return None

    def _extract_slug_candidates(url):
        """Extrahiere Bigram-Kandidaten aus URL-Slug."""
        if not url:
            return []
        path = urlparse(url).path.strip("/")
        slug = path.rsplit("/", 1)[-1] if "/" in path else path
        slug = re.sub(r"^\d+[_]?", "", slug)
        words = re.split(r"[_-]", slug)
        words = [w for w in words if len(w) >= 3 and w.lower() not in STOP]
        cands = []
        for i in range(len(words)):
            if i + 1 < len(words):
                cands.append(f"{words[i].title()} {words[i+1].title()}")
        return cands

    def _extract_title_candidates(title):
        """Extrahiere Bigram-Kandidaten aus Titel (Großbuchstaben-Sequenzen).
        Nur Bigramme — keine Einzelwörter (vermeidet False Positives).
        """
        if not title:
            return []
        t = re.sub(r"[^a-zA-Z0-9' -]", " ", title)
        t = re.sub(r"\s+", " ", t).strip()
        words = t.split()
        cands = set()
        for i, w in enumerate(words):
            if not w or len(w) < 2 or w.lower() in STOP:
                continue
            if w[0].isupper() and i + 1 < len(words) and words[i+1][0].isupper():
                c2 = f"{w} {words[i+1]}"
                if len(c2) >= 6 and words[i+1].lower() not in STOP:
                    cands.add(c2)
        return list(cands)

    # ── Items laden ──
    query = "SELECT id, title, item_url FROM items WHERE performer_id = ?"
    if limit:
        query += f" LIMIT {limit}"
    c.execute(query, (no_name_id,))
    items = c.fetchall()
    total = len(items)
    if total == 0:
        print("Keine NO_NAME-Items.")
        conn.close()
        return

    print(f"\n📋 {total} NO_NAME-Items...")
    if dry_run:
        print("   (Dry-Run — keine Änderungen)")

    resolved = 0
    s1 = s2 = s3 = 0
    review = []  # (score, cand, matched, item_id, title[:60])

    # ── 1. Scene-URL Match ──
    c.execute("SELECT scene_url, performer_id FROM performer_scenes")
    scene_map = {u: pid for u, pid in c.fetchall()}

    remaining = []
    for item_id, title, item_url in items:
        if item_url and item_url in scene_map:
            pid = scene_map[item_url]
            c.execute("SELECT name FROM performers WHERE id = ?", (pid,))
            pname = c.fetchone()[0] if c.fetchone() else "?"
            _assign(pid, item_id, item_url)
            resolved += 1
            s1 += 1
        else:
            remaining.append((item_id, title, item_url))
    print(f"  ├─ 1/3 Scene-URL (100% sicher): {s1}")

    # ── 2. URL-Slug WRatio ≥ 90 ──
    still = []
    for item_id, title, item_url in remaining:
        cands = _extract_slug_candidates(item_url)
        matched = None
        for cand in cands:
            m = _fuzzy(cand, cutoff=90)
            if m:
                matched = (m[0], m[1], cand)
                break
        if matched:
            name, score, cand = matched
            _assign(known_ids[name], item_id, item_url)
            resolved += 1
            s2 += 1
            if score < 95:
                review.append((score, cand, name, item_id, (title or "")[:60]))
        else:
            still.append((item_id, title, item_url))
    print(f"  ├─ 2/3 URL-Slug WRatio≥90: {s2}")

    # ── 3. Titel WRatio ≥ 90 ──
    def _process_title(item_id, title, item_url):
        cands = _extract_title_candidates(title)
        for cand in cands:
            m = _fuzzy(cand, cutoff=90)
            if m:
                name, score = m
                _assign(known_ids[name], item_id, item_url)
                if score < 95:
                    review.append((score, cand, name, item_id, (title or "")[:60]))
                return True
        return False

    for item_id, title, item_url in still:
        if _process_title(item_id, title, item_url):
            s3 += 1
            resolved += 1

    print(f"  └─ 3/3 Titel WRatio≥90:     {s3}")
    print(f"\n✅ {resolved}/{total} aufgelöst (Rest: {total - resolved})")

    if review:
        print(f"\n⚠️  {len(review)} unsichere Matches für Review:")
        for score, cand, name, item_id, title_snip in sorted(review)[:20]:
            print(f"  {score:5.1f}  {cand:25s} → {name:25s}  | {title_snip}")

    if not dry_run:
        conn.commit()
    conn.close()


def main():
    """Main function to run the database add module"""
    import sys

    db_file_path = "performers.db"

    if "--dedup" in sys.argv:
        force = "--force" in sys.argv
        dedup_performers(db_file_path, force=force)
        return

    if "--resolve-nonames" in sys.argv:
        dry = "--dry-run" in sys.argv or "-n" in sys.argv
        lim = None
        for i, a in enumerate(sys.argv):
            if a.startswith("--limit=") or a.startswith("-l="):
                try: lim = int(a.split("=", 1)[1])
                except Exception: pass
        resolve_nonames(db_file_path, dry_run=dry, limit=lim)
        return

    csv_file_path = "extracted.csv"

    # Check if CSV file exists
    if not Path(csv_file_path).exists():
        print(f"CSV file {csv_file_path} not found!")
        return

    add_performers_from_csv(csv_file_path, db_file_path)


if __name__ == "__main__":
    main()