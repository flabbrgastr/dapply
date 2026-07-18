#!/usr/bin/env python3
"""
LLM Name Extraction Benchmark — extract+ground approach.

Pipeline:
  1. Model extracts candidate name from title
  2. Grounding check against performer DB
  3. Report grounded hits vs ungrounded vs missed

Usage:
  # Quick smoke test
  uv run python test/benchmark/llm_extract.py --quick

  # Full benchmark
  uv run python test/benchmark/llm_extract.py --cases test/data/llm_extract_mixed.json

  # Test specific models
  uv run python test/benchmark/llm_extract.py \\
    --model "opencode@deepseek-v4-flash-free" \\
    --model "ollama@qwen3.5:0.8b"
"""

import json, time, sys, os, argparse, re, sqlite3
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from collections import Counter

try:
    import requests, urllib3
    urllib3.disable_warnings()
except ImportError:
    print("ERROR: requests required. Run: uv sync"); sys.exit(1)

# ── Defaults ─────────────────────────────────────────────────

DEFAULT_API_URL = "https://amd1.mooo.com:8123/v1/chat/completions"
DEFAULT_API_KEY = "test23@test34"
DEFAULT_DB = "performers.db"

DEFAULT_PROMPT = """From this adult video title, extract any performer name that appears.
Rules:
- Performer names are typically a person's name (first + last or stage name)
- Names often appear at the start: "Performer Name does X" or "Performer Name - title"
- If a name MIGHT be present, extract it — be extractive
- Return just the name, or "NONE" if clearly no name
- Examples: "Yessica Bunny first anal" → Yessica Bunny
  "Teen gets fucked" → NONE
  "Gabily Castro assfucked" → Gabily Castro"""

# ── Data classes ─────────────────────────────────────────────

@dataclass
class TestCase:
    title: str
    expected: str = "NONE"
    type: str = "no_name"
    slug: str = ""
    performer_id: Optional[int] = None

@dataclass
class GroundingResult:
    grounded: bool = False      # Found in DB?
    performer_id: Optional[int] = None
    performer_name: str = ""
    match_type: str = ""        # "exact" | "word" | "fuzzy" | "none"

@dataclass
class ItemResult:
    title: str
    expected: str
    extracted: str = ""
    grounding: GroundingResult = field(default_factory=GroundingResult)
    time: float = 0.0
    error: str = ""

    @property
    def is_hit(self) -> bool:
        """Grounded hit = model found a name AND it exists in DB."""
        return self.grounding.grounded

    @property
    def is_miss(self) -> bool:
        """Miss = name exists in DB but model didn't find it."""
        return (self.expected != "NONE" and not self.extracted) or \
               (self.expected != "NONE" and self.extracted and not self.grounding.grounded)

    @property
    def is_false_positive(self) -> bool:
        """False positive = model returned a name but it's not in DB."""
        return self.expected == "NONE" and self.extracted and self.extracted.upper() not in ('NONE','','.')

# ── Grounding Engine ─────────────────────────────────────────

