"""
Rating domain module.

A performer rating is either an alphabetical tier (``AAA``..``E``, each with an
optional ``+``/``-``) or a numeric score (``0``-``10``). ``Rating`` is the value
object for a parsed rating; ``RATING_HIERARCHY`` orders the categories for
display. Pure — no Flask, no database, no network.
"""

from typing import Optional

# Category ordering for the stats distribution. Higher index == "better".
RATING_HIERARCHY = {
    name: i for i, name in enumerate([
        "AAA+", "AAA", "AAA-", "AA+", "AA", "AA-",
        "A+", "A", "A-", "BBB+", "BBB", "BBB-",
        "BB+", "BB", "BB-", "B+", "B", "B-",
        "CCC+", "CCC", "CCC-", "CC+", "CC", "CC-",
        "C+", "C", "C-", "DDD+", "DDD", "DDD-",
        "DD+", "DD", "DD-", "D+", "D", "D-",
        "EEE+", "EEE", "EEE-", "EE+", "EE", "EE-",
        "E+", "E", "E-",
        "9-10 (Numeric)", "7-9 (Numeric)", "5-7 (Numeric)",
        "3-5 (Numeric)", "0-3 (Numeric)", "Other", "No Rating",
    ])
}

# Base sort key per alphabetical prefix (no +/-). Numeric ratings use their own
# value (0-10), so alphabetical tiers (≈50-110) always rank above them.
_ALPHA_BASE = {
    "AAA": 109.0, "AA": 105.0, "A": 101.0,
    "BBB": 97.0, "BB": 93.0, "B": 89.0,
    "CCC": 85.0, "CC": 81.0, "C": 77.0,
    "DDD": 73.0, "DD": 69.0, "D": 65.0,
    "EEE": 61.0, "EE": 57.0, "E": 53.0,
}
_PREFIXES = ("AAA", "AA", "A", "BBB", "BB", "B", "CCC", "CC", "C",
             "DDD", "DD", "D", "EEE", "EE", "E")


class Rating:
    """A parsed performer rating (alphabetical tier or numeric score)."""

    __slots__ = ("raw", "sort_key", "category", "is_numeric", "is_empty")

    def __init__(self, raw: str, sort_key: float, category: str,
                 is_numeric: bool, is_empty: bool) -> None:
        self.raw = raw
        self.sort_key = sort_key
        self.category = category
        self.is_numeric = is_numeric
        self.is_empty = is_empty

    @classmethod
    def parse(cls, raw: Optional[str]) -> "Rating":
        """Parse a raw rating string into a Rating. Never raises."""
        if raw is None or raw == "":
            return cls("", float("-inf"), "No Rating", False, True)
        try:
            num = float(raw)
            if num >= 9:
                cat = "9-10 (Numeric)"
            elif num >= 7:
                cat = "7-9 (Numeric)"
            elif num >= 5:
                cat = "5-7 (Numeric)"
            elif num >= 3:
                cat = "3-5 (Numeric)"
            else:
                cat = "0-3 (Numeric)"
            return cls(raw, num, cat, True, False)
        except ValueError:
            ru = raw.upper().strip()
            base = None
            prefix = ""
            plus = minus = False
            for p in _PREFIXES:
                if ru.startswith(p):
                    base = _ALPHA_BASE[p]
                    prefix = p
                    rest = ru[len(p):]
                    if rest.startswith("+"):
                        plus = True
                    elif rest.startswith("-"):
                        minus = True
                    break
            if base is None:
                return cls(raw, 40.0, "Other", False, False)
            adj = 1.0 if plus else (-1.0 if minus else 0.0)
            tier = prefix + ("+" if plus else ("-" if minus else ""))
            return cls(raw, base + adj, tier, False, False)

    def __lt__(self, other: "Rating") -> bool:
        if not isinstance(other, Rating):
            return NotImplemented
        return self.sort_key < other.sort_key

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Rating):
            return NotImplemented
        return self.sort_key == other.sort_key and self.raw == other.raw

    def __hash__(self) -> int:
        return hash((self.raw, self.sort_key))

    def __repr__(self) -> str:
        return f"Rating({self.raw!r})"


def rating_sort_key(raw: Optional[str]) -> float:
    """Convenience: sort key for a raw rating (higher == better)."""
    return Rating.parse(raw).sort_key


def rating_category(raw: Optional[str]) -> str:
    """Convenience: distribution category for a raw rating."""
    return Rating.parse(raw).category
