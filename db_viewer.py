"""
Web UI for browsing and editing the performer database.
Flask app serving the viewer template and REST API.
"""

import os
import re
from io import BytesIO
from collections import Counter

from flask import Flask, jsonify, render_template, request
import requests as http_requests
from PIL import Image as PIL_Image

import sqlite3

from dbadd import create_db
from performer_repository import SqlitePerformerRepository

app = Flask(__name__,
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
    static_url_path="/static",
)

repo = SqlitePerformerRepository()


@app.route("/")
def index():
    return render_template("viewer.html")


@app.route("/api/performers")
def get_performers():
    sort_by = request.args.get("sort_by", "name")
    sort_order = request.args.get("sort_order", "asc")
    show_aliases = request.args.get("show_aliases", "0") == "1"
    dap_only = request.args.get("dap_only", "0") == "1"
    search_q = request.args.get("q", "").strip()
    limit = request.args.get("limit", None)
    performers = repo.search(
        q=search_q, sort_by=sort_by, sort_order=sort_order,
        show_aliases=show_aliases, dap_only=dap_only, limit=limit,
    )
    return jsonify(performers)


@app.route("/api/performers/<int:performer_id>", methods=["PUT"])
def update_performer(performer_id):
    data = request.get_json()
    rating = data.get("rating")
    repo.update_rating(performer_id, rating)
    return jsonify({"message": "Performer updated successfully"})


@app.route("/api/performers", methods=["POST"])
def add_performer():
    data = request.get_json()
    name = data.get("name")
    rating = data.get("rating", "")
    if not name:
        return jsonify({"error": "Name is required"}), 400
    repo.insert(name, rating)
    return jsonify({"message": "Performer added successfully"})


@app.route("/api/performers/<int:performer_id>/confirm", methods=["POST"])
def confirm_performer(performer_id):
    """Confirm a performer name and add to refdb as manually verified."""
    data = request.get_json() or {}
    correct_name = data.get("name", "").strip()

    performer = repo.get_by_id(performer_id)
    if not performer:
        return jsonify({"error": "Performer not found"}), 404

    current_name = performer["name"]
    target_name = correct_name if correct_name else current_name

    # Update performer name if corrected
    if correct_name and correct_name != current_name:
        repo.update_name(performer_id, correct_name)
        # Also update AKA
        if current_name not in (performer.get("aka") or ""):
            repo.update_aka(performer_id, current_name)

    # Add to refdb_models if not already there
    conn = sqlite3.connect("performers.db")
    try:
        conn.execute(
            "INSERT OR IGNORE INTO refdb_models (name, profile_url) VALUES (?, ?)",
            (target_name, ""),
        )
        conn.execute(
            "INSERT OR REPLACE INTO refdb_validated_tags (tag, refdb_model_id, match_type) "
            "SELECT ?, id, 'manual' FROM refdb_models WHERE name = ?",
            (target_name, target_name),
        )
        conn.commit()
    finally:
        conn.close()
    repo.set_validated(performer_id)

    return jsonify({"message": "Performer confirmed", "name": target_name})


@app.route("/api/performers/<int:performer_id>/reassign", methods=["POST"])
def reassign_performer(performer_id):
    """
    Reassign all items from one performer to another, then optionally delete the source.
    Body: { "target_name": "...", "delete_source": true }
    """
    import sqlite3
    data = request.get_json() or {}
    target_name = data.get("target_name", "").strip()
    delete_source = data.get("delete_source", True)

    if not target_name:
        return jsonify({"error": "target_name is required"}), 400

    source = repo.get_by_id(performer_id)
    if not source:
        return jsonify({"error": "Source performer not found"}), 404
    source_name = source["name"]

    # Find or create target
    target = repo.get_by_name(target_name)
    if target:
        target_id = target["id"]
    else:
        target_id = repo.insert(target_name)

    # Move items
    repo.reassign_items(performer_id, target_id)

    # Optionally delete source
    if delete_source:
        repo.update_aka(target_id, source_name)
        repo.delete(performer_id)

    repo.set_validated(target_id)

    return jsonify({
        "message": f"Items reassigned from '{source_name}' to '{target_name}'",
        "source_id": performer_id,
        "target_id": target_id,
        "source_deleted": delete_source,
    })


