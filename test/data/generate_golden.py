#!/usr/bin/env python3
"""Generate golden test sets for LLM extraction benchmarks from the database."""

import sqlite3, json, random, argparse, os, sys

def generate(output_dir: str = "test/data", n_positive: int = 50, n_negative: int = 50):
    db_path = "performers.db"
    if not os.path.exists(db_path):
        print(f"ERROR: {db_path} not found. Run from project root.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # ── Positive: items with performer names in title ──
    c.execute('''
        SELECT i.title, p.name FROM items i 
        JOIN performers p ON i.performer_id = p.id 
        WHERE i.performer_id != 33 AND p.name != 'NO_NAME'
          AND i.title IS NOT NULL AND LENGTH(i.title) > 10 AND LENGTH(p.name) >= 5
        ORDER BY RANDOM() LIMIT ?
    ''', (n_positive * 3,))  # oversample to filter

    positive = []
    for title, pname in c.fetchall():
        name_lower = pname.lower()
        title_lower = title.lower()
        if name_lower in title_lower and len(positive) < n_positive:
            positive.append({
                "title": title,
                "expected": pname,
                "type": "has_name",
                "slug": ""
            })

    # ── Negative: NO_NAME items ──
    c.execute('''
        SELECT title FROM items 
        WHERE performer_id = 33 AND title IS NOT NULL AND LENGTH(title) > 15
        ORDER BY RANDOM() LIMIT ?
    ''', (n_negative,))

    negative = [{
        "title": row[0],
        "expected": "NONE",
        "type": "no_name",
        "slug": ""
    } for row in c.fetchall()]

    conn.close()

    # ── Write files ──
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "llm_extract_positive.json"), 'w') as f:
        json.dump({"name": "Positive (has performer name)", "cases": positive}, f, indent=2)

    with open(os.path.join(output_dir, "llm_extract_negative.json"), 'w') as f:
        json.dump({"name": "Negative (no performer name)", "cases": negative}, f, indent=2)

    mixed = positive + negative
    random.shuffle(mixed)
    with open(os.path.join(output_dir, "llm_extract_mixed.json"), 'w') as f:
        json.dump({"name": "Mixed golden set", "cases": mixed}, f, indent=2)

    print(f"Generated:")
    print(f"  Positive: {len(positive)}")
    print(f"  Negative: {len(negative)}")
    print(f"  Mixed:    {len(mixed)}")
    print(f"  → {output_dir}/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate golden test sets")
    parser.add_argument("--dir", "-d", default="test/data", help="Output directory")
    parser.add_argument("--positive", "-p", type=int, default=50, help="Positive cases count")
    parser.add_argument("--negative", "-n", type=int, default=50, help="Negative cases count")
    args = parser.parse_args()
    generate(args.dir, args.positive, args.negative)
