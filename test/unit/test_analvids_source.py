"""Tests for the AnalvidsSource port (candidate B).

Locks the port's contract and the Fake double. No network: the production
``ScrapingAnalvidsSource`` is only checked for conformance (it is an
``AnalvidsSource``); its HTTP behaviour is exercised live, not here.
"""

from analvids_source import AnalvidsSource, FakeAnalvidsSource, ScrapingAnalvidsSource


def test_fake_is_analvids_source():
    assert isinstance(FakeAnalvidsSource(), AnalvidsSource)


def test_scraping_is_analvids_source():
    assert isinstance(ScrapingAnalvidsSource(), AnalvidsSource)


def test_fake_search_returns_canned_results():
    results = [{"name": "X", "url": "u", "model_id": 1}]
    fake = FakeAnalvidsSource(search_results=results)
    out = fake.search("foo")
    assert out == {"results": results}
    assert fake.search_calls == ["foo"]


def test_fake_search_error_path():
    fake = FakeAnalvidsSource(search_error="boom")
    out = fake.search("foo")
    assert out == {"results": [], "error": "boom"}


def test_fake_fetch_profile_returns_canned_and_records_call():
    profile = {"name": "X", "model_id": 1, "local_image": "/i/1.webp"}
    fake = FakeAnalvidsSource(profile=profile)
    assert fake.fetch_profile("http://x") == profile
    assert fake.fetch_calls == ["http://x"]


def test_fake_fetch_profile_error_path():
    fake = FakeAnalvidsSource(profile_error="nope")
    assert fake.fetch_profile("anything") == {"error": "nope"}


def test_contract_shape():
    # The webapp branches on "error" in result; both methods must return a dict.
    fake = FakeAnalvidsSource(search_results=[{"name": "A"}], profile={"name": "A"})
    assert isinstance(fake.search("q"), dict)
    assert isinstance(fake.fetch_profile("r"), dict)
