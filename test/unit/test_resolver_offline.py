"""Offline tests for the NO_NAME resolver.

These prove the resolver depends only on the two ports
(``PerformerRepository``, ``LLMClient``) and not on a live DB, network, or
global mutable state:

  * ``phase2_hybrid_assign`` and ``run_llm_pass`` run end-to-end against
    ``InMemoryPerformerRepository`` + ``FakeLLMClient``.
  * ADR-0001: the resolver never creates performers. When the LLM
    "extracts" a name that is NOT in the database, the item is skipped
    and the performer count is unchanged — for both the hinted path
    (phase 2) and the open-ended path (run_llm_pass).
  * The LLM call sites route through ``LLMClient.complete`` (verified
    with the ``FakeLLMClient`` test double).

Run with:  uv run pytest test/unit/test_resolver_offline.py -v
"""

import sqlite3
from typing import Optional
from unittest import mock

import pytest

import resolve_nonames_cli as R
from llm_client import FakeLLMClient
from performer_repository import InMemoryPerformerRepository, SqlitePerformerRepository


# ── Helpers ────────────────────────────────────────────────

def _make_repo() -> InMemoryPerformerRepository:
    """Repo with one known performer + NO_NAME. No refdb names.

    Uses a lowercased, clearly-valid name ("mia kalani") so the fuzzy and
    open-ended validators pass without fighting production STOP-word /
    short-name rules.
    """
    repo = InMemoryPerformerRepository()
    repo.insert("mia kalani")   # pid 1
    return repo


def _known(repo: InMemoryPerformerRepository):
    known_ids = {p["name"]: p["id"] for p in repo.get_all() if p["name"] != "NO_NAME"}
    known_names = list(known_ids.keys())
    perf_multi = [(n.lower().replace(" ", "_"), n, n) for n in known_names]
    return known_ids, known_names, perf_multi


def _collector():
    results = []
    fn = lambda iid, pid, name, url, title, method: results.append(
        {"item_id": iid, "performer_id": pid, "name": name, "method": method}
    )
    return results, fn


# ── Tests ──────────────────────────────────────────────────

def test_load_refdb_slugs_through_repo_port():
    repo = InMemoryPerformerRepository()
    repo._refdb_names = [
        "Anna De Ville",
        "Braziliana",
        "ShyyFxx tu Gauchita Argentina",
    ]
    multi, single = R.load_refdb_slugs(repo)
    # 2-word+ names become multi; single long word becomes single
    assert ("anna_de_ville", "Anna De Ville") in multi
    assert ("shyyfxx_tu_gauchita_argentina", "ShyyFxx tu Gauchita Argentina") in multi
    assert ("braziliana", "Braziliana") in single


def test_llm_functions_route_through_fake_client():
    # llm_extract returns the name verbatim
    assert R.llm_extract("Anna De Ville solo anal", FakeLLMClient(["Anna De Ville"])) == "Anna De Ville"
    # llm_hinted_extract expects the LLM to reply with the CHOICE INDEX
    assert R.llm_hinted_extract("title", "slug", ["Anna De Ville", "Mia Kai"],
                                FakeLLMClient(["1"])) == "Anna De Ville"
    # NONE is rejected by every extractor
    none = FakeLLMClient(["NONE"])
    assert R.llm_extract("big ass compilation", none) is None
    assert R.llm_try_extract("random junk", none) is None


def test_phase2_llm_hinted_match_exercises_port_no_creation():
    repo = _make_repo()
    known_ids, known_names, perf_multi = _known(repo)
    # refdb empty so Stage 1 never matches. Stage 2 fuzzy-feeds Stage 3 hints.
    # Both the slug and the fuzzy pool are lowercased (as in production) so the
    # case-sensitive partial_ratio clears its cutoff and Stage 3 fires. The
    # hinted branch matches by substring, so case is irrelevant there.
    item = {"id": 1001, "item_url":
            "https://sxyprn.com/post/watch_mia_kalani_hot_scene_with_friend_"
            "doing_anal_today_now", "title": "A random clip title"}
    results, save = _collector()
    with mock.patch.object(R, "save_result", save):
        assigned = R.phase2_hybrid_assign(
            repo, [item], known_ids, known_names, perf_multi, [], [], [],
            {}, FakeLLMClient(["1"]),   # index 1 -> candidate 0 == "mia kalani"
        )
    assert assigned == 1
    # Matched an EXISTING performer; nothing created.
    assert len(repo._performers) == 2  # NO_NAME + mia kalani
    assert results[0]["performer_id"] == known_ids["mia kalani"]
    assert results[0]["method"] == "llm-hinted"