@app.route("/api/items/<int:item_id>/reassign", methods=["POST"])
def reassign_item(item_id):
    """Reassign a single item to a different performer."""
    data = request.get_json() or {}
    target_name = data.get("target_name", "").strip()
    if not target_name:
        return jsonify({"error": "target_name required"}), 400

    # Get current performer name
    item_info = repo.get_item_by_id(item_id)
    if not item_info:
        return jsonify({"error": "Item not found"}), 404
    source_name = item_info.get("name") or "(unassigned)"

    # Find or create target
    target = repo.get_by_name(target_name)
    if target:
        target_id = target["id"]
    else:
        target_id = repo.insert(target_name)

    repo.assign_item(item_id, target_id)
    return jsonify({"message": f"Item #{item_id} moved from '{source_name}' to '{target_name}'"})


@app.route("/api/items/<int:item_id>/unassign", methods=["POST"])
def unassign_item(item_id):
    """Remove item from its performer (set performer_id = NULL)."""
    item_info = repo.get_item_by_id(item_id)
    if not item_info:
        return jsonify({"error": "Item not found"}), 404
    source_name = item_info.get("name") or "(unassigned)"
    repo.unassign_item(item_id)
    return jsonify({"message": f"Item #{item_id} unassigned from '{source_name}'"})


