"""
PerformerRepository — single interface for all performer database operations.

Two adapters: SqlitePerformerRepository (production, backed by performers.db)
and InMemoryPerformerRepository (tests, backed by dicts).

Usage:
    from performer_repository import SqlitePerformerRepository
    repo = SqlitePerformerRepository()
    performers = repo.search(q="Natasha")
"""

from __future__ import annotations

import sqlite3
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


class _NoOpConn:
    """Stand-in for a SQLite connection used by test adapters.

    The resolver calls repo._conn().commit() to flush batched writes.
    The in-memory adapter is already synchronous, so commit is a no-op.
    """

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


# ── Abstract interface ────────────────────────────────────


class PerformerRepository(ABC):
    """Interface for all performer database operations."""

    # --- Performers CRUD ---

    @abstractmethod
    def search(self, q: str = "", sort_by: str = "name", sort_order: str = "asc",
               show_aliases: bool = False, dap_only: bool = False,
               limit: Optional[int] = None) -> List[dict]:
        """Search/filter performers with left-joined features."""

    @abstractmethod
    def get_by_id(self, performer_id: int) -> Optional[dict]:
        """Single performer by id (without features)."""

    @abstractmethod
    def get_by_name(self, name: str) -> Optional[dict]:
        """Single performer by name."""

    @abstractmethod
    def get_all(self) -> List[dict]:
        """All performers (name, id, validated)."""

    @abstractmethod
    def get_refdb_names(self) -> List[str]:
        """All refdb_models names (separate table, used for fuzzy/hinted matching)."""

    @abstractmethod
    def get_no_name(self) -> dict:
        """The special NO_NAME performer record."""

    @abstractmethod
    def insert(self, name: str, rating: Optional[str] = None,
               validated: int = 0) -> int:
        """Insert a new performer, return its id."""

    @abstractmethod
    def upsert(self, name: str, url: str = "",
               crawl_ts: Optional[int] = None) -> Tuple[int, bool]:
        """Insert or update a performer. Returns (id, was_created)."""

    @abstractmethod
    def update_name(self, performer_id: int, name: str) -> None:
        """Update performer name by id."""

    @abstractmethod
    def update_rating(self, performer_id: int, rating: str) -> None:
        """Update performer rating."""

    @abstractmethod
    def update_aka(self, performer_id: int, aka: str) -> None:
        """Add/update aka field (merges with existing if any)."""

    @abstractmethod
    def add_url(self, performer_id: int, url: str) -> None:
        """Add a URL to the performer's pipe-separated urls field."""

    @abstractmethod
    def set_validated(self, performer_id: int) -> None:
        """Mark performer as validated."""

    @abstractmethod
    def set_refdb_status(self, performer_id: int, status: str) -> None:
        """Set refdb_status (matched/unmatched/null)."""

    @abstractmethod
    def update_seen_dates(self, performer_id: int,
                          publish_date: Optional[str] = None) -> None:
        """Update first_seen/last_seen based on a publish date."""

    @abstractmethod
    def delete(self, performer_id: int) -> None:
        """Delete a performer (cascading to items/scenes/features)."""

    # --- Items ---

    @abstractmethod
    def get_items(self, performer_id: int,
                  limit: Optional[int] = None) -> List[dict]:
        """All items for a performer."""

    @abstractmethod
    def get_unmatched_items(self, no_name_id: int,
                            limit: Optional[int] = None) -> List[dict]:
        """Items still assigned to NO_NAME, randomized."""

    @abstractmethod
    def assign_item(self, item_id: int, performer_id: int) -> None:
        """Set item's performer_id."""

    @abstractmethod
    def unassign_item(self, item_id: int) -> None:
        """Set item's performer_id to NULL."""

    @abstractmethod
    def count_items(self, performer_id: int) -> int:
        """Count items for a performer."""

    @abstractmethod
    def count_unmatched(self, no_name_id: int) -> int:
        """Count items still assigned to NO_NAME."""

    @abstractmethod
    def reassign_items(self, from_id: int, to_id: int) -> None:
        """Reassign all items from one performer to another."""

    @abstractmethod
    def delete_item(self, item_id: int) -> None:
        """Delete a single item."""

    @abstractmethod
    def get_item_by_id(self, item_id: int) -> Optional[dict]:
        """Single item by id (with performer name left-joined)."""

    # --- Scenes ---

    @abstractmethod
    def get_scenes(self, performer_id: int) -> List[dict]:
        """All scenes for a performer."""

    @abstractmethod
    def get_scene_map(self) -> Dict[str, int]:
        """scene_url -> performer_id mapping."""

    @abstractmethod
    def delete_scenes(self, performer_id: int) -> None:
        """Delete all scenes for a performer."""

    @abstractmethod
    def insert_scene(self, performer_id: int, scene_url: str,
                     scene_title: str) -> None:
        """Insert a single scene."""

    @abstractmethod
    def upsert_scenes(self, performer_id: int,
                      scenes: List[Tuple[str, str]]) -> int:
        """Replace all scenes for a performer. Returns count inserted."""

    # --- Features ---

    @abstractmethod
    def get_features(self, performer_id: int) -> Optional[dict]:
        """performer_features row for a performer."""

    @abstractmethod
    def upsert_features(self, performer_id: int,
                        nationality: str = "",
                        age: Optional[int] = None,
                        tags: str = "",
                        scene_count: int = 0) -> None:
        """Insert or replace performer_features."""

    # --- Merging ---

    @abstractmethod
    def merge(self, keep_id: int, remove_id: int) -> None:
        """Merge two performers: reassign items, combine urls/akas, delete remove."""

    # --- Stats ---

    @abstractmethod
    def get_stats(self) -> dict:
        """Aggregate stats: total performers, items, DAP count, rating distribution,
        item histogram, and numeric_avg_rating."""

    @abstractmethod
    def get_stale(self, stale_days: int = 30) -> List[dict]:
        """Performers whose profiles haven't been scraped recently."""

    @abstractmethod
    def get_profiles_needing_scrape(self, stale_days: int = 30) -> List[dict]:
        """Validated analvids performers whose feature profiles are missing or stale."""

    @abstractmethod
    def get_unassigned_items(self, sort_by: str = "added_date",
                             sort_order: str = "desc") -> List[dict]:
        """Items with NULL performer_id."""

    # --- Non-performer tags ---

    @abstractmethod
    def get_non_performer_tags(self) -> List[dict]:
        """All non_performer_tags ordered by tag."""

    @abstractmethod
    def add_non_performer_tag(self, tag: str, reason: str = "") -> int:
        """Insert a new non_performer_tag. Returns id. Raises on duplicate."""

    @abstractmethod
    def delete_non_performer_tag(self, tag_id: int) -> None:
        """Remove a non_performer_tag."""

    # --- RefDB browsing ---

    @abstractmethod
    def search_refdb(self, q: str = "", nationality: str = "", tag: str = "",
                     age_min: Optional[int] = None,
                     age_max: Optional[int] = None,
                     has_profile: str = "",
                     sort_by: str = "name", sort_order: str = "asc",
                     page: int = 1, per_page: int = 50) -> dict:
        """Search/filter refdb_models + profiles. Returns {data, total, page, per_page}."""

    @abstractmethod
    def get_refdb_nationalities(self) -> List[str]:
        """Distinct nationalities from refdb_profiles."""

    @abstractmethod
    def get_refdb_counts(self) -> dict:
        """{validated, scraped, pending} counts."""

    @abstractmethod
    def get_most_crawled(self, limit: int = 10) -> List[dict]:
        """Performers sorted by crawls desc."""

    @abstractmethod
    def get_all_rated(self) -> List[dict]:
        """All performers with non-empty rating."""

    # --- RefDB writes / profile images ---

    @abstractmethod
    def add_to_refdb(self, name: str) -> None:
        """Insert a manually-confirmed performer name into refdb_models + validated tags."""

    @abstractmethod
    def get_profile_image(self, name: str) -> Optional[str]:
        """Return the cached local profile image path for a performer name, or None."""

    @abstractmethod
    def save_profile_image(self, model_id: int, image_url: str, local_path: str) -> None:
        """Persist a cached profile image (model_id, source url, local path)."""

    @abstractmethod
    def compute_refdb_status(self) -> int:
        """Batch-compute refdb_status (matched/fuzzy) for performers; return count updated."""

    # --- Bulk insert ---

    @abstractmethod
    def bulk_upsert_performers(self, names: List[str]) -> Dict[str, int]:
        """Upsert many performer names at once, return {name: id} map."""

    # --- Maintenance ---

    @abstractmethod
    def ensure_schema(self) -> None:
        """Create tables and migrate if needed."""


