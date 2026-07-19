"""
Data-access logic for the performer viewer.

No Flask in this module, and **no raw SQL** — every database read/write goes
through the ``PerformerRepository`` port (``repo``). This module owns only the
/api/stats payload assembly (pulls from the port, sorts/categorizes).

The analvids.com lookups live behind the ``AnalvidsSource`` port
(``analvids_source.py``), and rating logic lives in the ``Rating`` domain
module (``rating.py``).
"""

from collections import Counter

from rating import RATING_HIERARCHY, Rating


def build_stats_payload(repo) -> dict:
    """Assemble the full /api/stats payload from the repository port."""
    stats = repo.get_stats()

    rated = repo.get_all_rated()
    parsed = [(p, Rating.parse(p["rating"])) for p in rated]
    parsed.sort(key=lambda pr: pr[1], reverse=True)
    sorted_rated = [p for p, _ in parsed]
    top_rated = sorted_rated[:10]
    bottom_rated = sorted_rated[-10:][::-1]

    avg_alphabetical = (
        round(sum(pr[1].sort_key for pr in parsed) / len(parsed), 2)
        if parsed else 0.0
    )

    categories = [(pr.category, p["rating"]) for p, pr in parsed]
    rating_counts = Counter(cat for cat, _ in categories)
    dist_list = [{"range": cat, "count": cnt} for cat, cnt in rating_counts.items()]
    dist_list.sort(key=lambda x: RATING_HIERARCHY.get(x["range"], 999))

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
