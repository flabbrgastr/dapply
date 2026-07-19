"""Tests for the db_viewer split (routes / queries / rendering layers).

Locks the Flask route contract and covers the pure presentation helpers.
No network, no writes to the real database.
"""

import pytest

import db_viewer
from performer_repository import InMemoryPerformerRepository, SqlitePerformerRepository
from analvids_source import FakeAnalvidsSource
import viewer_queries
import rating


# Every (method, rule) the live web UI must expose. The split must not drop
# or rename any of these — this guards against accidental route loss.
EXPECTED_ROUTES = {
    ("GET", "/"),
    ("GET", "/api/performers"),
    ("POST", "/api/performers"),
    ("PUT", "/api/performers/<int:performer_id>"),
    ("DELETE", "/api/performers/<int:performer_id>"),
    ("POST", "/api/performers/<int:performer_id>/confirm"),
    ("POST", "/api/performers/<int:performer_id>/reassign"),
    ("POST", "/api/items/<int:item_id>/reassign"),
    ("POST", "/api/items/<int:item_id>/unassign"),
    ("DELETE", "/api/items/<int:item_id>"),
    ("GET", "/api/performers/unassigned/items"),
    ("GET", "/api/performers/lookup-analvids"),
    ("GET", "/api/performers/lookup-analvids-url"),
    ("GET", "/api/performers/<int:performer_id>/features"),
    ("GET", "/api/performers/<int:performer_id>/items"),
    ("GET", "/api/refdb/performers"),
    ("GET", "/api/non-performer-tags"),
    ("POST", "/api/non-performer-tags"),
    ("DELETE", "/api/non-performer-tags/<int:tag_id>"),
    ("GET", "/api/refdb"),
    ("GET", "/stats"),
    ("GET", "/api/stats"),
    ("POST", "/api/performers/refresh-refdb"),
}


def _registered_routes():
    rules = db_viewer.app.url_map.iter_rules()
    return {(sorted(r.methods - {"HEAD", "OPTIONS"})[0], r.rule) for r in rules
            if r.rule != "/static/<path:filename>"}


def test_app_imports_and_repo_is_repository():
    # The default production app injects the SQLite adapter.
    assert isinstance(db_viewer.app.config["REPO"], SqlitePerformerRepository)


def test_all_routes_registered():
    registered = _registered_routes()
    missing = EXPECTED_ROUTES - registered
    assert not missing, f"missing routes: {missing}"


def test_create_app_injects_provided_repo():
    # Candidate C: the factory accepts an injected port, so the webapp is
    # drivable without the production database.
    fake = InMemoryPerformerRepository()
    app = db_viewer.create_app(fake)
    assert app.config["REPO"] is fake


def test_performers_route_returns_seeded_data():
    # End-to-end: seed the injected repo, hit the route via the test client.
    repo = InMemoryPerformerRepository()
    pid = repo.insert("Test Star", "9.0")
    repo.set_validated(pid)
    client = db_viewer.create_app(repo).test_client()

    resp = client.get("/api/performers")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.get_json()]
    assert "Test Star" in names


def test_stats_route_returns_numeric_avg():
    repo = InMemoryPerformerRepository()
    repo.insert("Star A", "9.0")
    repo.insert("Star B", "8.0")
    client = db_viewer.create_app(repo).test_client()

    resp = client.get("/api/stats")
    assert resp.status_code == 200
    assert resp.get_json()["numeric_avg_rating"] == 8.5


def test_index_route_renders():
    client = db_viewer.create_app(InMemoryPerformerRepository()).test_client()
    resp = client.get("/")
    assert resp.status_code == 200


def test_lookup_analvids_returns_canned_results():
    # Candidate B: the analvids source is injected, so the lookup route is
    # exercisable without network.
    fake = FakeAnalvidsSource(
        search_results=[{"name": "Canned Model", "url": "http://x", "model_id": 7}]
    )
    client = db_viewer.create_app(InMemoryPerformerRepository(), analvids=fake).test_client()
    resp = client.get("/api/performers/lookup-analvids?q=foo")
    assert resp.status_code == 200
    results = resp.get_json()["results"]
    assert results[0]["name"] == "Canned Model"
    assert fake.search_calls == ["foo"]


def test_lookup_analvids_url_persists_cached_image():
    # The route composes the source with the repo: the cached image returned
    # by the source is persisted through the repository port.
    repo = InMemoryPerformerRepository()
    repo.add_to_refdb("Canned Model")  # refdb model id 1
    fake = FakeAnalvidsSource(
        profile={
            "name": "Canned Model", "url": "http://x", "model_id": 1,
            "scenes": 3, "nationality": "US", "image": "http://img",
            "local_image": "/performers/static/images/1.webp",
        }
    )
    client = db_viewer.create_app(repo, analvids=fake).test_client()
    resp = client.get("/api/performers/lookup-analvids-url?url=http://x")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Canned Model"
    assert repo.get_profile_image("Canned Model") == "/performers/static/images/1.webp"


def test_query_layer_is_importable_without_flask_running():
    # viewer_queries owns only the stats payload now; the analvids lookups
    # live behind the AnalvidsSource port.
    assert hasattr(viewer_queries, "build_stats_payload")
    import analvids_source
    assert hasattr(analvids_source, "ScrapingAnalvidsSource")
    assert hasattr(analvids_source, "FakeAnalvidsSource")


def test_rating_sort_key_ordering():
    # Higher tier -> higher numeric key; numeric ratings sort numerically.
    assert rating.rating_sort_key("AAA") > rating.rating_sort_key("BBB")
    assert rating.rating_sort_key("BBB") > rating.rating_sort_key("C")
    assert rating.rating_sort_key("9.5") == 9.5
    assert rating.rating_sort_key(None) == float("-inf")
    assert rating.rating_sort_key("") == float("-inf")


def test_rating_category():
    assert rating.rating_category("AAA") == "AAA"
    assert rating.rating_category("B+") == "B+"
    assert rating.rating_category("9.5") == "9-10 (Numeric)"
    assert rating.rating_category("") == "No Rating"


def test_rating_hierarchy_ordering():
    # Lower index == higher tier.
    h = rating.RATING_HIERARCHY
    assert h["AAA"] < h["A"] < h["BBB"] < h["C"] < h["No Rating"]
