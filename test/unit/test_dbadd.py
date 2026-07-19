"""Offline tests for dbadd.py — the ingest pipeline.

Covers the highest-consequence untested code: schema creation, date parsing,
and add_performers_from_items (performer creation, NO_NAME default, Model:
validation, URL dedup / crawl increment, fuzzy-merge -> AKA, hits parsing).

No network; everything runs against a temp SQLite database.
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

import dbadd

CRAWL_TS = 1_700_000_000  # fixed UTC anchor
SRC = "data/scrapes/crawl_1700000000/batch.csv"
FMT = "%Y-%m-%d %H:%M:%S"


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as d:
        yield os.path.join(d, "test.db")


def _columns(conn: sqlite3.Connection, table: str) -> list:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]


def test_create_db_schema_and_seed(db_path):
    """Schema is created and the non_performer_tags table is seeded."""
    dbadd.create_db(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    assert {"performers", "items", "non_performer_tags"} <= tables

    # Regression guard: items must have thumbnail_url (was missing before).
    assert "thumbnail_url" in _columns(conn, "items")

    cur.execute("SELECT COUNT(*) FROM non_performer_tags")
    assert cur.fetchone()[0] > 0
    conn.close()


def test_create_db_is_idempotent(db_path):
    """Running create_db twice must not error or double-seed tags."""
    dbadd.create_db(db_path)
    dbadd.create_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM non_performer_tags")
    assert cur.fetchone()[0] > 0  # still seeded exactly once
    conn.close()


def test_parse_item_date_relative():
    """Every relative-date branch resolves against the crawl anchor."""
    anchor = datetime.fromtimestamp(CRAWL_TS, tz=timezone.utc)

    # Empty -> crawl timestamp
    assert dbadd.parse_item_date("", CRAWL_TS) == anchor.strftime(FMT)

    # Keyword branches
    assert dbadd.parse_item_date("Yesterday", CRAWL_TS) == (anchor - timedelta(days=1)).strftime(FMT)
    assert dbadd.parse_item_date("Hour ago", CRAWL_TS) == (anchor - timedelta(hours=1)).strftime(FMT)
    assert dbadd.parse_item_date("Last year", CRAWL_TS) == anchor.replace(year=anchor.year - 1).strftime(FMT)

    # Numeric branches
    assert dbadd.parse_item_date("15 min", CRAWL_TS) == (anchor - timedelta(minutes=15)).strftime(FMT)
    assert dbadd.parse_item_date("3 hours ago", CRAWL_TS) == (anchor - timedelta(hours=3)).strftime(FMT)
    assert dbadd.parse_item_date("2 days ago", CRAWL_TS) == (anchor - timedelta(days=2)).strftime(FMT)
    assert dbadd.parse_item_date("2 weeks ago", CRAWL_TS) == (anchor - timedelta(weeks=2)).strftime(FMT)

    # "X months ago" keeps the day-of-month (month math, year rollover)
    m = anchor.month - 2
    y = anchor.year
    while m <= 0:
        m += 12
        y -= 1
    assert dbadd.parse_item_date("2 months ago", CRAWL_TS) == anchor.replace(year=y, month=m).strftime(FMT)


def _sample_items():
    return [
        {"item_url": "https://sxyprn.com/v/aaa", "performers": "Mia Kalani",
         "title": "Hot scene", "item_date": "2 days ago", "hits": "1,234", "source_file": SRC},
        {"item_url": "https://sxyprn.com/v/bbb", "performers": "Mia Kalani",
         "title": "Model: Mia Kalani hardcore", "item_date": "1 day ago", "hits": "500", "source_file": SRC},
        {"item_url": "https://sxyprn.com/v/ccc", "performers": "",
         "title": "No performer here", "item_date": "Yesterday", "hits": "oops", "source_file": SRC},
    ]


def test_add_performers_from_items_core(db_path):
    """Core ingest: performer creation, NO_NAME default, Model: validation,
    crawl increment, hits parsing, and NO_NAME linkage."""
    dbadd.add_performers_from_items(_sample_items(), db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT name, validated, crawls FROM performers ORDER BY name")
    perfs = cur.fetchall()
    assert {r[0] for r in perfs} == {"Mia Kalani", "NO_NAME"}

    mia = next(r for r in perfs if r[0] == "Mia Kalani")
    assert mia[1] == 1          # validated via "Model:" title on second item
    assert mia[2] == 2          # two distinct URLs -> crawls incremented

    cur.execute("SELECT COUNT(*) FROM items")
    assert cur.fetchone()[0] == 3

    # hits parsing: comma-stripped int vs invalid -> None
    cur.execute("SELECT hits FROM items WHERE item_url LIKE '%/aaa'")
    assert cur.fetchone()[0] == 1234
    cur.execute("SELECT hits FROM items WHERE item_url LIKE '%/ccc'")
    assert cur.fetchone()[0] is None

    # NO_NAME item is linked to the NO_NAME performer
    cur.execute("SELECT p.name FROM items i JOIN performers p ON p.id = i.performer_id "
                "WHERE i.item_url LIKE '%/ccc'")
    assert cur.fetchone()[0] == "NO_NAME"

    # first_seen / last_seen populated from publication dates
    cur.execute("SELECT first_seen, last_seen FROM performers WHERE name = 'Mia Kalani'")
    fs, ls = cur.fetchone()
    assert fs and ls
    conn.close()


def test_add_performers_fuzzy_merge_aka(db_path):
    """A near-miss spelling merges into the canonical performer via AKA."""
    items = [
        {"item_url": "https://sxyprn.com/v/aaa", "performers": "Mia Kalani",
         "title": "Scene one", "item_date": "1 day ago", "hits": "", "source_file": SRC},
        {"item_url": "https://sxyprn.com/v/bbb", "performers": "Mia Kalany",
         "title": "Scene two", "item_date": "Yesterday", "hits": "", "source_file": SRC},
    ]
    dbadd.add_performers_from_items(items, db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM performers WHERE name != 'NO_NAME'")
    assert cur.fetchone()[0] == 1  # merged, not duplicated

    cur.execute("SELECT name, aka, crawls FROM performers WHERE name != 'NO_NAME'")
    name, aka, crawls = cur.fetchone()
    assert name == "Mia Kalani"
    assert "Mia Kalany" in aka
    assert crawls == 2
    conn.close()


def test_add_performers_idempotent_dedup(db_path):
    """Re-ingesting the same items does not duplicate performers; items
    always append but crawls only increment on genuinely new URLs."""
    dbadd.add_performers_from_items(_sample_items(), db_path)
    dbadd.add_performers_from_items(_sample_items(), db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM performers")
    assert cur.fetchone()[0] == 2  # still exactly Mia Kalani + NO_NAME

    cur.execute("SELECT COUNT(*) FROM items")
    assert cur.fetchone()[0] == 6  # items are appended each run

    cur.execute("SELECT crawls FROM performers WHERE name = 'Mia Kalani'")
    assert cur.fetchone()[0] == 2  # same two URLs -> no extra increment

    cur.execute("SELECT crawls FROM performers WHERE name = 'NO_NAME'")
    assert cur.fetchone()[0] == 1  # same URL -> no extra increment
    conn.close()
