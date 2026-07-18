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

from unittest import mock

import pytest

import resolve_nonames_cli as R
from llm_client import FakeLLMClient
from performer_repository import InMemoryPerformerRepository


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
