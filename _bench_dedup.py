#!/usr/bin/env python3
"""Benchmark dedup algorithms against real performer data."""

import sqlite3
import difflib
import time
import rapidfuzz
from rapidfuzz import fuzz
import jellyfish

# ── Load real names from DB ──────────────────────────────────
conn = sqlite3.connect("performers.db")
c = conn.cursor()
c.execute("SELECT name FROM performers WHERE name != 'NO_NAME'")
all_names = [r[0] for r in c.fetchall()]
conn.close()

print(f"Loaded {len(all_names)} performer names from DB\n")

# ── Test pairs ───────────────────────────────────────────────
# (name1, name2, should_match, comment)
test_pairs = [
    # ── Should match (typos, case, compound) ──
    ("Evelyn turner", "Evelyn Turner", True, "case diff"),
    ("Vitoria Beatriz", "Victoria Beatriz", True, "single char typo"),
    ("Yenifer Chacon", "Yennifer Chacon", True, "n vs nn"),
    ("Anna Deville", "Anna De Ville", True, "compound word"),
    ("Ani Blackfox", "Ani Black Fox", True, "compound word 2"),
    ("Sasha Beart", "Sasha Be Art", True, "compound word 3"),
    ("Buttplug Betty", "Butt Plug Betty", True, "compound word 4"),
    ("AllisonSweet", "Allison Sweet", True, "no space"),
    ("LindaHouston", "Linda Houston", True, "no space 2"),
    ("Jazmine", "Jasmine", True, "phonetic"),
    ("Charly Summer", "Charly Summers", True, "plural"),
    ("Lucia Denvile", "Lucia Denville", True, "single char"),
    ("Rebeca Villar", "Rebecca Villar", True, "b vs bb"),
    ("Christina Cielo", "Cristina Cielo", True, "h diff"),
    ("Harper Maddox", "Harper Maddoxx", True, "extra letter"),

    # ── Should NOT match (different people, shared words) ──
    ("Violette", "Violette Pure", False, "first name vs full"),
    ("Anna", "Annie", False, "different name"),
    ("Anna", "Ania", False, "different name 2"),
    ("Lina", "Liana", False, "different name 3"),
    ("Lily", "Lilly", False, "different name 4"),
    ("Jessica", "Jessika", False, "differs by 1 char but could be different"),
    ("Sofia", "Sofie", False, "different name 5"),
    ("Jazmine", "Jasmine White", False, "first vs full name"),
    ("Beatriz", "Beatrix", False, "different name 6"),
    ("Cristal", "Christal", False, "different spelling?"),
    ("Valentine", "Valentina", False, "different name 7"),
    ("Selina", "Selena", False, "different name 8"),
    ("Sunny Jay", "Sunny Day", False, "different last name"),
    ("Lady Zee", "Lady Dee", False, "different last name 2"),
    ("Tina Fire", "Tina Fine", False, "different last name 3"),
    ("Bella Grey", "Bella Gray", False, "different last name 4"),
    ("Aya", "Arya", False, "different name"),
    ("Billy Star", "Billie Star", False, "different first name"),
    ("Kyra Sex", "Kira Sex", False, "different first name 2"),
    ("Veronika", "Veronica", False, "different name 9"),
]

