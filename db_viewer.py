import os
import sqlite3

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

DATABASE = "performers.db"


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Allows us to access columns by name
    return conn


@app.route("/")
def index():
    return render_template("viewer.html")


@app.route("/api/performers")
def get_performers():
    conn = get_db_connection()

    # Get sort parameters
    sort_by = request.args.get("sort_by", "name")
    sort_order = request.args.get("sort_order", "asc")

    # Validate sort parameters to prevent injection
    valid_columns = ["id", "name", "last_updated", "crawls", "rating"]
    if sort_by not in valid_columns:
        sort_by = "name"
    if sort_order not in ["asc", "desc"]:
        sort_order = "asc"

    # Query performers with sorting
    performers = conn.execute(
        f"SELECT * FROM performers ORDER BY {sort_by} {sort_order}"
    ).fetchall()

    conn.close()

    # Convert to list of dicts for JSON serialization
    performers_list = [dict(p) for p in performers]

    return jsonify(performers_list)


@app.route("/api/performers/<int:performer_id>", methods=["PUT"])
def update_performer(performer_id):
    from flask import request

    data = request.get_json()
    rating = data.get("rating")

    conn = get_db_connection()
    conn.execute(
        "UPDATE performers SET rating = ? WHERE id = ?", (rating, performer_id)
    )
    conn.commit()
    conn.close()

    return jsonify({"message": "Performer updated successfully"})


@app.route("/api/performers", methods=["POST"])
def add_performer():
    from flask import request

    data = request.get_json()
    name = data.get("name")
    rating = data.get("rating", "")

    if not name:
        return jsonify({"error": "Name is required"}), 400

    conn = get_db_connection()
    conn.execute("INSERT INTO performers (name, rating) VALUES (?, ?)", (name, rating))
    conn.commit()
    conn.close()

    return jsonify({"message": "Performer added successfully"})


@app.route("/api/performers/<int:performer_id>", methods=["DELETE"])
def delete_performer(performer_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM performers WHERE id = ?", (performer_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": "Performer deleted successfully"})


@app.route("/api/performers/<int:performer_id>/items")
def get_performer_items(performer_id):
    conn = get_db_connection()

    # Get sort parameters
    sort_by = request.args.get("sort_by", "added_date")
    sort_order = request.args.get("sort_order", "desc")

    # Validate sort parameters to prevent injection
    valid_columns = ["id", "item_url", "title", "item_date", "hits", "added_date", "source_file"]
    if sort_by not in valid_columns:
        sort_by = "added_date"
    if sort_order not in ["asc", "desc"]:
        sort_order = "desc"

    # Query items for the specific performer with sorting
    items = conn.execute(
        f"SELECT * FROM items WHERE performer_id = ? ORDER BY {sort_by} {sort_order}", (performer_id,)
    ).fetchall()

    conn.close()

    # Convert to list of dicts for JSON serialization
    items_list = [dict(item) for item in items]

    return jsonify(items_list)


@app.route("/stats")
def stats_page():
    return render_template("stats.html")


