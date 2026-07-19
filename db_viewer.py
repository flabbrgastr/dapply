"""
Web UI for browsing and editing the performer database.

Flask app — thin routes only. All data access / external scraping lives in
``viewer_queries.py``; rating logic lives in the ``Rating`` domain module (``rating.py``).

The app is built by :func:`create_app`, which injects the repository port.
This makes the webapp testable without the production database: a test can
build ``create_app(InMemoryPerformerRepository())`` and drive it through the
Flask test client. The module-level ``app`` is the default production instance
(USES SQLite) — preserved so ``python db_viewer.py`` and the existing tests
keep working unchanged.
"""

import os
from typing import Optional

from flask import Flask, jsonify, render_template, request

from dbadd import create_db
from performer_repository import PerformerRepository, SqlitePerformerRepository
from viewer_queries import build_stats_payload
from analvids_source import AnalvidsSource, ScrapingAnalvidsSource


def create_app(repo: Optional[PerformerRepository] = None,
                analvids: Optional[AnalvidsSource] = None) -> Flask:
    """
    Build the web UI Flask app, injecting the repository and analvids ports.

    Args:
        repo: The repository to use. Defaults to ``SqlitePerformerRepository()``
            (the production database). Inject a fake (e.g.
            ``InMemoryPerformerRepository``) for tests.
        analvids: The analvids.com lookup source. Defaults to
            ``ScrapingAnalvidsSource()`` (production, network). Inject
            ``FakeAnalvidsSource`` for tests.

    Returns:
        A configured Flask app. The injected ports are also available on
        ``app.config["REPO"]`` / ``app.config["ANALVIDS"]``.
    """
    if repo is None:
        repo = SqlitePerformerRepository()
    if analvids is None:
        analvids = ScrapingAnalvidsSource()

    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
        static_url_path="/static",
    )
    # Expose the injected ports for __main__ and external access.
    app.config["REPO"] = repo
    app.config["ANALVIDS"] = analvids

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

        repo.add_to_refdb(target_name)
        repo.set_validated(performer_id)

        return jsonify({"message": "Performer confirmed", "name": target_name})

    @app.route("/api/performers/<int:performer_id>/reassign", methods=["POST"])
    def reassign_performer(performer_id):
        """
        Reassign all items from one performer to another, then optionally delete the source.
        Body: { "target_name": "...", "delete_source": true }
        """
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
        return jsonify(analvids.search(q))

    @app.route("/api/performers/lookup-analvids-url")
    def lookup_analvids_url():
        """Fetch an analvids model profile by URL and extract performer info."""
        raw = request.args.get("url", "").strip()
        profile = analvids.fetch_profile(raw)
        if "error" in profile:
            return jsonify(profile)
        # Persist the cached image through the repository port (the only DB
        # writer); the source itself never touches the database.
        if profile.get("local_image") and profile.get("model_id"):
            repo.save_profile_image(
                profile["model_id"], profile.get("image"), profile["local_image"]
            )
        return jsonify(profile)

    @app.route("/api/performers/<int:performer_id>/features")
    def get_performer_features(performer_id):
        """Return performer_features + scenes for this performer."""
        feat = repo.get_features(performer_id)
        scenes = repo.get_scenes(performer_id)
        performer = repo.get_by_id(performer_id)
        pname = performer["name"] if performer else ""
        paka = performer.get("aka", "") if performer else ""
        pvalidated = bool(performer["validated"]) if performer else False

        profile_image = repo.get_profile_image(pname)

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

    @app.route("/api/stats")
    def get_stats():
        return jsonify(build_stats_payload(repo))

    @app.route("/api/performers/refresh-refdb", methods=["POST"])
    def refresh_refdb_status():
        count = repo.compute_refdb_status()
        if count >= 0:
            return jsonify({"message": f"Updated {count} performers", "count": count})
        return jsonify({"error": "RefDB status computation failed"}), 500

    return app


# Default production instance (uses SQLite). Preserves `python db_viewer.py`
# and the import-time behaviour the existing tests rely on.
app = create_app()


if __name__ == "__main__":
    create_db("performers.db")
    updated = app.config["REPO"].compute_refdb_status()
    if updated > 0:
        print(f"  ~ refdb_status computed for {updated} performers")
    app.run(debug=False, host='0.0.0.0', port=8009)