# ── Algorithms to test ───────────────────────────────────────
def algo_difflib(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100

def algo_rapidfuzz_ratio(a, b):
    return fuzz.ratio(a.lower(), b.lower())

def algo_rapidfuzz_token_sort(a, b):
    return fuzz.token_sort_ratio(a.lower(), b.lower())

def algo_rapidfuzz_token_set(a, b):
    return fuzz.token_set_ratio(a.lower(), b.lower())

def algo_rapidfuzz_token(a, b):
    return fuzz.token_ratio(a.lower(), b.lower())

def algo_rapidfuzz_partial(a, b):
    return fuzz.partial_ratio(a.lower(), b.lower())

def algo_rapidfuzz_wratio(a, b):
    return fuzz.WRatio(a.lower(), b.lower())

def algo_jellyfish_jaro(a, b):
    return jellyfish.jaro_similarity(a.lower(), b.lower()) * 100

def algo_jellyfish_jaro_winkler(a, b):
    return jellyfish.jaro_winkler_similarity(a.lower(), b.lower()) * 100

def algo_jellyfish_levenshtein(a, b):
    dist = jellyfish.levenshtein_distance(a.lower(), b.lower())
    max_len = max(len(a), len(b))
    return (1 - dist / max_len) * 100 if max_len > 0 else 100

def algo_jellyfish_damerau(a, b):
    dist = jellyfish.damerau_levenshtein_distance(a.lower(), b.lower())
    max_len = max(len(a), len(b))
    return (1 - dist / max_len) * 100 if max_len > 0 else 100

def algo_rapidfuzz_jaro(a, b):
    return rapidfuzz.distance.JaroWinkler.similarity(a.lower(), b.lower()) * 100

algorithms = [
    ("difflib (aktuell)", algo_difflib),
    ("rapidfuzz ratio", algo_rapidfuzz_ratio),
    ("rapidfuzz token_sort", algo_rapidfuzz_token_sort),
    ("rapidfuzz token_set", algo_rapidfuzz_token_set),
    ("rapidfuzz token", algo_rapidfuzz_token),
    ("rapidfuzz partial", algo_rapidfuzz_partial),
    ("rapidfuzz WRatio", algo_rapidfuzz_wratio),
    ("rapidfuzz JaroWinkler", algo_rapidfuzz_jaro),
    ("jellyfish jaro", algo_jellyfish_jaro),
    ("jellyfish jaro_winkler", algo_jellyfish_jaro_winkler),
    ("jellyfish levenshtein", algo_jellyfish_levenshtein),
    ("jellyfish damerau", algo_jellyfish_damerau),
]

# ── Score matrix ─────────────────────────────────────────────
print(f"{'Algorithmus':30s} {'Acc':>5s} {'FP':>4s} {'FN':>4s} {'Best Cut':>10s} {'Speed':>8s}")
print("─" * 70)

for name, algo_fn in algorithms:
    scores_should = []
    scores_should_not = []

    for a, b, should, _ in test_pairs:
        score = algo_fn(a, b)
        if should:
            scores_should.append(score)
        else:
            scores_should_not.append(score)

    # Find best cutoff
    best_cutoff = 0
    best_acc = 0
    for cutoff in range(50, 100):
        c_correct = 0
        for a, b, should, _ in test_pairs:
            score = algo_fn(a, b)
            match = score >= cutoff
            if match == should:
                c_correct += 1
        if c_correct > best_acc:
            best_acc = c_correct
            best_cutoff = cutoff

    # Calculate FP/FN at best cutoff
    my_fp = 0
    my_fn = 0
    for a, b, should, _ in test_pairs:
        score = algo_fn(a, b)
        match = score >= best_cutoff
        if should and not match:
            my_fn += 1
        if not should and match:
            my_fp += 1

    # Speed test
    t0 = time.perf_counter()
    for _ in range(500):
        for a, b, _, _ in test_pairs:
            algo_fn(a, b)
    t = time.perf_counter() - t0

    print(f"{name:30s} {best_acc/len(test_pairs)*100:4.0f}% {my_fp:4d} {my_fn:4d} {f'{best_cutoff}%':>10s} {t*1000:6.1f}ms")

# ── Show best cutoff per algo with detail ────────────────────
def _detail(name, algo_fn, cutoffs=[75, 80, 82, 85, 88, 90]):
    print(f"\n── Detail: {name} ──")
    for cutoff in cutoffs:
        my_fp = []
        my_fn = []
        for a, b, should, comment in test_pairs:
            score = algo_fn(a, b)
            match = score >= cutoff
            if should and not match:
                my_fn.append((a, b, score, comment))
            if not should and match:
                my_fp.append((a, b, score, comment))
        print(f"\nCutoff {cutoff}%: {len(my_fp)} FP, {len(my_fn)} FN")
        if my_fp:
            for a, b, s, c in my_fp:
                print(f"  FP: {a:25s} {b:25s} ({s:.0f}) {c}")
        if my_fn:
            for a, b, s, c in my_fn:
                print(f"  FN: {a:25s} {b:25s} ({s:.0f}) {c}")

_detail("rapidfuzz token_sort", algo_rapidfuzz_token_sort)
_detail("rapidfuzz JaroWinkler", algo_rapidfuzz_jaro)
_detail("jellyfish jaro_winkler", algo_jellyfish_jaro_winkler)
_detail("rapidfuzz token_ratio", algo_rapidfuzz_token)
_detail("rapidfuzz WRatio", algo_rapidfuzz_wratio)