@app.route("/api/items/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    """Delete a single item."""
    repo.delete_item(item_id)
    return jsonify({"message": f"Item #{item_id} deleted"})


@app.route("/api/performers/unassigned/items")
def unassigned_items():
    """Return all items with no performer assigned."""
    sort_by = request.args.get("sort_by", "added_date")
    sort_order = request.args.get("sort_order", "desc")
    items = repo.get_unassigned_items(sort_by=sort_by, sort_order=sort_order)
    return jsonify(items)


@app.route("/api/performers/<int:performer_id>", methods=["DELETE"])
def delete_performer(performer_id):
    repo.delete(performer_id)
    return jsonify({"message": "Performer deleted, items unassigned"})


@app.route("/api/performers/lookup-analvids")
def lookup_analvids():
    """Search analvids.com for a performer name and return matching models."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})

    try:
        from urllib.parse import quote

        url = f"https://www.analvids.com/models?search={quote(q)}"
        resp = http_requests.get(url, timeout=15,
                                 headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return jsonify({"results": [], "error": f"analvids returned {resp.status_code}"})

        html = resp.text
        results = []
        seen = set()

        cards = html.split('class="model-top__img"')
        for card in cards[1:]:
            url_match = re.search(
                r'href="(https://www\.analvids\.com/model/(\d+)/([^"]+))"', card[:500]
            )
            if not url_match:
                continue
            profile_url = url_match.group(1)
            model_id = int(url_match.group(2))
            slug = url_match.group(3)
            name_match = re.search(
                r'class="model-top__name"[^>]*>([^<]+)<', card[:800]
            )
            if not name_match:
                continue
            name = name_match.group(1).strip()
            if name in seen:
                continue
            seen.add(name)

            scenes = None
            scene_match = re.search(r'<b>(\d+)</b>\s*scenes?', card[:1500])
            if scene_match:
                scenes = int(scene_match.group(1))

            nationality = None
            flag_match = re.search(r'/assets/img/flags/(\w+)\.png', card[:800])
            if flag_match:
                nationality = flag_match.group(1).upper()

            results.append({
                "name": name, "url": profile_url,
                "model_id": model_id, "scenes": scenes,
                "nationality": nationality,
            })

        return jsonify({"results": results[:10]})
    except Exception as e:
        return jsonify({"results": [], "error": str(e)})


@app.route("/api/performers/lookup-analvids-url")
def lookup_analvids_url():
    """Fetch an analvids model profile by URL and extract performer info."""
    raw = request.args.get("url", "").strip()
    if not raw:
        return jsonify({"error": "Paste a name or analvids.com URL"})

    try:
        from urllib.parse import quote

        if "." not in raw or raw.startswith("http"):
            profile_url = raw
            if not profile_url.startswith("http"):
                parts = raw.strip().split()
                candidates = []
                if len(parts) >= 2:
                    candidates.append('_'.join(p.lower() for p in parts))
                    candidates.append(''.join(p.lower() for p in parts))
                else:
                    candidates.append(raw.lower())

                profile_url = None
                for candidate in candidates:
                    test_url = f"https://www.analvids.com/model/0/{candidate}"
                    resp = http_requests.get(
                        test_url, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"},
                        allow_redirects=True,
                    )
                    if resp.status_code == 200 and '/model/' in resp.url and resp.url != test_url:
                        profile_url = resp.url
                        break

                if not profile_url:
                    search_url = f"https://www.analvids.com/search/{quote(raw)}"
                    resp = http_requests.get(
                        search_url, timeout=10,
                        headers={"User-Agent": "Mozilla/5.0"},
                        allow_redirects=False,
                    )
                    loc = resp.headers.get('Location', '')
                    if resp.status_code in (301, 302) and '/model/' in loc:
                        if not loc.startswith('http'):
                            loc = 'https://www.analvids.com' + loc
                        profile_url = loc

                if not profile_url:
                    resp = http_requests.get(
                        f"https://html.duckduckgo.com/html/?q=analvids.com+{quote(raw)}",
                        timeout=10, headers={"User-Agent": "Mozilla/5.0"},
                    )
                    m = re.search(r'analvids\.com/model/(\d+)/([a-z_]+)', resp.text)
                    if m:
                        profile_url = f"https://www.analvids.com/model/{m.group(1)}/{m.group(2)}"
        else:
            profile_url = raw

        resp = http_requests.get(
            profile_url, timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code != 200:
            return jsonify({"error": f"analvids returned {resp.status_code}"})

        html = resp.text
        url_match = re.search(r'/model/(\d+)', profile_url)
        model_id = int(url_match.group(1)) if url_match else None

        name = None
        name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if name_match:
            name = name_match.group(1).strip()
        if not name:
            name_match = re.search(r'<title>([^|<]+)', html)
            if name_match:
                name = name_match.group(1).strip()

        nationality = None
        flag_match = re.search(r'/assets/img/flags/(\w+)\.png', html)
        if flag_match:
            nationality = flag_match.group(1).upper()

        scenes = None
        scene_match = re.search(r'<b>(\d+)</b>\s*scenes?', html)
        if scene_match:
            scenes = int(scene_match.group(1))

        image = None
        img_match = re.search(r'class="model__bg"[^>]*src="([^"]+)"', html)
        if img_match:
            image = img_match.group(1).replace('&amp;', '&')
        if not image:
            img_match = re.search(r'data-src="([^"]*cdn77[^"]*w=420[^"]+)"', html)
            if img_match:
                image = img_match.group(1).replace('&amp;', '&')

        if not name:
            return jsonify({"error": "Could not extract performer name"})

        # Store profile image as webp thumbnail
        local_image = None
        if image and model_id:
            try:
                import sqlite3 as _sqlite3
                static_dir = os.path.join(os.path.dirname(__file__), "static", "images")
                os.makedirs(static_dir, exist_ok=True)

                img_resp = http_requests.get(
                    image, timeout=10,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if img_resp.status_code == 200:
                    img_data = PIL_Image.open(BytesIO(img_resp.content))
                    max_w = 300
                    if img_data.width > max_w:
                        ratio = max_w / img_data.width
                        new_h = int(img_data.height * ratio)
                        img_data = img_data.resize((max_w, new_h), PIL_Image.LANCZOS)

                    fname = f"{model_id}.webp"
                    local_path = os.path.join(static_dir, fname)
                    img_data.save(local_path, "WEBP", quality=75)
                    local_image = f"/performers/static/images/{fname}"

                    conn2 = _sqlite3.connect("performers.db")
                    conn2.execute(
                        """CREATE TABLE IF NOT EXISTS performer_images (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            performer_id INTEGER, model_id INTEGER,
                            image_url TEXT, local_path TEXT,
                            type TEXT DEFAULT "profile",
                            added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )"""
                    )
                    conn2.execute(
                        "INSERT OR REPLACE INTO performer_images "
                        "(performer_id, model_id, image_url, local_path, type) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (None, model_id, image, local_image, "profile"),
                    )
                    conn2.commit()
                    conn2.close()
            except Exception:
                pass

        return jsonify({
            "name": name, "url": profile_url,
            "model_id": model_id, "scenes": scenes,
            "nationality": nationality, "image": image,
            "local_image": local_image,
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/performers/<int:performer_id>/features")
def get_performer_features(performer_id):
    """Return performer_features + scenes for this performer."""
    feat = repo.get_features(performer_id)
    scenes = repo.get_scenes(performer_id)
    performer = repo.get_by_id(performer_id)
    pname = performer["name"] if performer else ""
    paka = performer.get("aka", "") if performer else ""
    pvalidated = bool(performer["validated"]) if performer else False

    # Profile image from refdb
    profile_image = None
    if pname:
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect("performers.db")
        img = conn.execute(
            """SELECT pi.local_path FROM performer_images pi
                JOIN refdb_models m ON m.id = pi.model_id
                WHERE LOWER(m.name) = LOWER(?) LIMIT 1""",
            (pname,),
        ).fetchone()
        if img:
            profile_image = img[0]
        conn.close()

    return jsonify({
        "features": feat,
        "scenes": scenes,
        "name": pname,
        "aka": paka,
        "validated": pvalidated,
        "profile_image": profile_image,
    })


@app.route("/api/performers/<int:performer_id>/items")
def get_performer_items(performer_id):
    sort_by = request.args.get("sort_by", "added_date")
    sort_order = request.args.get("sort_order", "desc")
    items = repo.get_items(performer_id)

    # Deduplicate by item_url
    seen_urls = set()
    deduped = []
    for item in items:
        url = item.get("item_url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(item)

    # Sort in Python since repo returns by added_date desc
    valid_cols = {"id", "item_url", "title", "item_date", "hits", "added_date", "source_file"}
    if sort_by not in valid_cols:
        sort_by = "added_date"
    reverse = sort_order == "desc"
    deduped.sort(key=lambda x: x.get(sort_by, "") or "", reverse=reverse)

    return jsonify(deduped)


@app.route("/api/refdb/performers")
def get_refdb_performers():
    """Browse the reference database with filtering."""
    q = request.args.get("q", "").strip()
    nationality = request.args.get("nationality", "").strip()
    tag = request.args.get("tag", "").strip()
    age_min = request.args.get("age_min", type=int)
    age_max = request.args.get("age_max", type=int)
    has_profile = request.args.get("has_profile", "")
    sort_by = request.args.get("sort_by", "name")
    sort_order = request.args.get("sort_order", "asc")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    result = repo.search_refdb(
        q=q, nationality=nationality, tag=tag,
        age_min=age_min, age_max=age_max,
        has_profile=has_profile,
        sort_by=sort_by, sort_order=sort_order,
        page=page, per_page=per_page,
    )

    # Add nationalities for filter dropdown
    result["nationalities"] = repo.get_refdb_nationalities()
    return jsonify(result)


@app.route("/api/non-performer-tags", methods=["GET"])
def get_non_performer_tags():
    tags = repo.get_non_performer_tags()
    return jsonify(tags)


@app.route("/api/non-performer-tags", methods=["POST"])
def add_non_performer_tag():
    data = request.get_json()
    tag = data.get("tag", "").strip()
    reason = data.get("reason", "").strip()
    if not tag:
        return jsonify({"error": "Tag is required"}), 400
    try:
        tid = repo.add_non_performer_tag(tag, reason)
        return jsonify({"id": tid, "tag": tag, "reason": reason}), 201
    except Exception:
        return jsonify({"error": "Tag already exists"}), 409


@app.route("/api/non-performer-tags/<int:tag_id>", methods=["DELETE"])
def delete_non_performer_tag(tag_id):
    repo.delete_non_performer_tag(tag_id)
    return jsonify({"message": "Tag deleted"})


@app.route("/api/refdb")
def get_refdb_stats():
    """Stats about the reference database (profile scraping progress)."""
    counts = repo.get_refdb_counts()
    return jsonify(counts)


@app.route("/stats")
def stats_page():
    return render_template("stats.html")


# ── Rating sorting helpers (pure Python, no DB) ──

def _rating_sort_key(rating):
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


def _get_rating_category(rating):
    """Categorize a rating for distribution display."""
    if rating is None or rating == "":
        return "No Rating"
    try:
        num = float(rating)
        if num >= 9: return "9-10 (Numeric)"
        elif num >= 7: return "7-9 (Numeric)"
        elif num >= 5: return "5-7 (Numeric)"
        elif num >= 3: return "3-5 (Numeric)"
        else: return "0-3 (Numeric)"
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


@app.route("/api/stats")
def get_stats():
    stats = repo.get_stats()

    # --- Rating-specific stats (need custom logic) ---
    rated = repo.get_all_rated()
    sorted_rated = sorted(
        rated, key=lambda x: _rating_sort_key(x["rating"]), reverse=True
    )
    top_rated = sorted_rated[:10]
    bottom_rated = sorted_rated[-10:][::-1]

    # Average rating
    if sorted_rated:
        avg_alphabetical = round(
            sum(_rating_sort_key(p["rating"]) for p in sorted_rated) / len(sorted_rated), 2
        )
    else:
        avg_alphabetical = 0.0

    # Try numeric average
    import sqlite3
    conn = sqlite3.connect("performers.db")
    try:
        avg_numeric = conn.execute("""
            SELECT AVG(CAST(rating AS REAL)) FROM performers
            WHERE rating IS NOT NULL AND rating != ""
            AND (rating GLOB '[0-9]*' OR rating GLOB '[0-9]*.[0-9]*')
        """).fetchone()[0]
        avg_numeric = round(avg_numeric, 2) if avg_numeric else 0.0
    except Exception:
        avg_numeric = 0.0
    conn.close()

    # Rating distribution
    categories = [(_get_rating_category(p["rating"]), p["rating"]) for p in rated]
    rating_counts = Counter(cat for cat, _ in categories)
    dist_list = [{"range": cat, "count": cnt} for cat, cnt in rating_counts.items()]
    dist_list.sort(key=lambda x: _RATING_HIERARCHY.get(x["range"], 999))

    # Most crawled
    most_crawled = repo.get_most_crawled(10)

    return jsonify({
        "total_performers": stats["total_performers"],
        "total_items": stats["total_items"],
        "dap_performers": stats["dap_performers"],
        "total_scenes": stats["total_scenes"],
        "rating_distribution": dist_list,
        "rated_performers": len(rated),
        "avg_rating": avg_alphabetical,
        "numeric_avg_rating": avg_numeric,
        "top_rated": top_rated,
        "bottom_rated": bottom_rated,
        "most_crawled": most_crawled,
    })


def _compute_refdb_status():
    """
    Batch-compute refdb_status for all performers.
    Stores 'matched', 'fuzzy', or NULL (unmatched) in the performers table.
    """
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return 0

    import sqlite3
    conn = sqlite3.connect("performers.db")
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


@app.route("/api/performers/refresh-refdb", methods=["POST"])
def refresh_refdb_status():
    count = _compute_refdb_status()
    if count >= 0:
        return jsonify({"message": f"Updated {count} performers", "count": count})
    return jsonify({"error": "RefDB status computation failed"}), 500


def _check_refdb_match(name: str) -> str:
    """Legacy on-the-fly check (used if cached column is empty)."""
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return "unknown"
    import sqlite3
    conn = sqlite3.connect("performers.db")
    c = conn.cursor()
    c.execute("SELECT name FROM refdb_models")
    all_names = [row[0] for row in c.fetchall()]
    conn.close()
    if not all_names:
        return "unknown"
    name_lower = name.lower()
    for n in all_names:
        if n.lower() == name_lower:
            return "matched"
    result = process.extractOne(name, all_names, scorer=fuzz.token_sort_ratio, score_cutoff=88)
    if result:
        return "fuzzy"
    return "unmatched"


if __name__ == "__main__":
    create_db("performers.db")
    updated = _compute_refdb_status()
    if updated > 0:
        print(f"  ~ refdb_status computed for {updated} performers")
    app.run(debug=False, host='0.0.0.0', port=8009)