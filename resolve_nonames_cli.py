#!/usr/bin/env python3
"""
Resolve NO_NAME items by matching against known performers and,
as fallback, extracting names from slugs/titles.

Two-phase workflow:
  1. FAST auto-assign (slug/title substring match) — seconds, ~20-25% hit rate
  2. DEEP review (fuzzy + LLM hinted) — slower, interactive or batch

Usage:
    uv run python resolve_nonames_cli.py --help
    uv run python resolve_nonames_cli.py --fast          # Phase 1: fast auto-assign (all items)
    uv run python resolve_nonames_cli.py --fast --batch 2000
    uv run python resolve_nonames_cli.py --stats         # show current state
    uv run python resolve_nonames_cli.py --deep          # Phase 2: interactive review
    uv run python resolve_nonames_cli.py --deep --no-llm # skip LLM, fuzzy only
    uv run python resolve_nonames_cli.py --apply         # apply saved results to DB
"""

import re
import json
import os
import sys
import time
from urllib.parse import urlparse
from typing import Optional, List, Tuple

from rapidfuzz import fuzz, process

from performer_repository import SqlitePerformerRepository
from llm_client import LLMClient, UniInferLLMClient, FakeLLMClient

RESULTS_FILE = "noname_results.jsonl"
CHECKPOINT_FILE = "noname_checkpoint.json"
BATCH_SIZE = 50
FAST_BATCH = 5000


# ── STOP words (never part of a performer name) ────────────
from constants import STOP, COMMON_NOISE

# Common English words that should never be a performer name by themselves.
# If ALL words in an LLM-extracted candidate are in this set and the candidate
# isn't in any DB, reject it as descriptive noise.


# ═══════════════════════════════════════════════════════════
#  Data loading
# ═══════════════════════════════════════════════════════════

def load_performer_db(repo: SqlitePerformerRepository):
    """Build matching data structures. Returns (known: name->id, known_names: list, multi_slugs, single_slugs)."""
    all_performers = repo.get_all()
    known = {}
    multi_slugs: list[tuple[str, int, str]] = []
    single_slugs: list[tuple[str, int, str]] = []
    for r in all_performers:
        pid, name = r["id"], r["name"]
        if name == "NO_NAME":
            continue
        known[name] = pid
        perf_slug = re.sub(r'[^a-z0-9_]', '', name.lower().replace(' ', '_'))
        if not perf_slug or len(perf_slug) < 4:
            continue
        if '_' in perf_slug and len(perf_slug) >= 6:
            multi_slugs.append((perf_slug, pid, name))
        elif len(perf_slug) >= 4:
            single_slugs.append((perf_slug, pid, name))
    multi_slugs.sort(key=lambda x: -len(x[0]))
    single_slugs.sort(key=lambda x: -len(x[0]))
    return known, list(known.keys()), multi_slugs, single_slugs


def slug_from_url(url: str) -> str:
    """Extract URL path tail as slug."""
    if not url:
        return ""
    path = urlparse(url).path.strip("/")
    return path.rsplit("/", 1)[-1] if "/" in path else path


# ═══════════════════════════════════════════════════════════
#  PHASE 1: Fast slug/title substring matching (NO fuzzy)
# ═══════════════════════════════════════════════════════════

def fast_match_item(
    url: str, title: str,
    multi_slugs: List[Tuple[str, int, str]],
    single_slugs: List[Tuple[str, int, str]],
) -> Optional[Tuple[str, int, int]]:
    """
    Fast high-precision matching. ONLY multi-word slug substrings.
    Single-word and title-only matches excluded — too many false
    positives ("novinha", "brazil", "essa" in slugs matching fake DB entries).
    Returns (name, pid, 100) or None.
    """
    slug = slug_from_url(url)
    slug_padded = f"_{slug}_" if slug else ""
    if not slug_padded:
        return None
    for perf_slug, pid, name in multi_slugs:
        if f"_{perf_slug}_" in slug_padded:
            return (name, pid, 100)
    return None


# (new-name extraction disabled: false positive rate too high for automated extraction)
# Use Phase 2 (deep review) to manually add new performers.


