"""
Presentation/rendering helpers for the performer viewer.

Pure functions only — no Flask, no database, no network. These turn raw
rating strings into sort keys / categories for the stats view.
"""

from typing import Optional


def _rating_sort_key(rating: Optional[str]) -> float:
    """Convert alphabetical rating to a numeric sort key."""
    if rating is None or rating == "":
        return float("-inf")
    try:
        return float(rating)
    except ValueError:
        rating_upper = rating.upper().strip()
        if rating_upper.startswith("AAA"):
            return 110.0 if "+" in rating_upper else (108.0 if "-" in rating_upper else 109.0)
        elif rating_upper.startswith("AA"):
            return 106.0 if "+" in rating_upper else (104.0 if "-" in rating_upper else 105.0)
        elif rating_upper.startswith("A"):
            return 102.0 if "+" in rating_upper else (100.0 if "-" in rating_upper else 101.0)
        elif rating_upper.startswith("BBB"):
            return 98.0 if "+" in rating_upper else (96.0 if "-" in rating_upper else 97.0)
        elif rating_upper.startswith("BB"):
            return 94.0 if "+" in rating_upper else (92.0 if "-" in rating_upper else 93.0)
        elif rating_upper.startswith("B"):
            return 90.0 if "+" in rating_upper else (88.0 if "-" in rating_upper else 89.0)
        elif rating_upper.startswith("CCC"):
            return 86.0 if "+" in rating_upper else (84.0 if "-" in rating_upper else 85.0)
        elif rating_upper.startswith("CC"):
            return 82.0 if "+" in rating_upper else (80.0 if "-" in rating_upper else 81.0)
        elif rating_upper.startswith("C"):
            return 78.0 if "+" in rating_upper else (76.0 if "-" in rating_upper else 77.0)
        elif rating_upper.startswith("DDD"):
            return 74.0 if "+" in rating_upper else (72.0 if "-" in rating_upper else 73.0)
        elif rating_upper.startswith("DD"):
            return 70.0 if "+" in rating_upper else (68.0 if "-" in rating_upper else 69.0)
        elif rating_upper.startswith("D"):
            return 66.0 if "+" in rating_upper else (64.0 if "-" in rating_upper else 65.0)
        elif rating_upper.startswith("EEE"):
            return 62.0 if "+" in rating_upper else (60.0 if "-" in rating_upper else 61.0)
        elif rating_upper.startswith("EE"):
            return 58.0 if "+" in rating_upper else (56.0 if "-" in rating_upper else 57.0)
        elif rating_upper.startswith("E"):
            return 54.0 if "+" in rating_upper else (52.0 if "-" in rating_upper else 53.0)
        return 40.0


def _get_rating_category(rating: Optional[str]) -> str:
    """Categorize a rating for distribution display."""
    if rating is None or rating == "":
        return "No Rating"
    try:
        num = float(rating)
        if num >= 9:
            return "9-10 (Numeric)"
        elif num >= 7:
            return "7-9 (Numeric)"
        elif num >= 5:
            return "5-7 (Numeric)"
        elif num >= 3:
            return "3-5 (Numeric)"
        else:
            return "0-3 (Numeric)"
    except ValueError:
        rating_upper = rating.upper().strip()
        # Map to hierarchy
        for prefix, result in [
            ("AAA+", "AAA+"), ("AAA-", "AAA-"), ("AAA", "AAA"),
            ("AA+", "AA+"), ("AA-", "AA-"), ("AA", "AA"),
            ("A+", "A+"), ("A-", "A-"), ("A", "A"),
            ("BBB+", "BBB+"), ("BBB-", "BBB-"), ("BBB", "BBB"),
            ("BB+", "BB+"), ("BB-", "BB-"), ("BB", "BB"),
            ("B+", "B+"), ("B-", "B-"), ("B", "B"),
            ("CCC+", "CCC+"), ("CCC-", "CCC-"), ("CCC", "CCC"),
            ("CC+", "CC+"), ("CC-", "CC-"), ("CC", "CC"),
            ("C+", "C+"), ("C-", "C-"), ("C", "C"),
            ("DDD+", "DDD+"), ("DDD-", "DDD-"), ("DDD", "DDD"),
            ("DD+", "DD+"), ("DD-", "DD-"), ("DD", "DD"),
            ("D+", "D+"), ("D-", "D-"), ("D", "D"),
            ("EEE+", "EEE+"), ("EEE-", "EEE-"), ("EEE", "EEE"),
            ("EE+", "EE+"), ("EE-", "EE-"), ("EE", "EE"),
            ("E+", "E+"), ("E-", "E-"), ("E", "E"),
        ]:
            if rating_upper.startswith(prefix):
                return result
        return "Other"


_RATING_HIERARCHY = {
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
