"""Tests for the Rating domain module (candidate D)."""

from rating import RATING_HIERARCHY, Rating, rating_category, rating_sort_key


def test_parse_empty_and_none():
    assert Rating.parse(None).is_empty
    assert Rating.parse("").is_empty
    assert Rating.parse("").category == "No Rating"
    assert Rating.parse(None).sort_key == float("-inf")


def test_parse_numeric():
    r = Rating.parse("9.5")
    assert r.is_numeric
    assert r.sort_key == 9.5
    assert r.category == "9-10 (Numeric)"
    assert not r.is_empty


def test_parse_alphabetical_tiers_and_signs():
    assert Rating.parse("AAA").sort_key == 109.0
    assert Rating.parse("AAA+").sort_key == 110.0
    assert Rating.parse("AAA-").sort_key == 108.0
    assert Rating.parse("C").sort_key == 77.0
    assert Rating.parse("C+").sort_key == 78.0
    assert Rating.parse("C-").sort_key == 76.0
    assert Rating.parse("E").sort_key == 53.0
    assert Rating.parse("B+").category == "B+"


def test_parse_unknown_is_other():
    r = Rating.parse("???")
    assert r.category == "Other"
    assert r.sort_key == 40.0


def test_ordering():
    # Higher tier ranks higher.
    assert Rating.parse("AAA") > Rating.parse("BBB") > Rating.parse("C") > Rating.parse("E")
    # +/- adjusts within a tier.
    assert Rating.parse("AAA+") > Rating.parse("AAA") > Rating.parse("AAA-")
    # Alphabetical always ranks above numeric (different key ranges).
    assert Rating.parse("E") > Rating.parse("9.9")
    # Numeric ordered by value.
    assert Rating.parse("9.5") > Rating.parse("8.0")
    # Empty is lowest.
    assert Rating.parse("AAA") > Rating.parse("")


def test_convenience_wrappers_match_class():
    assert rating_sort_key("AAA") == Rating.parse("AAA").sort_key
    assert rating_category("B+") == Rating.parse("B+").category
    assert rating_category("") == "No Rating"


def test_hierarchy_ordering():
    h = RATING_HIERARCHY
    assert h["AAA"] < h["A"] < h["BBB"] < h["C"] < h["No Rating"]