class PerformerDB:
    """Grounding against the performer database."""

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._build_index()

    def _build_index(self):
        c = self.conn.cursor()
        c.execute('SELECT id, name FROM performers WHERE name != "NO_NAME"')
        self.all_performers = [(pid, name) for pid, name in c.fetchall()]

        # Indexes
        self.exact_index = {}     # lowercase name → (pid, name)
        self.slug_index = {}      # slug → (pid, name)
        self.word_index = {}      # word → [(pid, name), ...]
        self.name_lower_set = set()
        self.name_words_set = set()

        for pid, name in self.all_performers:
            lower = name.lower()
            self.exact_index[lower] = (pid, name)
            self.name_lower_set.add(lower)

            slug = re.sub(r'[^a-z0-9]', '_', lower).strip('_')
            self.slug_index[slug] = (pid, name)

            for word in lower.split():
                self.name_words_set.add(word)
                if len(word) >= 4:
                    if word not in self.word_index:
                        self.word_index[word] = []
                    self.word_index[word].append((pid, name))

        print(f"  DB index: {len(self.all_performers)} performers, "
              f"{len(self.word_index)} words, "
              f"{len(self.exact_index)} exact", file=sys.stderr)

    def ground(self, name: str) -> GroundingResult:
        """Check if a name exists in the performer DB."""
        result = GroundingResult()
        if not name or name.upper() in ('NONE', '', '.', '...', 'N/A', 'NON', 'NULL', '-'):
            return result

        lower = name.lower().strip()

        # 1. Exact match
        if lower in self.exact_index:
            pid, pname = self.exact_index[lower]
            result.grounded = True
            result.performer_id = pid
            result.performer_name = pname
            result.match_type = "exact"
            return result

        # 2. Slug match
        slug = re.sub(r'[^a-z0-9]', '_', lower).strip('_')
        if slug in self.slug_index:
            pid, pname = self.slug_index[slug]
            result.grounded = True
            result.performer_id = pid
            result.performer_name = pname
            result.match_type = "slug"
            return result

        # 3. Name is a substring of a known name
        for known_lower in self.name_lower_set:
            if lower in known_lower:
                pid, pname = self.exact_index[known_lower]
                result.grounded = True
                result.performer_id = pid
                result.performer_name = pname
                result.match_type = "substring"
                return result

        # 4. Performer name contains this name
        for known_lower in self.name_lower_set:
            if known_lower in lower:
                pid, pname = self.exact_index[known_lower]
                result.grounded = True
                result.performer_id = pid
                result.performer_name = pname
                result.match_type = "contained_in"
                return result

        # 5. Word match — all name words appear in DB names
        words = lower.split()
        matched_words = [w for w in words if len(w) >= 4 and w in self.word_index]
        if matched_words:
            # Find the performer that shares the most words
            word_counts = Counter()
            for w in matched_words:
                for pid, pname in self.word_index[w]:
                    word_counts[(pid, pname)] += 1
            if word_counts:
                (pid, pname), count = word_counts.most_common(1)[0]
                if count >= max(1, len(words) // 2):
                    result.grounded = True
                    result.performer_id = pid
                    result.performer_name = pname
                    result.match_type = f"words({count}/{len(words)})"
                    return result

        return result

    def close(self):
        self.conn.close()

# ── LLM Client ───────────────────────────────────────────────

class LLMClient:
    def __init__(self, api_url: str = DEFAULT_API_URL, api_key: str = DEFAULT_API_KEY):
        self.api_url = api_url
        self.api_key = api_key

    def extract_name(self, model_id: str, title: str, slug: str = "",
                     system_prompt: str = DEFAULT_PROMPT,
                     timeout: int = 20) -> Tuple[str, float]:
        """Call LLM to extract a performer name from a title."""
        t0 = time.time()
        resp = requests.post(self.api_url, json={
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Title: {title}\nURL slug: {slug}\n\nPerformer name:"}
            ],
            "temperature": 0,
            "max_tokens": 48,
            "think": False
        }, headers={"Authorization": f"Bearer {self.api_key}"},
            verify=False, timeout=timeout)

        t = time.time() - t0
        data = resp.json()
        answer = data['choices'][0]['message']['content'].strip()
        answer = answer.split('\n')[0].strip().rstrip('.,!?;: ')
        return answer, t

# ── Benchmark ────────────────────────────────────────────────

