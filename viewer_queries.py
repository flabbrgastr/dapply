"""
Data-access logic for the performer viewer.

No Flask in this module, and **no raw SQL** — every database read/write goes
through the ``PerformerRepository`` port (``repo``). This module owns only the
/api/stats payload assembly (pulls from the port, sorts/categorizes).

The analvids.com lookups live behind the ``AnalvidsSource`` port
(``analvids_source.py``), and pure presentation helpers (rating sort/category)
live in ``viewer_rendering.py``.
"""

from collections import Counter

from viewer_rendering import _RATING_HIERARCHY, _get_rating_category, _rating_sort_key


def build_stats_payload(repo) -> dict:
    """Assemble the full /api/stats payload from the repository port."""
    stats = repo.get_stats()

    rated = repo.get_all_rated()
    sorted_rated = sorted(rated, key=lambda x: _rating_sort_key(x["rating"]), reverse=True)
    top_rated = sorted_rated[:10]
    bottom_rated = sorted_rated[-10:][::-1]

    avg_alphabetical = (
        round(sum(_rating_sort_key(p["rating"]) for p in sorted_rated) / len(sorted_rated), 2)
        if sorted_rated else 0.0
    )

    categories = [(_get_rating_category(p["rating"]), p["rating"]) for p in rated]
    rating_counts = Counter(cat for cat, _ in categories)
    dist_list = [{"range": cat, "count": cnt} for cat, cnt in rating_counts.items()]
    dist_list.sort(key=lambda x: _RATING_HIERARCHY.get(x["range"], 999))

    most_crawled = repo.get_most_crawled(10)

    return {
        "total_performers": stats["total_performers"],
        "total_items": stats["total_items"],
        "dap_performers": stats["dap_performers"],
        "total_scenes": stats["total_scenes"],
        "rating_distribution": dist_list,
        "rated_performers": len(rated),
        "avg_rating": avg_alphabetical,
        "numeric_avg_rating": stats["numeric_avg_rating"],
        "top_rated": top_rated,
        "bottom_rated": bottom_rated,
        "most_crawled": most_crawled,
    }