# ── SQLite adapter ────────────────────────────────────────


class SqlitePerformerRepository(PerformerRepository):
    """Production adapter — backed by SQLite performers.db."""

    def __init__(self, db_path: str = "performers.db"):
        self.db_path = db_path
        self.ensure_schema()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Schema ──

    def ensure_schema(self) -> None:
        from dbadd import create_db
        create_db(self.db_path)

    # ── Performers ──

    def search(self, q="", sort_by="name", sort_order="asc",
               show_aliases=False, dap_only=False, limit=None) -> List[dict]:
        valid_cols = ["id", "name", "last_updated", "crawls",
                      "rating", "first_seen", "last_seen"]
        if sort_by not in valid_cols:
            sort_by = "name"
        if sort_order not in ("asc", "desc"):
            sort_order = "asc"

        conditions = []
        params = []
        if not show_aliases:
            conditions.append("(p.crawls > 0 OR p.validated = 1)")
        if dap_only:
            conditions.append("(pf.tags LIKE '%Double anal%' OR pf.tags LIKE '%DAP%')")
        if q:
            conditions.append("(p.name LIKE ? OR p.aka LIKE ?)")
            like_q = f"%{q}%"
            params.extend([like_q, like_q])

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"""
            SELECT p.*, pf.nationality, pf.age, pf.tags, pf.scene_count,
                   p.refdb_status,
                   COALESCE(ic.cnt, 0) AS item_count
            FROM performers p
            LEFT JOIN performer_features pf ON p.id = pf.performer_id
            LEFT JOIN (
                SELECT performer_id, COUNT(*) AS cnt
                FROM items GROUP BY performer_id
            ) ic ON ic.performer_id = p.id
            {where}
            ORDER BY p.{sort_by} {sort_order}
        """
        conn = self._conn()
        rows = conn.execute(query, params).fetchall()
        conn.close()

        results = []
        for r in rows:
            d = dict(r)
            d["nationality"] = d.pop("nationality", None) or ""
            d["age"] = d.pop("age", None)
            d["tags"] = d.pop("tags", None) or ""
            d["scene_count"] = d.pop("scene_count", None) or 0
            d["item_count"] = d.pop("item_count", 0) or 0
            d["refdb_match"] = d.pop("refdb_status", None) or "unmatched"
            results.append(d)

        if limit:
            results = results[:int(limit)]
        return results

    def get_by_id(self, performer_id: int) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM performers WHERE id = ?", (performer_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_by_name(self, name: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM performers WHERE name = ?", (name,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all(self) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, name FROM performers ORDER BY name"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_refdb_names(self) -> List[str]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT name FROM refdb_models"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_no_name(self) -> dict:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM performers WHERE name = 'NO_NAME'"
        ).fetchone()
        conn.close()
        if not row:
            raise ValueError("NO_NAME performer not found in DB")
        return dict(row)

    def insert(self, name: str, rating: Optional[str] = None,
               validated: int = 0) -> int:
        conn = self._conn()
        conn.execute(
            "INSERT INTO performers (name, rating, validated, last_updated) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (name, rating, validated),
        )
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        return pid

    def upsert(self, name: str, url: str = "",
               crawl_ts: Optional[int] = None) -> Tuple[int, bool]:
        conn = self._conn()
        existing = conn.execute(
            "SELECT id, urls FROM performers WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            pid = existing["id"]
            urls_set = set(existing["urls"].split("|")) if existing["urls"] else set()
            if url and url not in urls_set:
                urls_set.add(url)
                conn.execute(
                    "UPDATE performers SET urls = ?, crawls = crawls + 1, "
                    "last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                    ("|".join(sorted(urls_set)), pid),
                )
            else:
                conn.execute(
                    "UPDATE performers SET crawls = crawls + 1, "
                    "last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                    (pid,),
                )
            conn.commit()
            conn.close()
            return pid, False
        else:
            urls = url if url else ""
            conn.execute(
                "INSERT INTO performers (name, urls, crawls, last_updated) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (name, urls, 1 if url else 0),
            )
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            conn.close()
            return pid, True

    def update_name(self, performer_id: int, name: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE performers SET name = ?, last_updated = CURRENT_TIMESTAMP "
            "WHERE id = ?", (name, performer_id),
        )
        conn.commit()
        conn.close()

    def update_rating(self, performer_id: int, rating: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE performers SET rating = ? WHERE id = ?",
            (rating, performer_id),
        )
        conn.commit()
        conn.close()

    def update_aka(self, performer_id: int, aka: str) -> None:
        conn = self._conn()
        existing = conn.execute(
            "SELECT aka FROM performers WHERE id = ?", (performer_id,)
        ).fetchone()
        if existing and existing["aka"]:
            existing_set = {a.strip() for a in existing["aka"].split(",")}
            new_set = {a.strip() for a in aka.split(",")}
            merged = ", ".join(sorted(existing_set | new_set))
        else:
            merged = aka
        conn.execute(
            "UPDATE performers SET aka = ? WHERE id = ?",
            (merged, performer_id),
        )
        conn.commit()
        conn.close()

    def add_url(self, performer_id: int, url: str) -> None:
        conn = self._conn()
        existing = conn.execute(
            "SELECT urls FROM performers WHERE id = ?", (performer_id,)
        ).fetchone()
        urls_set = set(existing["urls"].split("|")) if existing and existing["urls"] else set()
        if url and url not in urls_set:
            urls_set.add(url)
            conn.execute(
                "UPDATE performers SET urls = ? WHERE id = ?",
                ("|".join(sorted(urls_set)), performer_id),
            )
            conn.commit()
        conn.close()

    def set_validated(self, performer_id: int) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE performers SET validated = 1 WHERE id = ?",
            (performer_id,),
        )
        conn.commit()
        conn.close()

    def set_refdb_status(self, performer_id: int, status: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE performers SET refdb_status = ? WHERE id = ?",
            (status, performer_id),
        )
        conn.commit()
        conn.close()

    def update_seen_dates(self, performer_id: int,
                          publish_date: Optional[str] = None) -> None:
        if not publish_date:
            return
        conn = self._conn()
        existing = conn.execute(
            "SELECT first_seen, last_seen FROM performers WHERE id = ?",
            (performer_id,),
        ).fetchone()
        if not existing:
            conn.close()
            return
        first = existing["first_seen"]
        last = existing["last_seen"]
        if not first or publish_date < first:
            first = publish_date
        if not last or publish_date > last:
            last = publish_date
        conn.execute(
            "UPDATE performers SET first_seen = ?, last_seen = ? WHERE id = ?",
            (first, last, performer_id),
        )
        conn.commit()
        conn.close()

    def delete(self, performer_id: int) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM performer_scenes WHERE performer_id = ?", (performer_id,))
        conn.execute("DELETE FROM performer_features WHERE performer_id = ?", (performer_id,))
        conn.execute("UPDATE items SET performer_id = NULL WHERE performer_id = ?", (performer_id,))
        conn.execute("DELETE FROM performers WHERE id = ?", (performer_id,))
        conn.commit()
        conn.close()

    # ── Items ──

    def get_items(self, performer_id: int,
                  limit: Optional[int] = None) -> List[dict]:
        conn = self._conn()
        query = """
            SELECT id, item_url, title, item_date, hits, added_date, source_file
            FROM items WHERE performer_id = ?
            ORDER BY added_date DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        rows = conn.execute(query, (performer_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_unmatched_items(self, no_name_id: int,
                            limit: Optional[int] = None) -> List[dict]:
        conn = self._conn()
        query = """
            SELECT id, title, item_url, source_file
            FROM items
            WHERE performer_id = ?
            ORDER BY RANDOM()
        """
        if limit:
            query += f" LIMIT {limit}"
        rows = conn.execute(query, (no_name_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def assign_item(self, item_id: int, performer_id: int) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE items SET performer_id = ? WHERE id = ?",
            (performer_id, item_id),
        )
        conn.commit()
        conn.close()

    def unassign_item(self, item_id: int) -> None:
        conn = self._conn()
        conn.execute("UPDATE items SET performer_id = NULL WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()

    def count_items(self, performer_id: int) -> int:
        conn = self._conn()
        cnt = conn.execute(
            "SELECT COUNT(*) FROM items WHERE performer_id = ?",
            (performer_id,),
        ).fetchone()[0]
        conn.close()
        return cnt

    def count_unmatched(self, no_name_id: int) -> int:
        conn = self._conn()
        cnt = conn.execute(
            "SELECT COUNT(*) FROM items WHERE performer_id = ?",
            (no_name_id,),
        ).fetchone()[0]
        conn.close()
        return cnt

    def reassign_items(self, from_id: int, to_id: int) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE items SET performer_id = ? WHERE performer_id = ?",
            (to_id, from_id),
        )
        conn.commit()
        conn.close()

    def delete_item(self, item_id: int) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()

    def get_item_by_id(self, item_id: int) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute("""
            SELECT p.name
            FROM items i
            LEFT JOIN performers p ON i.performer_id = p.id
            WHERE i.id = ?
        """, (item_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    # ── Scenes ──

    def get_scenes(self, performer_id: int) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM performer_scenes WHERE performer_id = ?",
            (performer_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_scene_map(self) -> Dict[str, int]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT scene_url, performer_id FROM performer_scenes"
        ).fetchall()
        conn.close()
        return {r["scene_url"]: r["performer_id"] for r in rows}

    def delete_scenes(self, performer_id: int) -> None:
        conn = self._conn()
        conn.execute(
            "DELETE FROM performer_scenes WHERE performer_id = ?",
            (performer_id,),
        )
        conn.commit()
        conn.close()

    def insert_scene(self, performer_id: int, scene_url: str,
                     scene_title: str) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO performer_scenes "
            "(performer_id, scene_url, scene_title) VALUES (?, ?, ?)",
            (performer_id, scene_url, scene_title),
        )
        conn.commit()
        conn.close()

    def upsert_scenes(self, performer_id: int,
                      scenes: List[Tuple[str, str]]) -> int:
        conn = self._conn()
        conn.execute(
            "DELETE FROM performer_scenes WHERE performer_id = ?",
            (performer_id,),
        )
        count = 0
        for scene_url, scene_title in scenes:
            conn.execute(
                "INSERT OR IGNORE INTO performer_scenes "
                "(performer_id, scene_url, scene_title) VALUES (?, ?, ?)",
                (performer_id, scene_url, scene_title),
            )
            count += 1
        conn.commit()
        conn.close()
        return count

    # ── Features ──

    def get_features(self, performer_id: int) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM performer_features WHERE performer_id = ?",
            (performer_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def upsert_features(self, performer_id: int,
                        nationality: str = "",
                        age: Optional[int] = None,
                        tags: str = "",
                        scene_count: int = 0) -> None:
        conn = self._conn()
        conn.execute("""
            INSERT INTO performer_features (performer_id, nationality, age,
                                            tags, scene_count, last_scraped)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(performer_id) DO UPDATE SET
                nationality = excluded.nationality,
                age = excluded.age,
                tags = excluded.tags,
                scene_count = excluded.scene_count,
                last_scraped = CURRENT_TIMESTAMP
        """, (performer_id, nationality, age, tags, scene_count))
        conn.commit()
        conn.close()

    # ── Merging ──

    def merge(self, keep_id: int, remove_id: int) -> None:
        conn = self._conn()

        # Reassign items
        conn.execute(
            "UPDATE items SET performer_id = ? WHERE performer_id = ?",
            (keep_id, remove_id),
        )

        # Combine URLs
        keep_row = conn.execute(
            "SELECT urls, aka FROM performers WHERE id = ?", (keep_id,)
        ).fetchone()
        remove_row = conn.execute(
            "SELECT urls, aka FROM performers WHERE id = ?", (remove_id,)
        ).fetchone()

        merged_urls = set()
        if keep_row and keep_row["urls"]:
            merged_urls.update(keep_row["urls"].split("|"))
        if remove_row and remove_row["urls"]:
            merged_urls.update(remove_row["urls"].split("|"))

        merged_akas = set()
        if keep_row and keep_row["aka"]:
            merged_akas.update(a.strip() for a in keep_row["aka"].split(","))
        if remove_row and remove_row["aka"]:
            merged_akas.update(a.strip() for a in remove_row["aka"].split(","))

        conn.execute(
            "UPDATE performers SET urls = ?, aka = ? WHERE id = ?",
            ("|".join(sorted(merged_urls)), ", ".join(sorted(merged_akas)), keep_id),
        )

        # Delete scenes + features for removed
        conn.execute("DELETE FROM performer_scenes WHERE performer_id = ?", (remove_id,))
        conn.execute("DELETE FROM performer_features WHERE performer_id = ?", (remove_id,))
        conn.execute("DELETE FROM performers WHERE id = ?", (remove_id,))

        conn.commit()
        conn.close()

    # ── Stats ──

    def get_stats(self) -> dict:
        conn = self._conn()
        stats = {}

        stats["total_performers"] = conn.execute(
            "SELECT COUNT(*) FROM performers"
        ).fetchone()[0]

        stats["total_items"] = conn.execute(
            "SELECT COUNT(*) FROM items"
        ).fetchone()[0]

        stats["dap_performers"] = conn.execute("""
            SELECT COUNT(*) FROM performer_features
            WHERE tags LIKE '%Double anal%' OR tags LIKE '%DAP%'
        """).fetchone()[0]

        stats["total_scenes"] = conn.execute(
            "SELECT COUNT(*) FROM performer_scenes"
        ).fetchone()[0]

        # Rating distribution
        rating_rows = conn.execute(
            "SELECT rating, COUNT(*) as cnt FROM performers "
            "WHERE rating != '' GROUP BY rating"
        ).fetchall()
        stats["rating_distribution"] = {r["rating"]: r["cnt"] for r in rating_rows}

        # Performer count per item count (for histograms)
        stats["item_histogram"] = {}
        rows = conn.execute(
            "SELECT COUNT(*) as cnt FROM items GROUP BY performer_id"
        ).fetchall()
        for r in rows:
            c = r["cnt"]
            bucket = c if c <= 10 else "11+"
            stats["item_histogram"][bucket] = stats["item_histogram"].get(bucket, 0) + 1

        # Numeric average rating (was a raw query in viewer_queries.build_stats_payload)
        avg_numeric = conn.execute("""
            SELECT AVG(CAST(rating AS REAL)) FROM performers
            WHERE rating IS NOT NULL AND rating != ""
            AND (rating GLOB '[0-9]*' OR rating GLOB '[0-9]*.[0-9]*')
        """).fetchone()[0]
        stats["numeric_avg_rating"] = round(avg_numeric, 2) if avg_numeric else 0.0

        conn.close()
        return stats

    def get_stale(self, stale_days: int = 30) -> List[dict]:
        conn = self._conn()
        rows = conn.execute("""
            SELECT p.id, p.name, p.urls, p.last_updated
            FROM performers p
            LEFT JOIN performer_features pf ON pf.performer_id = p.id
            WHERE p.name != 'NO_NAME'
              AND (
                  pf.performer_id IS NULL
                  OR pf.last_scraped < datetime('now', '-' || ? || ' days')
              )
            ORDER BY pf.last_scraped ASC NULLS FIRST
        """, (stale_days,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_profiles_needing_scrape(self, stale_days: int = 30) -> List[dict]:
        """
        Get validated performers with an analvids model page URL
        whose features are missing or stale.
        """
        conn = self._conn()
        rows = conn.execute("""
            SELECT p.id, p.name, i.item_url
            FROM performers p
            JOIN items i ON i.performer_id = p.id AND i.title LIKE 'Model: %'
            LEFT JOIN performer_features pf ON pf.performer_id = p.id
            WHERE p.validated = 1
              AND i.item_url LIKE '%analvids.com/model/%'
              AND (pf.performer_id IS NULL OR pf.last_scraped < datetime('now', '-' || ? || ' days'))
            GROUP BY p.id
            ORDER BY p.name
        """, (stale_days,)).fetchall()
        conn.close()
        return [{"id": r[0], "name": r[1], "url": r[2]} for r in rows]

    # ── Bulk ──

    def bulk_upsert_performers(self, names: List[str]) -> Dict[str, int]:
        """Upsert many performer names, return {name: id}."""
        conn = self._conn()
        result = {}
        for name in names:
            existing = conn.execute(
                "SELECT id FROM performers WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                result[name] = existing["id"]
            else:
                conn.execute(
                    "INSERT INTO performers (name, last_updated) VALUES (?, CURRENT_TIMESTAMP)",
                    (name,),
                )
                result[name] = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        return result

    # ── Unassigned items ──

    def get_unassigned_items(self, sort_by="added_date",
                              sort_order="desc") -> List[dict]:
        allowed = {"id", "item_url", "title", "item_date", "hits", "added_date"}
        if sort_by not in allowed:
            sort_by = "added_date"
        if sort_order not in ("asc", "desc"):
            sort_order = "desc"
        conn = self._conn()
        rows = conn.execute(
            f"SELECT id, item_url, title, item_date, hits, added_date, source_file"
            f" FROM items WHERE performer_id IS NULL ORDER BY {sort_by} {sort_order}"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── Non-performer tags ──

    def get_non_performer_tags(self) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM non_performer_tags ORDER BY tag"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_non_performer_tag(self, tag: str, reason: str = "") -> int:
        conn = self._conn()
        conn.execute(
            "INSERT INTO non_performer_tags (tag, reason) VALUES (?, ?)",
            (tag, reason),
        )
        tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        return tid

    def delete_non_performer_tag(self, tag_id: int) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM non_performer_tags WHERE id = ?", (tag_id,))
        conn.commit()
        conn.close()

    # ── RefDB browsing ──

    def search_refdb(self, q="", nationality="", tag="",
                     age_min=None, age_max=None,
                     has_profile="",
                     sort_by="name", sort_order="asc",
                     page=1, per_page=50) -> dict:
        valid_sort = ["name", "nationality", "age", "scene_count", "years_active"]
        if sort_by not in valid_sort:
            sort_by = "name"
        if sort_order not in ("asc", "desc"):
            sort_order = "asc"

        conditions = []
        params = []
        if q:
            conditions.append("m.name LIKE ?")
            params.append(f"%{q}%")
        if nationality:
            conditions.append("p.nationality = ?")
            params.append(nationality)
        if tag:
            conditions.append("p.tags LIKE ?")
            params.append(f"%{tag}%")
        if age_min is not None:
            conditions.append("p.age >= ?")
            params.append(age_min)
        if age_max is not None:
            conditions.append("p.age <= ?")
            params.append(age_max)
        if has_profile == "yes":
            conditions.append("p.model_id IS NOT NULL")
        elif has_profile == "no":
            conditions.append("p.model_id IS NULL")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        conn = self._conn()
        total = conn.execute(
            f"SELECT COUNT(*) FROM refdb_models m LEFT JOIN refdb_profiles p ON p.model_id = m.id {where}",
            params,
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""SELECT m.id, m.name, m.profile_url, m.scene_count as dir_scene_count,
                       p.nationality, p.age, p.years_active, p.tags,
                       p.scene_count as profile_scene_count, p.last_scraped
                FROM refdb_models m
                LEFT JOIN refdb_profiles p ON p.model_id = m.id
                {where}
                ORDER BY {sort_by} {sort_order}
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()
        conn.close()

        return {
            "data": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    def get_refdb_nationalities(self) -> List[str]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT DISTINCT p.nationality FROM refdb_profiles p"
            " WHERE p.nationality != '' ORDER BY p.nationality"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_refdb_counts(self) -> dict:
        conn = self._conn()
        validated = conn.execute(
            "SELECT COUNT(*) FROM performers WHERE validated = 1"
        ).fetchone()[0]
        scraped = conn.execute(
            "SELECT COUNT(*) FROM performer_features"
        ).fetchone()[0]
        conn.close()
        return {"validated": validated, "scraped": scraped,
                "pending": validated - scraped}

    def get_most_crawled(self, limit: int = 10) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM performers WHERE crawls IS NOT NULL"
            " ORDER BY crawls DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_rated(self) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            'SELECT * FROM performers WHERE rating IS NOT NULL AND rating != ""'
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


    # --- RefDB writes / profile images ---

    def add_to_refdb(self, name: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO refdb_models (name, profile_url) VALUES (?, ?)",
                (name, ""),
            )
            conn.execute(
                "INSERT OR REPLACE INTO refdb_validated_tags (tag, refdb_model_id, match_type) "
                "SELECT ?, id, 'manual' FROM refdb_models WHERE name = ?",
                (name, name),
            )
            conn.commit()
        finally:
            conn.close()

    def get_profile_image(self, name: str) -> Optional[str]:
        if not name:
            return None
        conn = self._conn()
        try:
            img = conn.execute(
                """SELECT pi.local_path FROM performer_images pi
                    JOIN refdb_models m ON m.id = pi.model_id
                    WHERE LOWER(m.name) = LOWER(?) LIMIT 1""",
                (name,),
            ).fetchone()
            return img[0] if img else None
        finally:
            conn.close()

    def save_profile_image(self, model_id: int, image_url: str, local_path: str) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO performer_images "
                "(performer_id, model_id, image_url, local_path, type) "
                "VALUES (?, ?, ?, ?, ?)",
                (None, model_id, image_url, local_path, "profile"),
            )
            conn.commit()
        finally:
            conn.close()

    def compute_refdb_status(self) -> int:
        try:
            from rapidfuzz import fuzz, process
        except ImportError:
            return 0
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT name FROM refdb_models")
        all_names = [row[0] for row in c.fetchall()]
        if not all_names:
            conn.close()
            return 0
        c.execute("SELECT id, name FROM performers WHERE refdb_status IS NULL")
        pending = c.fetchall()
        updated = 0
        for pid, name in pending:
            status = None
            name_lower = name.lower()
            for n in all_names:
                if n.lower() == name_lower:
                    status = "matched"
                    break
            if status is None:
                result = process.extractOne(name, all_names, scorer=fuzz.token_sort_ratio, score_cutoff=88)
                if result:
                    status = "fuzzy"
            if status:
                c.execute("UPDATE performers SET refdb_status = ? WHERE id = ?", (status, pid))
                updated += 1
        conn.commit()
        conn.close()
        return updated


# ── InMemory adapter (for tests) ──────────────────────────


class InMemoryPerformerRepository(PerformerRepository):
    """Test adapter — backed by dicts. No SQLite needed."""

    def __init__(self):
        self._next_pid = 1
        self._next_iid = 1
        self._performers: Dict[int, dict] = {}
        self._items: Dict[int, dict] = {}
        self._scenes: Dict[int, list] = {}  # performer_id -> list of dicts
        self._features: Dict[int, dict] = {}
        self._refdb_names: List[str] = []
        self._refdb_models: Dict[int, dict] = {}
        self._non_performer_tags: Dict[int, dict] = {}
        self._insert_no_name()

    def _insert_no_name(self):
        pid = self._next_pid
        self._next_pid += 1
        self._performers[pid] = {
            "id": pid, "name": "NO_NAME", "urls": "",
            "last_updated": "2026-01-01 00:00:00",
            "crawls": 0, "aka": "", "rating": "",
            "validated": 0, "first_seen": None, "last_seen": None,
            "refdb_status": None,
        }

    def _conn(self):
        """No-op connection stand-in (resolver flushes batches via .commit())."""
        return _NoOpConn()

    def _make_performer(self, name, rating=None, validated=0):
        pid = self._next_pid
        self._next_pid += 1
        self._performers[pid] = {
            "id": pid, "name": name, "urls": "",
            "last_updated": "2026-01-01 00:00:00",
            "crawls": 0, "aka": "", "rating": rating or "",
            "validated": validated, "first_seen": None, "last_seen": None,
            "refdb_status": None,
        }
        return pid

    def ensure_schema(self) -> None:
        pass

    # ── Performers ──

    def search(self, q="", sort_by="name", sort_order="asc",
               show_aliases=False, dap_only=False, limit=None) -> List[dict]:
        results = []
        for p in self._performers.values():
            if not show_aliases and p["crawls"] == 0 and p["validated"] == 0:
                continue
            if dap_only:
                feat = self._features.get(p["id"])
                tags = (feat.get("tags") or "") if feat else ""
                if "Double anal" not in tags and "DAP" not in tags:
                    continue
            if q:
                if q.lower() not in p["name"].lower() and \
                   q.lower() not in (p.get("aka") or "").lower():
                    continue
            d = dict(p)
            feat = self._features.get(p["id"])
            if feat:
                d["nationality"] = feat.get("nationality", "")
                d["age"] = feat.get("age")
                d["tags"] = feat.get("tags", "")
                d["scene_count"] = feat.get("scene_count", 0)
            else:
                d["nationality"] = ""
                d["age"] = None
                d["tags"] = ""
                d["scene_count"] = 0
            d["refdb_match"] = d.pop("refdb_status", None) or "unmatched"
            d["item_count"] = sum(
                1 for it in self._items.values()
                if it.get("performer_id") == p["id"]
            )
            results.append(d)

        reverse = sort_order == "desc"
        if sort_by == "name":
            results.sort(key=lambda x: x["name"], reverse=reverse)
        elif sort_by == "crawls":
            results.sort(key=lambda x: x["crawls"], reverse=reverse)
        elif sort_by == "last_updated":
            results.sort(key=lambda x: x.get("last_updated") or "", reverse=reverse)
        elif sort_by in ("first_seen", "last_seen"):
            results.sort(key=lambda x: x.get(sort_by) or "", reverse=reverse)

        if limit:
            results = results[:int(limit)]
        return results

    def get_by_id(self, performer_id: int) -> Optional[dict]:
        d = self._performers.get(performer_id)
        return dict(d) if d else None

    def get_by_name(self, name: str) -> Optional[dict]:
        for p in self._performers.values():
            if p["name"] == name:
                return dict(p)
        return None

    def get_all(self) -> List[dict]:
        return [{"id": p["id"], "name": p["name"]}
                for p in sorted(self._performers.values(), key=lambda x: x["name"])]

    def get_refdb_names(self) -> List[str]:
        return list(self._refdb_names)

    def get_no_name(self) -> dict:
        for p in self._performers.values():
            if p["name"] == "NO_NAME":
                return dict(p)
        raise ValueError("NO_NAME not found")

    def insert(self, name: str, rating: Optional[str] = None,
               validated: int = 0) -> int:
        return self._make_performer(name, rating, validated)

    def upsert(self, name: str, url: str = "",
               crawl_ts: Optional[int] = None) -> Tuple[int, bool]:
        for p in self._performers.values():
            if p["name"] == name:
                if url and url not in p["urls"].split("|"):
                    p["urls"] = "|".join(sorted(set(p["urls"].split("|")) | {url}))
                p["crawls"] += 1
                return p["id"], False
        pid = self._make_performer(name)
        p = self._performers[pid]
        p["urls"] = url
        p["crawls"] = 1 if url else 0
        return pid, True

    def update_name(self, performer_id: int, name: str) -> None:
        if performer_id in self._performers:
            self._performers[performer_id]["name"] = name

    def update_rating(self, performer_id: int, rating: str) -> None:
        if performer_id in self._performers:
            self._performers[performer_id]["rating"] = rating

    def update_aka(self, performer_id: int, aka: str) -> None:
        if performer_id in self._performers:
            existing = self._performers[performer_id].get("aka", "") or ""
            existing_set = {a.strip() for a in existing.split(",") if a.strip()}
            new_set = {a.strip() for a in aka.split(",") if a.strip()}
            self._performers[performer_id]["aka"] = ", ".join(sorted(existing_set | new_set))

    def add_url(self, performer_id: int, url: str) -> None:
        if performer_id in self._performers:
            p = self._performers[performer_id]
            urls_set = set(p["urls"].split("|")) if p["urls"] else set()
            if url and url not in urls_set:
                urls_set.add(url)
                p["urls"] = "|".join(sorted(urls_set))

    def set_validated(self, performer_id: int) -> None:
        if performer_id in self._performers:
            self._performers[performer_id]["validated"] = 1

    def set_refdb_status(self, performer_id: int, status: str) -> None:
        if performer_id in self._performers:
            self._performers[performer_id]["refdb_status"] = status

    def update_seen_dates(self, performer_id: int,
                          publish_date: Optional[str] = None) -> None:
        if performer_id in self._performers and publish_date:
            p = self._performers[performer_id]
            if not p["first_seen"] or publish_date < p["first_seen"]:
                p["first_seen"] = publish_date
            if not p["last_seen"] or publish_date > p["last_seen"]:
                p["last_seen"] = publish_date

    def delete(self, performer_id: int) -> None:
        self._performers.pop(performer_id, None)
        self._items = {k: v for k, v in self._items.items()
                       if v.get("performer_id") != performer_id}
        self._scenes.pop(performer_id, None)
        self._features.pop(performer_id, None)

    # ── Items ──

    def get_items(self, performer_id: int,
                  limit: Optional[int] = None) -> List[dict]:
        items = [dict(v) for v in self._items.values()
                 if v.get("performer_id") == performer_id]
        items.sort(key=lambda x: x.get("added_date", ""), reverse=True)
        if limit:
            items = items[:int(limit)]
        return items

    def get_unmatched_items(self, no_name_id: int,
                            limit: Optional[int] = None) -> List[dict]:
        from random import shuffle
        items = [dict(v) for v in self._items.values()
                 if v.get("performer_id") == no_name_id]
        shuffle(items)
        if limit:
            items = items[:int(limit)]
        return items

    def assign_item(self, item_id: int, performer_id: int) -> None:
        if item_id in self._items:
            self._items[item_id]["performer_id"] = performer_id

    def unassign_item(self, item_id: int) -> None:
        if item_id in self._items:
            self._items[item_id]["performer_id"] = None

    def count_items(self, performer_id: int) -> int:
        return sum(1 for v in self._items.values()
                   if v.get("performer_id") == performer_id)

    def count_unmatched(self, no_name_id: int) -> int:
        return self.count_items(no_name_id)

    def reassign_items(self, from_id: int, to_id: int) -> None:
        for v in self._items.values():
            if v.get("performer_id") == from_id:
                v["performer_id"] = to_id

    def delete_item(self, item_id: int) -> None:
        self._items.pop(item_id, None)

    def get_item_by_id(self, item_id: int) -> Optional[dict]:
        item = self._items.get(item_id)
        if not item:
            return None
        d = dict(item)
        p = self._performers.get(item.get("performer_id"))
        d["name"] = p["name"] if p else None
        return d

    # ── Scenes ──

    def get_scenes(self, performer_id: int) -> List[dict]:
        return [dict(s) for s in self._scenes.get(performer_id, [])]

    def get_scene_map(self) -> Dict[str, int]:
        m = {}
        for pid, scenes in self._scenes.items():
            for s in scenes:
                m[s["scene_url"]] = pid
        return m

    def delete_scenes(self, performer_id: int) -> None:
        self._scenes.pop(performer_id, None)

    def insert_scene(self, performer_id: int, scene_url: str,
                     scene_title: str) -> None:
        if performer_id not in self._scenes:
            self._scenes[performer_id] = []
        urls = {s["scene_url"] for s in self._scenes[performer_id]}
        if scene_url not in urls:
            self._scenes[performer_id].append({
                "performer_id": performer_id,
                "scene_url": scene_url,
                "scene_title": scene_title,
            })

    def upsert_scenes(self, performer_id: int,
                      scenes: List[Tuple[str, str]]) -> int:
        self._scenes[performer_id] = []
        count = 0
        urls_seen = set()
        for scene_url, scene_title in scenes:
            if scene_url not in urls_seen:
                self._scenes[performer_id].append({
                    "performer_id": performer_id,
                    "scene_url": scene_url,
                    "scene_title": scene_title,
                })
                urls_seen.add(scene_url)
                count += 1
        return count

    # ── Features ──

    def get_features(self, performer_id: int) -> Optional[dict]:
        d = self._features.get(performer_id)
        return dict(d) if d else None

    def upsert_features(self, performer_id: int,
                        nationality: str = "",
                        age: Optional[int] = None,
                        tags: str = "",
                        scene_count: int = 0) -> None:
        self._features[performer_id] = {
            "performer_id": performer_id,
            "nationality": nationality,
            "age": age,
            "tags": tags,
            "scene_count": scene_count,
        }

    # ── Merging ──

    def merge(self, keep_id: int, remove_id: int) -> None:
        self.reassign_items(remove_id, keep_id)
        keep = self._performers.get(keep_id)
        remove = self._performers.get(remove_id)
        if keep and remove:
            merged_urls = set(keep["urls"].split("|")) | set(remove["urls"].split("|"))
            keep_akas = {a.strip() for a in (keep["aka"] or "").split(",") if a.strip()}
            remove_akas = {a.strip() for a in (remove["aka"] or "").split(",") if a.strip()}
            keep["urls"] = "|".join(sorted(merged_urls))
            keep["aka"] = ", ".join(sorted(keep_akas | remove_akas))
        self.delete(remove_id)

    # ── Stats ──

    def get_stats(self) -> dict:
        total_p = len(self._performers)
        total_i = len(self._items)
        dap_count = sum(1 for f in self._features.values()
                        if "Double anal" in f.get("tags", "")
                        or "DAP" in f.get("tags", ""))
        scene_count = sum(len(s) for s in self._scenes.values())
        rating_dist = {}
        for p in self._performers.values():
            r = p.get("rating", "")
            if r:
                rating_dist[r] = rating_dist.get(r, 0) + 1
        item_hist = {}
        pid_counts = {}
        for v in self._items.values():
            pid = v.get("performer_id")
            if pid:
                pid_counts[pid] = pid_counts.get(pid, 0) + 1
        for c in pid_counts.values():
            bucket = c if c <= 10 else "11+"
            item_hist[bucket] = item_hist.get(bucket, 0) + 1
        nums = []
        for p in self._performers.values():
            r = p.get("rating", "")
            try:
                nums.append(float(r))
            except (ValueError, TypeError):
                pass
        numeric_avg = round(sum(nums) / len(nums), 2) if nums else 0.0

        return {
            "total_performers": total_p,
            "total_items": total_i,
            "dap_performers": dap_count,
            "total_scenes": scene_count,
            "rating_distribution": rating_dist,
            "item_histogram": item_hist,
            "numeric_avg_rating": numeric_avg,
        }

    # --- RefDB writes / profile images ---

    def add_to_refdb(self, name: str) -> None:
        if any(m["name"].lower() == name.lower() for m in self._refdb_models.values()):
            return
        mid = len(self._refdb_models) + 1
        self._refdb_models[mid] = {"name": name, "image": None}
        self._refdb_names.append(name)

    def get_profile_image(self, name: str) -> Optional[str]:
        if not name:
            return None
        for m in self._refdb_models.values():
            if m["name"].lower() == name.lower():
                return m["image"]
        return None

    def save_profile_image(self, model_id: int, image_url: str, local_path: str) -> None:
        if model_id in self._refdb_models:
            self._refdb_models[model_id]["image"] = local_path

    def compute_refdb_status(self) -> int:
        updated = 0
        for p in self._performers.values():
            if p.get("refdb_status") is not None:
                continue
            status = None
            name_lower = p["name"].lower()
            for n in self._refdb_names:
                if n.lower() == name_lower:
                    status = "matched"
                    break
            if status:
                p["refdb_status"] = status
                updated += 1
        return updated

    def get_stale(self, stale_days: int = 30) -> List[dict]:
        results = []
        for p in self._performers.values():
            if p["name"] == "NO_NAME":
                continue
            feat = self._features.get(p["id"])
            if feat is None:
                results.append(dict(p))
        return results

    def get_profiles_needing_scrape(self, stale_days: int = 30) -> List[dict]:
        results = []
        for p in self._performers.values():
            if p["name"] == "NO_NAME" or not p.get("validated"):
                continue
            # Check if any item has model URL
            has_model_url = False
            for item in self._items.values():
                if item.get("performer_id") == p["id"] and \
                   (item.get("title") or "").startswith("Model:") and \
                   "analvids.com/model" in (item.get("item_url") or ""):
                    has_model_url = True
                    break
            if not has_model_url:
                continue
            feat = self._features.get(p["id"])
            if feat is None:
                results.append({"id": p["id"], "name": p["name"], "url": None})
        return results

    def bulk_upsert_performers(self, names: List[str]) -> Dict[str, int]:
        result = {}
        for name in names:
            existing = self.get_by_name(name)
            if existing:
                result[name] = existing["id"]
            else:
                result[name] = self._make_performer(name)
        return result

    # ── Unassigned items ──

    def get_unassigned_items(self, sort_by="added_date",
                              sort_order="desc") -> List[dict]:
        allowed = {"id", "item_url", "title", "item_date", "hits", "added_date"}
        if sort_by not in allowed:
            sort_by = "added_date"
        items = [dict(v) for v in self._items.values()
                 if v.get("performer_id") is None]
        reverse = sort_order == "desc"
        items.sort(key=lambda x: x.get(sort_by, "") or "", reverse=reverse)
        return items

    # ── Non-performer tags ──

    def get_non_performer_tags(self) -> List[dict]:
        return list(self._non_performer_tags.values())

    def add_non_performer_tag(self, tag: str, reason: str = "") -> int:
        tid = len(self._non_performer_tags) + 1
        self._non_performer_tags[tid] = {"id": tid, "tag": tag, "reason": reason}
        return tid

    def delete_non_performer_tag(self, tag_id: int) -> None:
        self._non_performer_tags.pop(tag_id, None)

    # ── RefDB browsing ──

    def search_refdb(self, q="", nationality="", tag="",
                     age_min=None, age_max=None,
                     has_profile="",
                     sort_by="name", sort_order="asc",
                     page=1, per_page=50) -> dict:
        return {"data": [], "total": 0, "page": page, "per_page": per_page}

    def get_refdb_nationalities(self) -> List[str]:
        return []

    def get_refdb_counts(self) -> dict:
        validated = sum(1 for p in self._performers.values() if p.get("validated"))
        scraped = len(self._features)
        return {"validated": validated, "scraped": scraped,
                "pending": validated - scraped}

    def get_most_crawled(self, limit: int = 10) -> List[dict]:
        sorted_p = sorted(
            self._performers.values(),
            key=lambda x: x.get("crawls", 0) or 0,
            reverse=True,
        )[:limit]
        return [dict(p) for p in sorted_p]

    def get_all_rated(self) -> List[dict]:
        return [dict(p) for p in self._performers.values()
                if p.get("rating")]
