"""Tests for the refdb / profile-image / stats extensions to the repository port.

Candidate A of the architecture review folds the webapp's raw SQL into the
``PerformerRepository`` port. These tests exercise the new members on BOTH
adapters — the point of A is that one fake (InMemoryPerformerRepository)
exercises the whole webapp surface.

No network. The Sqlite adapter runs against a temp database.
"""

import os
import sqlite3
import tempfile

import pytest

from dbadd import create_db
from performer_repository import (
    InMemoryPerformerRepository,
    SqlitePerformerRepository,
)
import refdb as refdb_module


@pytest.fixture
def repos():
    """Yield both adapters: a temp-DB Sqlite repo and an in-memory repo."""
    tmp = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmp.name, "test.db")
    create_db(db_path)
    # refdb tables are created by the scraper module, not dbadd.create_db
    refdb_module._ensure_tables(db_path)
    sqlite_repo = SqlitePerformerRepository(db_path)
    mem_repo = InMemoryPerformerRepository()
    yield [("sqlite", sqlite_repo), ("memory", mem_repo)]
    tmp.cleanup()


def _model_id(repo, name: str) -> int:
    """Resolve a refdb model id for the roundtrip test (adapter-specific)."""
    if isinstance(repo, SqlitePerformerRepository):
        conn = sqlite3.connect(repo.db_path)
        mid = conn.execute("SELECT id FROM refdb_models WHERE name = ?", (name,)).fetchone()[0]
        conn.close()
        return mid
    for k, v in repo._refdb_models.items():
        if v["name"] == name:
            return k
    raise AssertionError(f"no refdb model named {name!r}")


def test_add_to_refdb(repos):
    for _name, repo in repos:
        repo.add_to_refdb("Test Model")
        assert "Test Model" in repo.get_refdb_names()
        # Idempotent: a second call must not duplicate the name.
        before = len(repo.get_refdb_names())
        repo.add_to_refdb("Test Model")
        assert len(repo.get_refdb_names()) == before


def test_profile_image_roundtrip(repos):
    for _name, repo in repos:
        repo.add_to_refdb("Img Model")
        mid = _model_id(repo, "Img Model")
        assert repo.get_profile_image("Img Model") is None
        repo.save_profile_image(mid, "https://example.com/x.jpg", "/static/images/1.webp")
        assert repo.get_profile_image("Img Model") == "/static/images/1.webp"


def test_compute_refdb_status_matches(repos):
    for _name, repo in repos:
        repo.add_to_refdb("Match Me")
        pid = repo.insert("Match Me", "")
        assert repo.get_by_id(pid).get("refdb_status") is None
        updated = repo.compute_refdb_status()
        assert updated >= 1
        assert repo.get_by_id(pid).get("refdb_status") == "matched"


def test_get_stats_numeric_avg(repos):
    for _name, repo in repos:
        repo.insert("Rater A", "9.5")
        repo.insert("Rater B", "8.0")
        repo.insert("Rater C", "AAA")  # alphabetical -> excluded from numeric avg
        stats = repo.get_stats()
        assert "numeric_avg_rating" in stats
        assert stats["numeric_avg_rating"] == 8.75  # (9.5 + 8.0) / 2