def test_phase2_refdb_slug_unknown_never_creates():
    """ADR-0001 (Stage 1): a refdb-slug match for an unknown name skips."""
    repo = _make_repo()
    before = len(repo._performers)
    # known_ids deliberately EXCLUDES "zelda knew" so the refdb match cannot resolve
    known_ids = {"mia kalani": 1}
    known_names = ["mia kalani"]
    perf_multi = [("mia_kalani", "mia kalani", "mia kalani")]
    # refdb name NOT in known_ids, but slug matches it exactly
    refdb_multi = [("zelda_knew", "zelda knew")]
    item = {"id": 1002, "item_url":
            "https://sxyprn.com/post/zelda_knew_hot_scene", "title": "clip"}
    results, save = _collector()
    with mock.patch.object(R, "save_result", save):
        assigned = R.phase2_hybrid_assign(
            repo, [item], known_ids, known_names, perf_multi, [], refdb_multi, [],
            {}, FakeLLMClient(["NONE"]),
        )
    assert assigned == 0
    assert len(repo._performers) == before  # no creation


def test_run_llm_pass_unknown_name_never_creates():
    """ADR-0001 (open-ended): LLM returns a name absent from the DB.

    The item must be left unassigned and the performer table unchanged.
    This is the path that previously ran ``INSERT INTO performers``.
    """
    repo = _make_repo()
    before = len(repo._performers)
    known_ids, known_names, _ = _known(repo)
    item = {
        "id": 2001,
        "item_url": "https://sxyprn.com/post/completely_unknown_name_video",
        "title": "Completely Unknown Name hot scene",
    }
    results, save = _collector()
    with mock.patch.object(R, "save_result", save):
        assigned = R.run_llm_pass(
            repo, FakeLLMClient(["Completely Unknown Name"]),
            [item], known_ids, known_names, [], [],
        )
    assert assigned == 0
    assert len(repo._performers) == before  # crucial: no new performer
    assert results and results[0]["performer_id"] is None
    assert results[0]["method"] == "llm-fail"


def test_run_llm_pass_known_name_matches_no_creation():
    # The open-ended validator expects a Title-Cased LLM output
    # (first letter upper) and matches the DB's Title-Cased key.
    repo = InMemoryPerformerRepository()
    repo.insert("Mia Kalani")   # pid 1
    known_ids = {"Mia Kalani": 1}
    known_names = ["Mia Kalani"]
    item = {
        "id": 2002,
        "item_url": "https://sxyprn.com/post/mia_kalani_video",
        "title": "Mia Kalani hot scene",
    }
    results, save = _collector()
    with mock.patch.object(R, "save_result", save):
        assigned = R.run_llm_pass(
            repo, FakeLLMClient(["Mia Kalani"]),
            [item], known_ids, known_names, [], [],
        )
    assert assigned == 1
    assert len(repo._performers) == 2  # unchanged (matched existing)
    assert results[0]["performer_id"] == known_ids["Mia Kalani"]


# ── Real-DB helpers (ADR enforcement + apply round-trip) ──

