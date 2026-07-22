# Agent Guidelines for Dapply Project

## Build, Lint, and Test Commands

This Python project uses `uv` as the package and environment manager.

```bash
# Install dependencies (creates .venv + uv.lock)
uv sync
uv sync --extra dev     # includes pytest

# Run tests
uv run pytest test/unit/ -v

# --- Daily sxyprn update (re-scrape page 0 for fresh performers) ---
uv run python orchestator.py --daily

# Scrape 3 fresh pages from each site
uv run python orchestator.py

# More pages or specific site
uv run python orchestator.py -site anvids_dapmodels -n 5 --delay 1
uv run python orchestator.py -n 30 --delay 0.5 --no-stop

# Batch-extract old HTML files into CSV + DB
uv run python orchestator.py --extract data/scrapes/crawl_12345

# View results in web UI
uv run python db_viewer.py
```

## Deployment

### Web UI (live)

**https://booksi.duckdns.org:8007/performers/**

Runs persistently behind nginx reverse proxy (HTTP basic auth).

### Daily cron (automatic)

```bash
# Runs every day at 4:00 AM
0 4 * * * /home/woodmastr/code/fg/dapply/update-dapply.sh >/dev/null 2>&1
```

**`update-dapply.sh`** does:
1. `uv run python orchestator.py --daily` — re-scrapes sxyprn page 0 for fresh performers
2. Ensures the web UI is alive on port 8009 (restarts if dead)

### Logs

| Log | Path |
|---|---|
| Daily scrape | `/tmp/dapply-daily.log` |
| Web UI | `/tmp/db_viewer.log` |

### Manual restart (web UI after reboot)

```bash
cd /home/woodmastr/code/fg/dapply && nohup uv run python db_viewer.py > /tmp/db_viewer.log 2>&1 &
```

### Database stats (after daily run)

```bash
cd /home/woodmastr/code/fg/dapply && uv run python3 -c "
import sqlite3
conn = sqlite3.connect('performers.db')
c = conn.cursor()
for tbl in ['performers', 'items', 'refdb_models', 'performer_features', 'performer_scenes', 'refdb_profiles']:
    c.execute(f'SELECT COUNT(*) FROM \"{tbl}\"')
    print(f'{tbl}: {c.fetchone()[0]} rows')
c.execute(\"SELECT COUNT(*) FROM items WHERE performer_id = 33\")
print(f'NO_NAME items: {c.fetchone()[0]}')
conn.close()
"
```

## 🗓️ Wrap-Up (2026-07-17) — NO_NAME Resolution Complete

### Final Database Stats

| Table | Rows |
|:------|-----:|
| **Performers** | 21,527 (was 2,223) |
| **RefDB models** | 21,268 (was 6,904) — full directory scraped |
| **Items** | 49,111 |
| **Assigned** | 44,033 (**89.7%**) |
| **NO_NAME** | **5,078 (10.3%)** — truly unsolvable |
| **Performer tags** | 21,526 (gender classified) |
| **Performer features** | 1,111 |

### Remaining NO_NAME Profile

| Category | Count | % |
|:---------|------:|--:|
| Straight (keywords present) | 2,058 | 40.5% |
| Trans content | 920 | 18.1% |
| Gay content | 186 | 3.7% |
| Lesbian content | 25 | 0.5% |
| Unknown (no gender keywords) | 1,889 | 37.2% |
| DAP content | 896 | 17.6% |
| Portuguese titles | ~1,100 | ~22% |
| Single-word/hash URL | 557 | 11.0% |

### Why They're Unsolvable

Every matching strategy was exhausted against the full 21K performer set:

1. **Exact slug match** — performer slug in item URL
2. **Substring slug match** — longest performer slug as word-boundaried substring of item slug
3. **Title contains full performer name** — exact name with word boundaries
4. **Fuzzy title match** — distinctive word from name verified standalone in title
5. **Single-word slug → performer name** — 557 items checked, 0 matches
6. **Performer name word → title word** — 9,818 name words indexed, 0 matches
7. **Female-only matching** — filtered to 21,007 female performers, +5 matches
8. **Non-straight content separated** — 1,029 gay/trans items checked vs all genders

Result: these items genuinely have **no performer name** in title or URL — amateur content, social media usernames, Portuguese descriptions, hash-based URLs from tube sites.

### What Was Accomplished

- **Full analvids directory scrape**: refdb_models 6,904 → **21,268**
- **Full performer sync**: 2,223 → **21,527**
- **~2,700 new assignments** across all matching passes
- **Performer gender tagging**: stored in `performer_tags` table (21,007 female, 381 male, 138 trans)
- **Verification layers**: STOP list (250+), descriptive-name filtering (32 excluded), word-boundary checks, prefix verification, slug cross-verify
- **Repository pattern**: `performer_repository.py` — all DB through interface
- **RefDB scraper**: `scrape_refdb_full.py` — BeautifulSoup, 36 models/page
- **Deployment**: `update-dapply.sh` (cron `0 4 * * *`), web UI on port 8009