def load_refdb_slugs(repo: SqlitePerformerRepository) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Load refdb_models names as (slug, name) lists for matching."""
    rows = repo.get_refdb_names()

    multi = []
    single = []
    for name in rows:
        s = re.sub(r'[^a-z0-9_]', '', name.lower().replace(' ', '_'))
        if not s or len(s) < 4:
            continue
        if '_' in s and len(s) >= 6:
            multi.append((s, name))
        elif len(s) >= 4:
            single.append((s, name))
    multi.sort(key=lambda x: -len(x[0]))
    single.sort(key=lambda x: -len(x[0]))
    return multi, single


def phase2_hybrid_assign(
    repo: SqlitePerformerRepository,
    items: List[dict],
    known_ids: dict,
    known_names: list,
    perf_multi: list,
    perf_single: list,
    refdb_multi: list,
    refdb_single: list,
    scene_map: dict,
    llm: LLMClient,
) -> int:
    """
    Phase 2: Hybrid matching pipeline.

    Stage 1 — RefDB slug substring match (fast, high precision)
    Stage 2 — Fuzzy match + title-text verification (medium speed)
    Stage 3 — LLM hinted extraction (slow, for hard cases)

    Returns number of items assigned.
    """
    from rapidfuzz import fuzz, process

    assigned = 0
    stage1 = 0
    stage2 = 0
    stage3 = 0
    skipped = 0

    for i, item in enumerate(items):
        url = item.get("item_url", "") or ""
        title = item.get("title", "") or ""
        slug_str = slug_from_url(url)
        slug_padded = f"_{slug_str}_" if slug_str else ""

        title_lower = ""
        if title:
            t = re.sub(r'[^a-z0-9 ]', ' ', title.lower())
            title_lower = f" {re.sub(r'\s+', ' ', t).strip()} "

        # ── Stage 1: RefDB slug substring match ──
        match = None
        for ref_slug, ref_name in refdb_multi:
            if slug_padded and f"_{ref_slug}_" in slug_padded:
                match = ref_name
                break

        if match:
            pid = known_ids.get(match)
            if pid:
                repo.assign_item(item["id"], pid)
                repo.add_url(pid, url)
                save_result(item["id"], pid, match, url, title, "refdb-slug")
                assigned += 1
                stage1 += 1
                if assigned % 200 == 0:
                    repo._conn().commit()
            continue

        # ── Stage 2: Fuzzy + title verification ──
        # Build candidate pool from refdb + performer multi-word names
        candidates = []

        # Fuzzy against refdb multi-word names
        slug_words = slug_str.replace('_', ' ') if slug_str else ""
        if len(slug_words) >= 6:
            multi_names = [n for _, n in refdb_multi]
            best = process.extractOne(slug_words, multi_names, scorer=fuzz.partial_ratio, score_cutoff=80)
            if best:
                candidates.append((best[0], int(best[1]), "refdb-fuzzy"))

        # Fuzzy against performer multi-word names
        if len(slug_words) >= 6:
            perf_multi_names = [n for _, _, n in perf_multi]
            best = process.extractOne(slug_words, perf_multi_names, scorer=fuzz.partial_ratio, score_cutoff=80)
            if best:
                candidates.append((best[0], int(best[1]), "perf-fuzzy"))

        # Title pattern extraction + fuzzy
        cands = extract_title_candidates(title)
        for cand in cands:
            m = fuzzy_match_candidate(cand, known_names, known_ids, cutoff=75)
            if m:
                candidates.append((m[0], m[2], "fuzzy-title"))

        # Deduplicate and sort by score
        seen = set()
        unique_cands = []
        for name, score, source in sorted(candidates, key=lambda x: -x[1]):
            if name not in seen:
                seen.add(name)
                unique_cands.append((name, score, source))

        # Title verification: only accept if the name (or key parts) appear in title
        verified = []
        for name, score, source in unique_cands:
            name_lower = name.lower()
            parts = name_lower.split()
            # Check if full name or both words appear in title
            in_title = False
            if len(parts) >= 2:
                # Both name parts should appear in title
                if all(part in (title_lower or "") for part in parts):
                    in_title = True
            elif len(parts) == 1 and len(parts[0]) >= 5:
                if parts[0] in (title_lower or ""):
                    in_title = True
            if in_title:
                verified.append((name, score, source))

        if verified:
            name, score, source = verified[0]
            pid = known_ids.get(name)
            if pid:
                repo.assign_item(item["id"], pid)
                repo.add_url(pid, url)
                save_result(item["id"], pid, name, url, title, source)
                assigned += 1
                stage2 += 1
                if assigned % 200 == 0:
                    repo._conn().commit()
            continue

        # ── Stage 3: LLM hinted extraction (only for items with good slug context) ──
        if len(slug_words) >= 8:
            # Build top-5 from all candidates (even without title verification)
            all_cands = unique_cands[:5] if unique_cands else []
            if all_cands:
                hint_names = [c[0] for c in all_cands]
                raw = llm_hinted_extract(title, slug_str, hint_names, llm)
                if raw:
                    raw_lower = raw.lower()
                    for cand_name in hint_names:
                        if cand_name.lower() in raw_lower:
                            pid = known_ids.get(cand_name)
                            if pid:
                                repo.assign_item(item["id"], pid)
                                repo.add_url(pid, url)
                                save_result(item["id"], pid, cand_name, url, title, "llm-hinted")
                                assigned += 1
                                stage3 += 1
                                if assigned % 200 == 0:
                                    repo._conn().commit()
                            break

        # Count as skipped if no stage matched
        skipped += 1
        if (i + 1) % 1000 == 0:
            print(f"    Progress: {i+1}/{len(items)} items, {assigned} assigned (S1={stage1}, S2={stage2}, S3={stage3})")
            repo._conn().commit()

    repo._conn().commit()
    print(f"\n  Hybrid results: {assigned} assigned (refdb-slug={stage1}, fuzzy-verified={stage2}, llm={stage3}), {skipped} skipped")
    return assigned


def phase1_fast_auto_assign(
    repo: SqlitePerformerRepository,
    items: List[dict],
    known_ids: dict,
    multi_slugs: list,
    single_slugs: list,
    scene_map: dict,
) -> int:
    """
    Phase 1: Fast slug/title substring matching.
    Assigns directly to DB when match found.
    Returns number of items assigned.
    """
    assigned = 0

    for i, item in enumerate(items):
        url = item.get("item_url", "") or ""
        title = item.get("title", "") or ""

        # Scene map check
        if url in scene_map:
            pid = scene_map[url]
            repo.assign_item(item["id"], pid)
            save_result(item["id"], pid, "?scene", url, title, "scene")
            assigned += 1
            if assigned % 200 == 0:
                repo._conn().commit()
            continue

        # Fast match against DB
        match = fast_match_item(url, title, multi_slugs, single_slugs)
        if match:
            name, pid, score = match
            repo.assign_item(item["id"], pid)
            repo.add_url(pid, url)
            save_result(item["id"], pid, name, url, title, f"slug-{score}")
            assigned += 1
            if assigned % 200 == 0:
                repo._conn().commit()
            continue

    repo._conn().commit()
    return assigned


# ═══════════════════════════════════════════════════════════
#  PHASE 2: Deep matching (fuzzy + LLM)
# ═══════════════════════════════════════════════════════════

def match_item(url, title, multi_slugs, single_slugs, known_names, known_ids):
    """Full matching with fuzzy — for Phase 2 only. Same as before."""
    results = []
    seen = set()

    slug_padded = ""
    if url:
        slug = slug_from_url(url)
        if slug:
            slug_padded = f"_{slug}_"

    title_lower = ""
    if title:
        t = re.sub(r'[^a-z0-9 ]', ' ', title.lower())
        title_lower = f" {re.sub(r'\s+', ' ', t).strip()} "

    def add(name, score, source):
        if name not in seen:
            seen.add(name)
            results.append((name, score, source))

    # 1. URL slug multi-word substring
    for perf_slug, pid, name in multi_slugs:
        if slug_padded and f"_{perf_slug}_" in slug_padded:
            add(name, 100, "slug")
            break

    # 2. URL slug single-word substring
    if not results:
        for perf_slug, pid, name in single_slugs:
            if slug_padded and f"_{perf_slug}_" in slug_padded:
                add(name, 95, "slug")
                break

    # 3. Title substring match
    if not results and title_lower:
        for perf_slug, pid, name in multi_slugs:
            key = perf_slug.replace('_', ' ')
            if f" {key} " in title_lower:
                add(name, 95, "title")
                break
        if not results:
            for perf_slug, pid, name in single_slugs:
                key = perf_slug.replace('_', ' ')
                if len(key) >= 4 and f" {key} " in title_lower:
                    add(name, 90, "title")
                    break

    if results:
        return results

    # 4. Title pattern extraction + fuzzy
    cands = extract_title_candidates(title)
    for cand in cands:
        m = fuzzy_match_candidate(cand, known_names, known_ids, cutoff=75)
        if m:
            name, pid, score = m
            add(name, score, "fuzzy-title")
            break

    # 5. Fuzzy slug full
    if slug_padded:
        slug_words = slug_padded.strip('_').replace('_', ' ')
        multi_names = [n for n in known_names if ' ' in n]
        best = process.extractOne(slug_words, multi_names, scorer=fuzz.partial_ratio, score_cutoff=85)
        if best:
            add(best[0], int(best[1]), "fuzzy-slug-full")

    # 6. Fuzzy bigrams
    if slug_padded:
        slug = slug_padded.strip('_')
        words = re.split(r'_', slug)
        stop_lower = {w.lower() for w in STOP}
        clean = [w for w in words if w and len(w) >= 3 and w not in stop_lower]
        multi_names = [n for n in known_names if ' ' in n]
        for i in range(len(clean) - 1):
            cand = f"{clean[i].title()} {clean[i+1].title()}"
            if len(cand) >= 6:
                m = fuzzy_match_candidate(cand, multi_names, known_ids, cutoff=82)
                if m:
                    name, pid, score = m
                    add(name, score, "fuzzy-slug-bi")
                    break

    # 7. Fuzzy phrase
    if slug_padded:
        slug = slug_padded.strip('_')
        words = re.split(r'_', slug)
        stop_lower = {w.lower() for w in STOP}
        clean = [w for w in words if w and len(w) >= 3 and w not in stop_lower]
        multi_names = [n for n in known_names if ' ' in n]
        for width in (4, 3):
            if len(clean) >= width:
                phrase = ' '.join(w.title() for w in clean[:width])
                m = fuzzy_match_candidate(phrase, multi_names, known_ids, cutoff=78)
                if m:
                    name, pid, score = m
                    add(name, score, "fuzzy-slug-N")
                    break

    results.sort(key=lambda x: -x[1])
    return results


def extract_title_candidates(title: str) -> List[str]:
    """Extract candidate performer names from title."""
    if not title:
        return []
    t = title
    t = re.sub(r'\bhttps?://\S+|www\.\S+|\S+\.(?:com|net|org|io|tv|to|link)\b', '', t, flags=re.I)
    t = re.sub(r'#\w+', '', t)
    t = re.sub(r'\([^)]*\)', '', t)
    t = re.sub(r'\s+', ' ', t).strip()

    candidates = set()

    m = re.match(r'^\s*([A-Z][a-z]+\s+[A-Z][a-z]+)', t)
    if m:
        candidates.add(m.group(1))

    for m in re.finditer(r',\s*([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[,\.]', t):
        candidates.add(m.group(1))

    for m in re.finditer(r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(?:VS|vs|Vs|AND|and|&)', t):
        candidates.add(m.group(1))

    for m in re.finditer(r'\b(?:with|for|meet)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)', t, re.I):
        candidates.add(m.group(1))

    for m in re.finditer(r'\b(?:hot|sexy|beautiful|gorgeous|cute|sweet|young|slutty)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)', t, re.I):
        candidates.add(m.group(1))

    return list(candidates)


def fuzzy_match_candidate(cand: str, known_names: List[str], known_ids: dict, cutoff: int = 80):
    if len(cand) < 5:
        return None
    result = process.extractOne(cand, known_names, scorer=fuzz.token_sort_ratio, score_cutoff=cutoff)
    if result:
        return (result[0], known_ids[result[0]], int(result[1]))
    return None


# ═══════════════════════════════════════════════════════════
#  LLM helpers
# ═══════════════════════════════════════════════════════════


def llm_extract(title: str, llm: LLMClient) -> Optional[str]:
    """
    Two-prompt extraction: try P1 (explicit+examples) first,
    fall back to XML prompt if P1 echoes title (>3 words).
    Returns performer name or None.
    """
    # Prompt 1: explicit with examples (best precision)
    p1 = (
        'Performer name? Reply ONLY name or NONE.\n'
        'Examples:\n'
        'title: Anna De Ville solo anal\n'
        'name: Anna De Ville\n'
        'title: big ass compilation\n'
        'name: NONE\n\n'
        f'Title: {title[:250]}'
    )
    r1 = llm.complete([{"role": "user", "content": p1}], max_tokens=32)
    if r1 is None:
        return None
    r1_clean = r1.strip().strip('.').strip()
    if r1_clean.upper() in ('NONE', 'NON', ''):
        return None
    # If P1 returned 1-3 words, it likely extracted a name
    words = r1_clean.split()
    if 1 <= len(words) <= 3:
        return r1_clean

    # P1 echoed the title (>3 words) — try XML prompt for better extraction
    p2 = f'<title>{title[:250]}</title>\nExtract <name>performer name</name> or <name>NONE</name>.\nAnswer: <name>'
    r2 = llm.complete([{"role": "user", "content": p2}], max_tokens=32)
    if r2 is None:
        return None
    # Extract from XML tags
    parts = r2.split('<name>')
    if len(parts) >= 2:
        extracted = parts[1].split('</name>')[0].strip()
        if extracted.upper() in ('NONE', 'NONE.', '', 'NON'):
            return None
        words2 = extracted.split()
        if 1 <= len(words2) <= 3:
            return extracted
    return None


def llm_hinted_extract(title: str, slug: str, candidates: List[str],
                          llm: LLMClient) -> Optional[str]:
    if not candidates:
        return None

    clean = re.sub(r'\bhttps?://\S+|www\.\S+', '', title, flags=re.I)
    clean = re.sub(r'#\w+', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()[:250]

    choices_str = '\n'.join(f"{i+1}. {n}" for i, n in enumerate(candidates))
    prompt = (
        f"Video title: {clean}\n"
        f"URL slug: {slug}\n\n"
        "Which performer(s) from this list are in the video?\n"
        f"{choices_str}\n\n"
        "Reply with just the number(s) separated by commas, or 0 if none match."
    )

    try:
        content = llm.complete([{"role": "user", "content": prompt}], max_tokens=16)
    except Exception:
        return None
    nums = re.findall(r'\d+', content)
    selected = [int(n) for n in nums if n.isdigit()]
    if 0 in selected:
        return None
    names = []
    for n in selected:
        if 1 <= n <= len(candidates):
            names.append(candidates[n-1])
    return ", ".join(names) if names else None


def llm_try_extract(title: str, llm: LLMClient) -> Optional[str]:
    """Open-ended LLM extraction (weak, used as last resort)."""
    prompt = (
        "Extract the female performer name(s) from this video title. "
        "Names are proper nouns (capitalized first+last name). "
        "Ignore: URLs, hashtags, scene words."
        "Reply with names only, comma-separated. If none, reply NONE.\n\n"
        f"Title: {title[:300]}"
    )
    try:
        content = llm.complete([{"role": "user", "content": prompt}], max_tokens=48)
    except Exception:
        return None
    if content is None:
        return None
    if content.upper().strip() in ("NONE", "NONE.", ""):
        return None
    if content.lower().strip() in ("none", "none."):
        return None
    return content


# ═══════════════════════════════════════════════════════════
#  I/O helpers
# ═══════════════════════════════════════════════════════════

def save_result(item_id: int, performer_id: Optional[int], performer_name: Optional[str],
                item_url: str, title: str, method: str):
    with open(RESULTS_FILE, "a") as f:
        f.write(json.dumps({
            "item_id": item_id,
            "performer_id": performer_id,
            "performer_name": performer_name,
            "item_url": item_url,
            "title": title,
            "method": method,
        }) + "\n")


def load_results() -> List[dict]:
    if not os.path.exists(RESULTS_FILE):
        return []
    results = []
    with open(RESULTS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results


def get_processed_ids() -> set:
    return {r["item_id"] for r in load_results()}


# ═══════════════════════════════════════════════════════════
#  Interactive review
# ═══════════════════════════════════════════════════════════

def review_item(item_id, title, url, fuzzy_suggestions, llm_result,
                known_names, known_ids, item_index, total) -> Optional[int]:
    domain = "analvids" if "analvids" in url else "sxyprn" if "sxyprn" in url else "other"
    llm_raw, llm_found = llm_result if llm_result else (None, [])

    print(f"\n{'=' * 65}")
    print(f"  [{item_index}/{total}] {domain}")
    print(f"  Title: {title[:120]}")
    print(f"  URL:   {url[:90]}")
    print(f"{'=' * 65}")

    suggestions = list(fuzzy_suggestions)
    for n in llm_found:
        if not any(n == s[0] for s in suggestions):
            suggestions.append((n, 90, "llm+db"))

    if fuzzy_suggestions:
        print(f"\n  📐 Match suggestions:")
        for i, (name, score, source) in enumerate(fuzzy_suggestions, 1):
            print(f"    [{i}] {name:30s} (score={score}, {source})")
    else:
        print(f"\n  📐 No DB match found")

    if llm_raw:
        print(f"  🤖 LLM raw: {llm_raw[:60]}")
        if llm_found:
            for n in llm_found:
                if not any(n == s[0] for s in fuzzy_suggestions):
                    idx = len(suggestions)
                    print(f"    → In DB: [{idx}] {n}")
        else:
            print(f"    → Not found in DB")

    while True:
        choices = ""
        if suggestions:
            choices += "1-" + str(len(suggestions)) + " / "
        choices += "[m]anual / [s]kip / [q]uit"

        try:
            inp = input(f"\n  ❯ {choices}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if inp == "q":
            print("  Quitting.")
            sys.exit(0)
        if inp == "s":
            print("  Skipped.")
            return None
        if inp == "m":
            name = input("  Enter performer name: ").strip()
            if name:
                if name in known_ids:
                    return known_ids[name]
                result = process.extractOne(name, known_names, scorer=fuzz.token_sort_ratio, score_cutoff=70)
                if result:
                    matched_name, score = result
                    print(f"  → Fuzzy matched '{matched_name}' (score={score})")
                    yn = input("  Accept? [Y/n]: ").strip().lower()
                    if yn != "n":
                        return known_ids[matched_name]
                print(f"  ⚠  '{name}' not found in DB. Skipping.")
                return None
            continue
        if inp.isdigit() and suggestions:
            idx = int(inp) - 1
            if 0 <= idx < len(suggestions):
                return known_ids[suggestions[idx][0]]
        if inp and inp not in ("", "s", "q", "m"):
            if inp in known_ids:
                print(f"  → Exact match for '{inp}'")
                return known_ids[inp]
            result = process.extractOne(inp, known_names, scorer=fuzz.token_sort_ratio, score_cutoff=70)
            if result:
                matched_name, score = result
                print(f"  → Fuzzy matched '{matched_name}' (score={score})")
                if input("  Accept? [Y/n]: ").strip().lower() != "n":
                    return known_ids[matched_name]
        print("  Invalid choice.")


# ═══════════════════════════════════════════════════════════
#  Apply saved results
# ═══════════════════════════════════════════════════════════

def apply_all_results(repo: SqlitePerformerRepository):
    results = load_results()
    if not results:
        print("No saved results found.")
        return
    applied = 0
    for r in results:
        pid = r["performer_id"]
        item_id = r["item_id"]
        if pid is None:
            continue
        repo.assign_item(item_id, pid)
        repo.add_url(pid, r.get("item_url", ""))
        applied += 1
    print(f"✅ Applied {applied} assignments to DB.")


# ═══════════════════════════════════════════════════════════
#  Stats
# ═══════════════════════════════════════════════════════════

def show_stats(repo: SqlitePerformerRepository):
    no_name = repo.get_no_name()
    total = repo.count_unmatched(no_name["id"])

    unmatched = repo.get_unmatched_items(no_name["id"], limit=10000)
    sxyprn = sum(1 for i in unmatched if "sxyprn" in (i.get("item_url") or ""))
    analvids = sum(1 for i in unmatched if "analvids" in (i.get("item_url") or ""))
    other = total - sxyprn - analvids

    results = load_results()
    assigned = sum(1 for r in results if r["performer_id"] is not None)
    skipped = sum(1 for r in results if r["performer_id"] is None)

    scene_map = repo.get_scene_map()
    scene_hits = sum(1 for r in results if r["method"] == "scene")
    slug_hits = sum(1 for r in results if r["method"].startswith("slug"))

    print(f"\n📊 NO_NAME items: {total}")
    print(f"   sxyprn:    {sxyprn:6d}")
    print(f"   analvids:  {analvids:6d}")
    if other:
        print(f"   other:     {other:6d}")
    print(f"")
    print(f"📝 Results file: {len(results)} total")
    print(f"   Assigned:  {assigned:6d}  (scene={scene_hits}, slug={slug_hits})")
    print(f"   Skipped:   {skipped:6d}")
    print(f"")
    print(f"🔍 Scene URLs in DB: {len(scene_map)}")
    print(f"💡 Remaining: {total}")
    print()


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════

def run_llm_pass(repo, llm, all_items, known_ids, known_names,
                refdb_multi, refdb_single) -> int:
    """Open-ended LLM extraction pass over unmatched items.

    Read-assign only (see ADR-0001): never creates performers.
    Returns the number of items assigned.
    """
    from rapidfuzz import fuzz, process
    assigned = 0
    for i, item in enumerate(all_items):
        url = item.get("item_url", "") or ""
        title = item.get("title", "") or ""

        if not title or len(title) < 10:
            save_result(item["id"], None, None, url, title, "skip")
            continue

        # Open-ended extraction with winning prompt
        raw = llm_extract(title, llm)

        if raw:
            name = raw.strip().strip('.').strip()
            parts = name.split()
            stop_lower = {w.lower() for w in STOP}

            # Basic sanity: no stop words, looks like a name
            valid = True
            has_stop = any(p.lower() in stop_lower for p in parts)
            
            # Reject if contains clear stop/descriptive words
            series_words = {'adventures', 'episode', 'volume', 'chapter', 'part', 'season',
                            'compilation', 'collection', 'series', 'studio', 'production', 'presents'}
            has_numbers = any(c.isdigit() for c in name)
            has_series = any(p.lower() in series_words for p in parts)
            too_long = len(parts) > 4
            all_caps = name.isupper() and len(name) > 8
            
            if has_stop or has_numbers or has_series or too_long or all_caps:
                valid = False

            # Accept single-word name ONLY if it fuzzy-matches a known performer
            if valid and len(parts) == 1:
                # Check if partial-ratio match to known_names >= 85
                best = process.extractOne(name, known_names, scorer=fuzz.partial_ratio, score_cutoff=85)
                accepted = False
                if best:
                    # Verify: single word must be a PREFIX of the matched name's first word
                    # (e.g. "Inga" → "Inga Devil" OK; "Lucia" → "Candie Luciani" NOT OK)
                    target_first = best[0].split()[0].lower()
                    if name.lower() == target_first or target_first.startswith(name.lower()):
                        name = best[0]
                        parts = name.split()
                        accepted = True
                if not accepted:
                    # Check refdb
                    for ref_slug, ref_name in refdb_multi:
                        if name.lower() in ref_name.lower():
                            target_first = ref_name.split()[0].lower()
                            if name.lower() == target_first or target_first.startswith(name.lower()):
                                if len(ref_name.split()) >= 2:
                                    name = ref_name
                                    parts = name.split()
                                    accepted = True
                                    break
                    if not accepted:
                        valid = False  # single word not in any DB

            # Multi-word: reject if too many words (>3) or no capitalized start
            if valid and len(parts) >= 2:
                if len(parts) > 3:
                    valid = False
                if not parts[0][0].isupper():
                    valid = False

            # Reject names where ALL words are ≤3 chars (too short for real names)
            if valid:
                if parts and all(len(w) <= 3 for w in parts):
                    valid = False

            # Cross-verify: significant words (≥4 chars) in URL slug
            if valid and url:
                slug = slug_from_url(url)
                sig_words = [p.lower() for p in parts if len(p) >= 4]
                if sig_words:
                    count_in_slug = sum(1 for w in sig_words if w in slug)
                    if len(parts) >= 3:
                        # 3+ word names: need ≥2 significant words in slug (blocks "Catsuit Cat Performers")
                        if count_in_slug < 2:
                            valid = False
                    else:
                        # 1-2 word names: need ≥1 significant word in slug
                        if count_in_slug < 1:
                            valid = False

            if valid:
                pid = known_ids.get(name)

                if pid is None:
                    # Fuzzy match: partial_ratio first (tolerates noise prefixes like "Piss Bille Star" → "Billie Star"),
                    # then token_sort_ratio for full-name precision
                    best = process.extractOne(name, known_names, scorer=fuzz.partial_ratio, score_cutoff=85)
                    if best:
                        # Verify: single-word must be a PREFIX of the matched name's first word
                        # (e.g. "Inga" → "Inga Devil" OK; "Lucia" → "Candie Luciani" NOT OK)
                        orig_words = name.split()
                        target_words = best[0].split()
                        valid_match = False
                        if len(orig_words) == 1:
                            # Single word: must be prefix of the target's first word
                            valid_match = target_words[0].lower().startswith(orig_words[0].lower())
                        else:
                            # Multi-word: use token_sort_ratio
                            tsr = fuzz.token_sort_ratio(name, best[0])
                            valid_match = tsr >= 75
                        if valid_match:
                            name = best[0]
                            pid = known_ids.get(name)
                    if pid is None:
                        best = process.extractOne(name, known_names, scorer=fuzz.token_sort_ratio, score_cutoff=85)
                        if best:
                            name = best[0]
                            pid = known_ids.get(name)

                if pid is None:
                    # Check refdb (read-only match; resolver never creates)
                    for ref_slug, ref_name in refdb_multi:
                        if ref_name.lower() == name.lower():
                            pid = known_ids.get(ref_name)
                            if pid is not None:
                                name = ref_name
                            break

                if pid:
                    repo.assign_item(item["id"], pid)
                    repo.add_url(pid, url)
                    save_result(item["id"], pid, name, url, title, "llm")
                    assigned += 1
                else:
                    save_result(item["id"], None, None, url, title, "llm-fail")
            else:
                save_result(item["id"], None, None, url, title, "llm-reject")
        else:
            save_result(item["id"], None, None, url, title, "llm-skip")

        if (i + 1) % 100 == 0:
            repo._conn().commit()
            print(f"    LLM pass: {i+1}/{len(all_items)} items, {assigned} assigned")

    repo._conn().commit()
    return assigned

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Resolve NO_NAME items")
    parser.add_argument("--stats", action="store_true", help="Show stats")
    parser.add_argument("--apply", action="store_true", help="Apply saved results to DB")

    # Phase 1: fast auto-assign
    parser.add_argument("--fast", action="store_true",
                        help="Phase 1: fast slug/title auto-assign (no fuzzy, no LLM)")
    parser.add_argument("--dry-run", action="store_true",
                        help="With --fast: count potential matches but don't assign")

    # Phase 2: deep review
    parser.add_argument("--deep", action="store_true",
                        help="Phase 2: interactive review with fuzzy + LLM")
    parser.add_argument("--no-llm", action="store_true",
                        help="With --deep: skip LLM, fuzzy only")

    # Phase 3: hybrid (refdb → fuzzy-verified → llm-hinted)
    parser.add_argument("--hybrid", action="store_true",
                        help="Phase 3: hybrid pipeline (refdb slug → fuzzy verified → LLM hinted)")
    parser.add_argument("--llm", action="store_true",
                        help="Stage 3 only: LLM hinted pass on hard remaining items")

    # Common
    parser.add_argument("--model", type=str, default=None,
                        help="LLM model id (default: opencode@deepseek-v4-flash-free)")
    parser.add_argument("--batch", type=int, default=0,
                        help="Items to process (default: 0 = all)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-processed items")

    args = parser.parse_args()

    repo = SqlitePerformerRepository()
    llm = UniInferLLMClient(model=args.model) if args.model else UniInferLLMClient()

    # ── Stats only ──
    if args.stats:
        show_stats(repo)
        return

    # ── Apply ──
    if args.apply:
        apply_all_results(repo)
        return

    no_name_id = repo.get_no_name()["id"]
    known_ids, known_names, multi_slugs, single_slugs = load_performer_db(repo)
    scene_map = repo.get_scene_map()

    # ── Phase 1: Fast auto-assign ──
    if args.fast:
        # Load all unmatched items
        print("📦 Loading unmatched items...")
        all_items = repo.get_unmatched_items(no_name_id, limit=None)
        total = len(all_items)

        # Filter already processed
        if args.resume:
            processed = get_processed_ids()
            old_count = len(all_items)
            all_items = [i for i in all_items if i["id"] not in processed]
            print(f"📋 Resuming — skipping {len(processed)} already processed items ({old_count} → {len(all_items)})")

        if args.batch > 0 and len(all_items) > args.batch:
            all_items = all_items[:args.batch]

        if not all_items:
            print("✅ No items to process!")
            return

        # Dry-run: just count potential matches
        if args.dry_run:
            print(f"📋 Counting potential fast-matches among {len(all_items)} items...")
            t0 = time.time()
            slug_hits = 0
            scene_hits = 0
            for item in all_items:
                url = item.get("item_url", "") or ""
                title = item.get("title", "") or ""
                if url in scene_map:
                    scene_hits += 1
                elif fast_match_item(url, title, multi_slugs, single_slugs):
                    slug_hits += 1
            elapsed = time.time() - t0
            total_hits = scene_hits + slug_hits
            print(f"\n📊 Potential fast-matches: {total_hits}/{len(all_items)} ({total_hits/max(len(all_items),1)*100:.1f}%)")
            print(f"   Scene match: {scene_hits}")
            print(f"   Slug match:  {slug_hits}")
            print(f"   No match:    {len(all_items) - total_hits}")
            print(f"   (computed in {elapsed:.1f}s)")
            return

        print(f"📋 Fast-matching {len(all_items)} items (multi-word slug only)...")
        t0 = time.time()
        assigned = phase1_fast_auto_assign(repo, all_items, known_ids, multi_slugs, single_slugs, scene_map)
        elapsed = time.time() - t0
        print(f"\n✅ Phase 1 done: {assigned}/{len(all_items)} assigned in {elapsed:.1f}s")
        print(f"   Results saved to {RESULTS_FILE}")
        print(f"   Run with --stats to see remaining, --deep for interactive review.")
        return

    # ── Phase 2: Deep interactive review ──
    if args.deep:
        print("📦 Loading unmatched items...")
        all_items = repo.get_unmatched_items(no_name_id, limit=None)
        if args.resume:
            processed = get_processed_ids()
            all_items = [i for i in all_items if i["id"] not in processed]
            print(f"📋 Resuming — skipping {len(processed)} processed items")
        if args.batch > 0 and len(all_items) > args.batch:
            all_items = all_items[:args.batch]

        total = len(all_items)
        if total == 0:
            print("✅ No items to review!")
            return

        print(f"\n🔍 Deep-matching {total} items (fuzzy + {'LLM' if not args.no_llm else 'no LLM'})...")

        # Pre-score all items with full matching (fuzzy included)
        print("  Pre-computing matches...")
        scored = []
        for i, item in enumerate(all_items):
            sys.stdout.write(f"\r  Scoring [{i+1}/{total}]...")
            sys.stdout.flush()
            url = item.get("item_url", "") or ""
            title = item.get("title", "") or ""
            sug = match_item(url, title, multi_slugs, single_slugs, known_names, known_ids)
            scored.append({**item, "fuzzy_suggestions": sug or []})
        print()

        # Interactive review
        print(f"\n  Reviewing {total} items...")
        for i, s in enumerate(scored):
            llm_suggestion = None
            if not s["fuzzy_suggestions"] and not args.no_llm:
                slug = slug_from_url(s.get("item_url", "") or "")
                title_cands = extract_title_candidates(s.get("title", "") or "")
                hint_cands = []
                for cand in title_cands:
                    m = fuzzy_match_candidate(cand, known_names, known_ids, cutoff=70)
                    if m:
                        hint_cands.append(m[0])
                if slug:
                    words = re.split(r'_', slug)
                    stop_lower = {w.lower() for w in STOP}
                    clean = [w for w in words if w and len(w) >= 3 and w not in stop_lower]
                    for j in range(len(clean) - 1):
                        cand = f"{clean[j].title()} {clean[j+1].title()}"
                        if len(cand) >= 6:
                            m = fuzzy_match_candidate(cand, known_names, known_ids, cutoff=70)
                            if m and m[0] not in hint_cands:
                                hint_cands.append(m[0])
                seen_hints = set()
                unique_hints = [h for h in hint_cands if not (h in seen_hints or seen_hints.add(h))]
                hint_cands = unique_hints[:5]
                if hint_cands:
                    raw = llm_hinted_extract(s.get("title", "") or "", slug, hint_cands, llm)
                    if raw:
                        raw_lower = raw.lower()
                        found_in_db = [n for n in known_names if n.lower() in raw_lower]
                        llm_suggestion = (raw, found_in_db)

            pid = review_item(
                s["id"], s.get("title", "") or "", s.get("item_url", "") or "",
                s["fuzzy_suggestions"], llm_suggestion,
                known_names, known_ids, i + 1, total,
            )
            if pid:
                pname = {v: k for k, v in known_ids.items()}.get(pid, "?")
                repo.assign_item(s["id"], pid)
                repo.add_url(pid, s.get("item_url", ""))
                save_result(s["id"], pid, pname, s.get("item_url", ""), s.get("title", "") or "", "review")
                print(f"  ✅ Assigned '{pname}'")
            else:
                save_result(s["id"], None, None, s.get("item_url", ""), s.get("title", "") or "", "skip")

        total_assigned = sum(1 for r in load_results() if r["performer_id"] is not None)
        print(f"\n{'=' * 65}")
        print(f"  Session done. Total assigned so far: {total_assigned}")
        return

    # ── Default: show usage ──
    # ── Phase 3: Hybrid pipeline ──
    if args.hybrid:
        print("📦 Loading unmatched items...")
        all_items = repo.get_unmatched_items(no_name_id, limit=None)
        if args.resume:
            processed = get_processed_ids()
            all_items = [i for i in all_items if i["id"] not in processed]
            print(f"📋 Resuming — skipping {len(processed)} processed items")
        if args.batch > 0 and len(all_items) > args.batch:
            all_items = all_items[:args.batch]

        if not all_items:
            print("✅ No items to process!")
            return

        print(f"📋 Hybrid pipeline on {len(all_items)} items (refdb → fuzzy → LLM)...")
        print("📦 Loading refdb model names...")
        refdb_multi, refdb_single = load_refdb_slugs(repo)
        print(f"   RefDB multi-word: {len(refdb_multi)}, single-word: {len(refdb_single)}")

        t0 = time.time()
        assigned = phase2_hybrid_assign(
            repo, all_items, known_ids, known_names,
            multi_slugs, single_slugs,
            refdb_multi, refdb_single, scene_map,
            llm,
        )
        elapsed = time.time() - t0
        print(f"\n✅ Phase 3 done: {assigned}/{len(all_items)} assigned in {elapsed:.1f}s")
        print(f"   Results saved to {RESULTS_FILE}")
        print(f"   Run with --stats to see remaining.")
        return

    # ── Stage 3-only: LLM pass on hard remaining items ──
    if args.llm:
        print("📦 Loading unmatched items...")
        all_items = repo.get_unmatched_items(no_name_id, limit=None)
        if args.resume:
            processed = get_processed_ids()
            all_items = [i for i in all_items if i["id"] not in processed]
            print(f"📋 Resuming — skipping {len(processed)} processed items")
        if args.batch > 0 and len(all_items) > args.batch:
            all_items = all_items[:args.batch]

        if not all_items:
            print("✅ No items to process!")
            return

        print(f"🤖 LLM pass on {len(all_items)} items (open-ended extraction)...")
        print("📦 Loading refdb model names...")
        refdb_multi, refdb_single = load_refdb_slugs(repo)
        t0 = time.time()
        assigned = 0

        assigned = run_llm_pass(repo, llm, all_items, known_ids, known_names, refdb_multi, refdb_single)
        elapsed = time.time() - t0
        print(f"\n🤖 LLM pass done: {assigned}/{len(all_items)} assigned in {elapsed:.1f}s")
        return

    parser.print_help()
    print("\n\nRun --stats to see current state, --fast to auto-assign, --hybrid for refdb+fuzzy+LLM.")


if __name__ == "__main__":
    main()