def _count_performers(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM performers").fetchone()[0]
    conn.close()
    return n


def _item_performer(db_path: str, item_id: int) -> Optional[int]:
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT performer_id FROM items WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def test_run_llm_pass_adds_no_performer_to_real_db(tmp_path):
    """ADR-0001 enforced via the REAL write path (not just the in-memory dict).

    The deleted creation code wrote to the real ``performers.db`` via raw
    ``sqlite3.connect``, bypassing the in-memory repo. A reintroduced raw
    INSERT adds a row to the real table; this test catches that regression
    by counting rows in a temp SQLite DB.
    """
    db = str(tmp_path / "perf.db")
    repo = SqlitePerformerRepository(db)
    pid = repo.insert("Mia Kalani")
    known_ids = {"Mia Kalani": pid}
    known_names = ["Mia Kalani"]
    item = {
        "id": 9001,
        "item_url": "https://sxyprn.com/post/completely_unknown_name_video",
        "title": "Completely Unknown Name hot scene",
    }
    before = _count_performers(db)
    R.run_llm_pass(repo, FakeLLMClient(["Completely Unknown Name"]),
                   [item], known_ids, known_names, [], [])
    assert _count_performers(db) == before  # no row written to performers table


def test_run_llm_pass_persists_via_save_and_apply(tmp_path):
    """Real save_result -> load_results -> apply_all_results round-trip.

    Exercises the actual JSONL output and the apply step against a real
    SQLite repo (the production data path the other tests mock away).
    """
    db = str(tmp_path / "perf.db")
    repo = SqlitePerformerRepository(db)
    pid = repo.insert("Mia Kalani")
    # Insert an item directly (dbadd.create_db's items schema lacks the
    # thumbnail_url column insert_item expects; irrelevant to this test).
    conn = repo._conn()
    conn.execute(
        "INSERT INTO items (item_url, title, performer_id) VALUES (?, ?, NULL)",
        ("https://sxyprn.com/post/mia_kalani_video", "Mia Kalani hot scene"),
    )
    item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    before = _count_performers(db)
    known_ids = {"Mia Kalani": pid}
    known_names = ["Mia Kalani"]
    results_file = str(tmp_path / "results.jsonl")
    orig = R.RESULTS_FILE
    R.RESULTS_FILE = results_file
    try:
        R.run_llm_pass(
            repo, FakeLLMClient(["Mia Kalani"]),
            [{"id": item_id, "item_url": "https://sxyprn.com/post/mia_kalani_video",
              "title": "Mia Kalani hot scene"}],
            known_ids, known_names, [], [],
        )
        # The resolver wrote a real, parseable JSONL
        saved = R.load_results()
        assert len(saved) == 1
        assert saved[0]["performer_id"] == pid
        # Apply step consumes it against the real repo
        R.apply_all_results(repo)
    finally:
        R.RESULTS_FILE = orig
    # Item actually assigned in the real DB, no performer created
    assert _item_performer(db, item_id) == pid
    assert _count_performers(db) == before  # NO_NAME not seeded; only Mia Kalani


def test_insert_item_on_fresh_db_has_thumbnail_column(tmp_path):
    """Regression for the latent bug: create_db's items table was missing the
    ``thumbnail_url`` column that insert_item (and the thumb scripts) expect.
    insert_item on a fresh DB raised OperationalError before the fix.
    """
    db = str(tmp_path / "perf.db")
    repo = SqlitePerformerRepository(db)
    iid = repo.insert_item(item_url="https://sxyprn.com/post/foo", title="Foo video")
    assert isinstance(iid, int) and iid >= 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT item_url, thumbnail_url FROM items WHERE id = ?", (iid,)
    ).fetchone()
    conn.close()
    assert row[0] == "https://sxyprn.com/post/foo"
    assert row[1] == ""  # column now exists; insert_item defaults it to empty string


def test_fast_match_item_slug_substring():
    """Deterministic Phase-1 slug matching (the production workhorse)."""
    multi = [("anna_de_ville", 1, "Anna De Ville")]
    single = []
    hit = R.fast_match_item("https://sxyprn.com/post/anna_de_ville_hot", "t", multi, single)
    assert hit == ("Anna De Ville", 1, 100)
    assert R.fast_match_item("https://sxyprn.com/post/random", "t", multi, single) is None


def test_phase1_fast_auto_assign_no_creation():
    """Deterministic Phase-1 matching assigns via the repo port, never creates."""
    repo = InMemoryPerformerRepository()
    pid = repo.insert("mia kalani")
    known_ids = {"mia kalani": pid}
    multi = [("mia_kalani", pid, "mia kalani")]
    item = {"id": 1, "item_url": "https://sxyprn.com/post/mia_kalani_video", "title": "x"}
    results, save = _collector()
    with mock.patch.object(R, "save_result", save):
        assigned = R.phase1_fast_auto_assign(repo, [item], known_ids, multi, [], {})
    assert assigned == 1
    assert results[0]["performer_id"] == pid
    assert len(repo._performers) == 2  # NO_NAME + mia kalani (no creation)


def test_match_item_slug_and_no_match():
    multi = [("anna_de_ville", 7, "Anna De Ville")]
    single = []
    known_names = ["Anna De Ville"]
    known_ids = {"Anna De Ville": 7}
    res = R.match_item("https://x/post/anna_de_ville_hot", "title here", multi, single, known_names, known_ids)
    assert res and res[0][0] == "Anna De Ville"
    assert R.match_item("https://x/post/random", "title here", multi, single, known_names, known_ids) == []


def test_llm_extract_prompt_contains_title():
    """#5: the resolver builds the right prompt (not just any response)."""
    fake = FakeLLMClient(["Anna De Ville"])
    R.llm_extract("Anna De Ville solo anal", fake)
    content = fake.calls[-1]["messages"][0]["content"]
    assert "Anna De Ville solo anal" in content


def test_llm_hinted_prompt_contains_candidates():
    fake = FakeLLMClient(["1"])
    R.llm_hinted_extract("some title", "slug", ["Anna De Ville", "Mia Kai"], fake)
    content = fake.calls[-1]["messages"][0]["content"]
    assert "Anna De Ville" in content and "Mia Kai" in content
