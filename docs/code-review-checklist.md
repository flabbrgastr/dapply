# Code Review Checklist — dapply

Generated from a repo review. Track progress by ticking boxes.

## Priority fixes (cheap, high-value)

- [x] **1. Gitignore `noname_results.jsonl`** — resolver output (`RESULTS_FILE`) is
      committed to git; `*.jsonl` is already ignored so just `git rm --cached` it.
- [x] **2. De-duplicate shared constants** — move `STOP`, `COMMON_NOISE`
      (`resolve_nonames_cli.py`) and `USER_AGENTS` (3 scraper files) into a single
      `constants.py`; import everywhere. `dbadd.py`'s `STOP` is a subset of the
      resolver's, so one canonical set covers both.
- [x] **3. Kill the 3 bare `except:`** — `dbadd.py:790`, `db_viewer.py:677`,
      `scrape_refdb_full.py:256` → `except Exception:` (so `KeyboardInterrupt` /
      `SystemExit` still propagate).
- [x] **4. Add a `dbadd` ingest test** — parse a sample row/HTML → assert
      performer/item rows. Covers the riskiest untested path.
- [ ] **5. Split `db_viewer.py`** — routes / query layer / rendering (currently
      784 LOC, 27 flat defs, 0 methods).

## Tracked findings (no immediate action)

- [ ] Committed mutable artifact: `noname_results.jsonl` (fixed by #1).
- [x] `dbadd.parse_item_date` mixed local time (empty branch) and UTC (other
      branches) in the same `item_date` column — fixed in #4.
- [ ] `STOP`/`COMMON_NOISE` duplicated across modules (fixed by #2).
- [ ] `USER_AGENTS` defined in 3 files (fixed by #2).
- [ ] God modules: `resolve_nonames_cli.py` (1284), `performer_repository.py`
      (1484), `db_viewer.py` (784), `orchestator.py` (754), `scraper.py` (646).
- [ ] 3 bare `except:` + 22 `except Exception` (bare ones fixed by #3).
- [ ] 221 `print()` calls, no `logging` strategy (cron path).
- [ ] Test coverage gaps: `dbadd`, `db_viewer`, `orchestator` core, thumb scripts.
- [ ] Dead code: `insert_item` has no callers; `_bench_dedup.py` stray;
      `refdb.py` vs `scrape_refdb_full.py` overlap.
- [ ] Inconsistent typing on resolver functions (`phase2_hybrid_assign`,
      `run_llm_pass`, `match_item` lost annotations).
- [ ] `db_viewer.py` flat layout (27 defs, 0 methods).

## What's good (keep)

- [ ] Repository pattern (`performer_repository.py`) — clean ABC + 2 adapters.
- [ ] `LLMClient` port (`llm_client.py`) — thin transport + `FakeLLMClient`.
- [ ] ADR practice (`docs/adr/0001`).
- [ ] Resolver is read-assign only; LLM behind a port; `--model` flag.
- [ ] Reusable LLM benchmark framework.
- [ ] `AGENTS.md` with commands, git flow, ADR link.