### Future Opportunities

- **UniInfer batch classification**: `amd1.mooo.com:8123` with `ollama@qwen3.5:0.8b` — could classify remaining items by content type or attempt name extraction
- **DAP matching**: 896 DAP items could be matched if DAP performer profiles are ever built
- **Brazilian industry**: ~1,100 Portuguese items could be matched against Brazilian-specific performer databases
- **Daily maintenance**: cron already running, new items auto-processed through same pipeline

## Code Style Guidelines

### Imports
Group imports: Standard Library → Third-Party → Local.
Use explicit imports and `typing` module for hints.

```python
import os
import time
from typing import List, Optional, Dict

import requests
from bs4 import BeautifulSoup

from scraper import ScraperModule
```

### Naming Conventions
- **Classes**: `PascalCase` (e.g., `ScraperModule`, `URLGenerator`)
- **Functions/Methods**: `snake_case` (e.g., `generate_urls`, `scrape_batch`)
- **Variables**: `snake_case` (e.g., `config_file`, `retry_count`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_TIMEOUT`)
- **Private**: Prefix with underscore (e.g., `_helper_method`)

### Type Hints & Docstrings
Mandatory type hints for all signatures. Use multi-line docstrings with Args/Returns.

```python
def scrape_url(self, url: str) -> ScrapeResponse:
    """
    Scrape a single URL and save the content.

    Args:
        url: The URL to scrape

    Returns:
        ScrapeResponse object containing the result
    """
    pass
```

### Error Handling
Catch specific exceptions. Log errors appropriately. Fail gracefully.

```python
try:
    response = self.session.get(url, timeout=self.timeout)
except requests.exceptions.Timeout:
    self.logger.error(f"Timeout: {url}")
    return ScrapeResponse(..., result=ScrapeResult.RETRY)
except requests.exceptions.RequestException as e:
    self.logger.error(f"Request failed: {e}")
    return ScrapeResponse(..., result=ScrapeResult.FAILED)
```

### String Formatting
Use f-strings.
```python
url = f"https://example.com/page={page_id}"  # Good
url = "https://example.com/page={}".format(page_id)  # Avoid
```

### File Organization
```python
"""Module docstring"""

# Imports (Std, 3rd-party, Local)
import os
import requests
from scraper import ScraperModule

# Constants
TIMEOUT = 30

# Classes/Functions
class MyClass:
    pass

if __name__ == "__main__":
    main()
```

### Testing Guidelines
- Use `pytest` for unit tests.
- Tests must be independent.
- Use fixtures and `tempfile` for isolation.
- Clean up resources.

### LLM Benchmarks (dev branch only)
- **Never rawdog ad-hoc LLM tests** — always use the benchmark framework or add to it.
- `test/benchmark/llm_extract.py` — reusable parameterizable benchmark for extract+ground approach.
- `test/data/generate_golden.py` — regenerate golden sets from DB.
- Golden sets: `test/data/llm_extract_{positive,negative,mixed}.json`
- All benchmark work stays on a **dev branch**, not master.

```bash
# Quick smoke test (10 cases)
uv run python test/benchmark/llm_extract.py --quick

# Full comparison on 100 cases
uv run python test/benchmark/llm_extract.py --show 5

# Specific models with output
uv run python test/benchmark/llm_extract.py \
  --model "opencode@deepseek-v4-flash-free" \
  --model "ollama@qwen3.5:0.8b" \
  --output results.json
```

```python
import pytest
import tempfile
from scraper import ScraperModule

def test_initialization():
    with tempfile.TemporaryDirectory() as temp_dir:
        scraper = ScraperModule(output_dir=str(temp_dir))
        assert scraper.timeout == 30
```

### Database & Data
- Use parameterized queries to prevent SQL injection.
- Explicitly commit and close connections.
- Use `pandas` for heavy CSV/Data processing.
- Use `dataclasses` for structured data transfer.
- Use `Enum` for fixed states (e.g., `ScrapeResult`).

### Logging
Use Python's standard `logging`. Every module defines a module-level logger;
CLI entrypoints configure output via `logutils.setup_logging()` (streams to
stdout, so the cron's `/tmp/dapply-daily.log` capture and `2>&1` keep working).

```python
import logging
from logutils import setup_logging

logger = logging.getLogger(__name__)

# at a CLI entrypoint:
setup_logging()  # INFO by default; setup_logging(level=logging.WARNING) for quieter tools
logger.info("Operation started")
```

Do **not** use bare `print()` for runtime output — route it through `logger`.
(`setup_logging` is idempotent; library modules just define `logger` and let the
entrypoint configure the root handler.)

### Project-Specific Patterns
- **URL Templates**: Use `$variable` syntax (e.g., `https://site.com/id=$id`).
- **Status Tracking**: Maintain `url_status_tracking.txt` (`[ ]` pending, `[X]` done, `[-N]` failed).
- **Output Structure**: `data/scrapes/crawl_<timestamp>/config_name/`.