@app.route("/api/stats")
def get_stats():
    conn = get_db_connection()

    # Total performers
    total_performers = conn.execute("SELECT COUNT(*) FROM performers").fetchone()[0]

    # Rated performers
    rated_performers = conn.execute(
        'SELECT COUNT(*) FROM performers WHERE rating IS NOT NULL AND rating != ""'
    ).fetchone()[0]

    # Alphabetical rating comparison function - AAA > AA+ > AA > AA- > A > ...
    def rating_sort_key(rating):
        if rating is None or rating == "":
            return float("-inf")  # Lowest priority

        # Handle numeric ratings
        try:
            return float(rating)
        except ValueError:
            # Handle alphabetical ratings
            rating_upper = rating.upper().strip()

            # AAA ratings
            if rating_upper.startswith("AAA"):
                if "+" in rating_upper:
                    return 110.0  # AAA+
                elif "-" in rating_upper:
                    return 108.0  # AAA-
                else:
                    return 109.0  # AAA (standard)
            # AA ratings
            elif rating_upper.startswith("AA"):
                if "+" in rating_upper:
                    return 106.0  # AA+
                elif "-" in rating_upper:
                    return 104.0  # AA-
                else:
                    return 105.0  # AA (standard)
            # A ratings
            elif rating_upper.startswith("A"):
                if "+" in rating_upper:
                    return 102.0  # A+
                elif "-" in rating_upper:
                    return 100.0  # A-
                else:
                    return 101.0  # A (standard)
            # BBB ratings
            elif rating_upper.startswith("BBB"):
                if "+" in rating_upper:
                    return 98.0  # BBB+
                elif "-" in rating_upper:
                    return 96.0  # BBB-
                else:
                    return 97.0  # BBB (standard)
            # BB ratings
            elif rating_upper.startswith("BB"):
                if "+" in rating_upper:
                    return 94.0  # BB+
                elif "-" in rating_upper:
                    return 92.0  # BB-
                else:
                    return 93.0  # BB (standard)
            # B ratings
            elif rating_upper.startswith("B"):
                if "+" in rating_upper:
                    return 90.0  # B+
                elif "-" in rating_upper:
                    return 88.0  # B-
                else:
                    return 89.0  # B (standard)
            # CCC ratings
            elif rating_upper.startswith("CCC"):
                if "+" in rating_upper:
                    return 86.0  # CCC+
                elif "-" in rating_upper:
                    return 84.0  # CCC-
                else:
                    return 85.0  # CCC (standard)
            # CC ratings
            elif rating_upper.startswith("CC"):
                if "+" in rating_upper:
                    return 82.0  # CC+
                elif "-" in rating_upper:
                    return 80.0  # CC-
                else:
                    return 81.0  # CC (standard)
            # C ratings
            elif rating_upper.startswith("C"):
                if "+" in rating_upper:
                    return 78.0  # C+
                elif "-" in rating_upper:
                    return 76.0  # C-
                else:
                    return 77.0  # C (standard)
            # DDD ratings
            elif rating_upper.startswith("DDD"):
                if "+" in rating_upper:
                    return 74.0  # DDD+
                elif "-" in rating_upper:
                    return 72.0  # DDD-
                else:
                    return 73.0  # DDD (standard)
            # DD ratings
            elif rating_upper.startswith("DD"):
                if "+" in rating_upper:
                    return 70.0  # DD+
                elif "-" in rating_upper:
                    return 68.0  # DD-
                else:
                    return 69.0  # DD (standard)
            # D ratings
            elif rating_upper.startswith("D"):
                if "+" in rating_upper:
                    return 66.0  # D+
                elif "-" in rating_upper:
                    return 64.0  # D-
                else:
                    return 65.0  # D (standard)
            # EEE ratings
            elif rating_upper.startswith("EEE"):
                if "+" in rating_upper:
                    return 62.0  # EEE+
                elif "-" in rating_upper:
                    return 60.0  # EEE-
                else:
                    return 61.0  # EEE (standard)
            # EE ratings
            elif rating_upper.startswith("EE"):
                if "+" in rating_upper:
                    return 58.0  # EE+
                elif "-" in rating_upper:
                    return 56.0  # EE-
                else:
                    return 57.0  # EE (standard)
            # E ratings
            elif rating_upper.startswith("E"):
                if "+" in rating_upper:
                    return 54.0  # E+
                elif "-" in rating_upper:
                    return 52.0  # E-
                else:
                    return 53.0  # E (standard)
            else:
                # For any other rating, give it a standardized value
                return 40.0

    # Calculate average rating for numeric ratings only
    try:
        avg_rating_result = conn.execute("""
            SELECT AVG(CAST(rating AS REAL)) FROM performers
            WHERE rating IS NOT NULL AND rating != ""
            AND rating GLOB "[0-9]*" OR rating GLOB "[0-9]*.[0-9]*"
        """).fetchone()[0]
        avg_numeric_rating = (
            round(avg_rating_result, 2) if avg_rating_result is not None else 0.0
        )
    except:
        avg_numeric_rating = 0.0

    # Get all performers with ratings for sorting
    all_rated_performers = conn.execute(
        'SELECT * FROM performers WHERE rating IS NOT NULL AND rating != ""'
    ).fetchall()
    # Sort using our custom function
    sorted_performers = sorted(
        [dict(row) for row in all_rated_performers],
        key=lambda x: rating_sort_key(x["rating"]),
        reverse=True,
    )

    # Top 10 rated performers
    top_rated = sorted_performers[:10]

    # Bottom 10 rated performers
    bottom_rated = sorted_performers[-10:][::-1]  # Reverse to show ascending order

    # Average rating considering alphabetical ratings (convert to numerical scale for average)
    if sorted_performers:
        total_rating_value = sum(
            [rating_sort_key(performer["rating"]) for performer in sorted_performers]
        )
        avg_alphabetical_rating = round(total_rating_value / len(sorted_performers), 2)
    else:
        avg_alphabetical_rating = 0.0

    # Performers by rating distribution (for alphabetical ratings)
    def get_rating_category(rating):
        if rating is None or rating == "":
            return "No Rating"

        # Handle numeric ratings
        try:
            num_rating = float(rating)
            if num_rating >= 9:
                return "9-10 (Numeric)"
            elif num_rating >= 7:
                return "7-9 (Numeric)"
            elif num_rating >= 5:
                return "5-7 (Numeric)"
            elif num_rating >= 3:
                return "3-5 (Numeric)"
            else:
                return "0-3 (Numeric)"
        except ValueError:
            # Handle alphabetical ratings
            rating_upper = rating.upper().strip()

            # AAA ratings
            if rating_upper.startswith("AAA"):
                if "+" in rating_upper:
                    return "AAA+"
                elif "-" in rating_upper:
                    return "AAA-"
                else:
                    return "AAA"
            # AA ratings
            elif rating_upper.startswith("AA"):
                if "+" in rating_upper:
                    return "AA+"
                elif "-" in rating_upper:
                    return "AA-"
                else:
                    return "AA"
            # A ratings
            elif rating_upper.startswith("A"):
                if "+" in rating_upper:
                    return "A+"
                elif "-" in rating_upper:
                    return "A-"
                else:
                    return "A"
            # BBB ratings
            elif rating_upper.startswith("BBB"):
                if "+" in rating_upper:
                    return "BBB+"
                elif "-" in rating_upper:
                    return "BBB-"
                else:
                    return "BBB"
            # BB ratings
            elif rating_upper.startswith("BB"):
                if "+" in rating_upper:
                    return "BB+"
                elif "-" in rating_upper:
                    return "BB-"
                else:
                    return "BB"
            # B ratings
            elif rating_upper.startswith("B"):
                if "+" in rating_upper:
                    return "B+"
                elif "-" in rating_upper:
                    return "B-"
                else:
                    return "B"
            # CCC ratings
            elif rating_upper.startswith("CCC"):
                if "+" in rating_upper:
                    return "CCC+"
                elif "-" in rating_upper:
                    return "CCC-"
                else:
                    return "CCC"
            # CC ratings
            elif rating_upper.startswith("CC"):
                if "+" in rating_upper:
                    return "CC+"
                elif "-" in rating_upper:
                    return "CC-"
                else:
                    return "CC"
            # C ratings
            elif rating_upper.startswith("C"):
                if "+" in rating_upper:
                    return "C+"
                elif "-" in rating_upper:
                    return "C-"
                else:
                    return "C"
            # DDD ratings
            elif rating_upper.startswith("DDD"):
                if "+" in rating_upper:
                    return "DDD+"
                elif "-" in rating_upper:
                    return "DDD-"
                else:
                    return "DDD"
            # DD ratings
            elif rating_upper.startswith("DD"):
                if "+" in rating_upper:
                    return "DD+"
                elif "-" in rating_upper:
                    return "DD-"
                else:
                    return "DD"
            # D ratings
            elif rating_upper.startswith("D"):
                if "+" in rating_upper:
                    return "D+"
                elif "-" in rating_upper:
                    return "D-"
                else:
                    return "D"
            # EEE ratings
            elif rating_upper.startswith("EEE"):
                if "+" in rating_upper:
                    return "EEE+"
                elif "-" in rating_upper:
                    return "EEE-"
                else:
                    return "EEE"
            # EE ratings
            elif rating_upper.startswith("EE"):
                if "+" in rating_upper:
                    return "EE+"
                elif "-" in rating_upper:
                    return "EE-"
                else:
                    return "EE"
            # E ratings
            elif rating_upper.startswith("E"):
                if "+" in rating_upper:
                    return "E+"
                elif "-" in rating_upper:
                    return "E-"
                else:
                    return "E"
            else:
                return "Other"

    # Count performers by category
    from collections import Counter

    rating_categories = [get_rating_category(p["rating"]) for p in sorted_performers]
    rating_counts = Counter(rating_categories)

    rating_distribution_list = [
        {"range": category, "count": count} for category, count in rating_counts.items()
    ]

    # Sort rating distribution by our predefined hierarchy
    def rating_hierarchy_key(category):
        rating_hierarchy = {
            "AAA+": 1,
            "AAA": 2,
            "AAA-": 3,
            "AA+": 4,
            "AA": 5,
            "AA-": 6,
            "A+": 7,
            "A": 8,
            "A-": 9,
            "BBB+": 10,
            "BBB": 11,
            "BBB-": 12,
            "BB+": 13,
            "BB": 14,
            "BB-": 15,
            "B+": 16,
            "B": 17,
            "B-": 18,
            "CCC+": 19,
            "CCC": 20,
            "CCC-": 21,
            "CC+": 22,
            "CC": 23,
            "CC-": 24,
            "C+": 25,
            "C": 26,
            "C-": 27,
            "DDD+": 28,
            "DDD": 29,
            "DDD-": 30,
            "DD+": 31,
            "DD": 32,
            "DD-": 33,
            "D+": 34,
            "D": 35,
            "D-": 36,
            "EEE+": 37,
            "EEE": 38,
            "EEE-": 39,
            "EE+": 40,
            "EE": 41,
            "EE-": 42,
            "E+": 43,
            "E": 44,
            "E-": 45,
            "9-10 (Numeric)": 46,
            "7-9 (Numeric)": 47,
            "5-7 (Numeric)": 48,
            "3-5 (Numeric)": 49,
            "0-3 (Numeric)": 50,
            "Other": 99,
            "No Rating": 100,
        }
        return rating_hierarchy.get(category, 999)

    rating_distribution_list.sort(key=rating_hierarchy_key)

    # Most crawled performers (sorted by crawls, not rating)
    most_crawled = conn.execute("""
        SELECT * FROM performers
        WHERE crawls IS NOT NULL
        ORDER BY crawls DESC LIMIT 10
    """).fetchall()

    conn.close()

    # Convert rows to dictionaries
    most_crawled_list = [dict(row) for row in most_crawled]

    return jsonify(
        {
            "total_performers": total_performers,
            "rated_performers": rated_performers,
            "avg_rating": avg_alphabetical_rating,  # Using alphabetical average
            "numeric_avg_rating": avg_numeric_rating,  # Numeric average as backup
            "top_rated": top_rated,
            "bottom_rated": bottom_rated,
            "rating_distribution": rating_distribution_list,
            "most_crawled": most_crawled_list,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5001)