class ExtractGroundBenchmark:
    def __init__(self, api_url: str = DEFAULT_API_URL, api_key: str = DEFAULT_API_KEY,
                 db_path: str = DEFAULT_DB):
        self.llm = LLMClient(api_url, api_key)
        self.db = PerformerDB(db_path)
        print(f"", file=sys.stderr)  # blank line after DB init

    def load_cases(self, path: str) -> List[TestCase]:
        with open(path) as f:
            data = json.load(f)
        cases_raw = data.get("cases", data if isinstance(data, list) else [])
        cases = []
        for c in cases_raw:
            tc = TestCase(title=c["title"], expected=c.get("expected", "NONE"),
                          type=c.get("type", "unknown"), slug=c.get("slug", ""),
                          performer_id=c.get("performer_id"))
            cases.append(tc)
        return cases

    def run(self, model_id: str, cases: List[TestCase],
            system_prompt: str = DEFAULT_PROMPT) -> List[ItemResult]:
        results = []
        for i, case in enumerate(cases):
            result = ItemResult(title=case.title, expected=case.expected)
            try:
                extracted, t = self.llm.extract_name(model_id, case.title, case.slug, system_prompt)
                result.extracted = extracted
                result.time = t
                result.grounding = self.db.ground(extracted)
            except Exception as e:
                result.error = str(e)[:100]

            results.append(result)

            # Progress
            if (i+1) % 10 == 0:
                hits = sum(1 for r in results if r.is_hit)
                print(f"  [{i+1}/{len(cases)}] {hits} grounded so far...", file=sys.stderr)

        return results

    def print_results(self, model_id: str, results: List[ItemResult], show: int = 0):
        total = len(results)
        has_names = [r for r in results if r.expected != "NONE"]
        no_names = [r for r in results if r.expected == "NONE"]

        grounded = [r for r in results if r.is_hit]
        ungrounded = [r for r in results if r.extracted and r.extracted.upper() not in ('NONE','','.') and not r.grounding.grounded]
        missed = [r for r in results if r.expected != "NONE" and not r.is_hit]

        grounded_hits = len(grounded)
        false_positives = len(ungrounded)
        misses = len(missed)

        avg_time = sum(r.time for r in results if r.time) / max(total, 1)

        print(f"\n{'─'*66}")
        print(f"  {model_id}")
        print(f"{'─'*66}")
        print(f"  Total cases:  {total}")
        print(f"  Grounded hits: {grounded_hits}/{total} ({grounded_hits/total*100:.0f}%)")
        print(f"  Ungrounded:    {false_positives} (model said name, not in DB)")
        print(f"  Missed names:  {misses} (DB has name, model didn't find it)")
        print(f"  Avg time:      {avg_time:.1f}s")
        print(f"{'─'*66}")

        if show > 0:
            print(f"\n  Grounded hits ({len(grounded)}):")
            for r in grounded[:show]:
                g = r.grounding
                print(f"    ✓ #{g.performer_id} {g.performer_name[:25]:25s} | {r.extracted[:25]:25s} | {r.title[:50]}")
            if false_positives:
                print(f"\n  Ungrounded ({false_positives}):")
                for r in ungrounded[:show]:
                    print(f"    ✗ {r.extracted[:30]:30s} | {r.title[:55]}")
            if misses and has_names:
                print(f"\n  Missed ({misses}):")
                for r in missed[:show]:
                    print(f"    ? expected={r.expected[:20]:20s} | {r.title[:60]}")

    def close(self):
        self.db.close()

# ── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LLM Extract+Ground Benchmark")
    parser.add_argument("--model", "-m", action="append", help="Model(s) to test")
    parser.add_argument("--cases", "-c", default="test/data/llm_extract_mixed.json")
    parser.add_argument("--quick", "-q", action="store_true")
    parser.add_argument("--show", "-s", type=int, default=5, help="Show N details")
    parser.add_argument("--output", "-o", help="Save results JSON")
    args = parser.parse_args()

    benchmark = ExtractGroundBenchmark()
    cases = benchmark.load_cases(args.cases)

    if args.quick:
        cases = cases[:10]

    models = args.model or [
        "ollama@qwen3.5:0.8b",
        "opencode@deepseek-v4-flash-free",
    ]

    print(f"Loaded {len(cases)} test cases")

    for model_id in models:
        results = benchmark.run(model_id, cases)
        benchmark.print_results(model_id, results, show=args.show)

        if args.output:
            out_path = args.output.replace(".json", f"_{model_id.split('@')[-1][:20]}.json")
            with open(out_path, 'w') as f:
                json.dump([asdict(r) for r in results], f, indent=2, default=str)
            print(f"  Saved: {out_path}")

    benchmark.close()

if __name__ == "__main__":
    main()
