# Agent Guidelines for Dapply Project

## Build, Lint, and Test Commands

This Python project uses `uv` as the package and environment manager.

```bash
# Install dependencies (creates .venv + uv.lock)
uv sync
uv sync --extra dev     # includes pytest

# Run tests
uv run pytest test/unit/ -v

# --- Daily update (scrape 3 fresh pages from each site) ---
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
1. `uv run python orchestator.py` — scrapes 3 fresh pages per site with auto-stop
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

## 🗓️ Current State (2026-07-17 EOD)

### Final Metrics

| Metric | Value |
|:-------|:-----:|
| **Performers** | 21,527 (was 2,223) |
| **RefDB models** | 21,268 (was 6,904 — full directory scraped) |
| **Total items** | 49,111 |
| **Assigned** | 44,033 (89.7%) |
| **NO_NAME remaining** | **5,078 (10.3%)** |
| └ Straight (no match) | 4,049 |
| └ Gay/trans (thrown away) | 1,029 |

### What was done today

1. **RefDB sync** (earlier batch of 6,904) → performers from 2,223 to 7,345
2. **Clean fuzzy matching** with verification layer → +90, filtered 32 descriptive-name performers
3. **Full directory scrape** (pages 1-659) → refdb from 6,904 to **21,268 models** (all of analvids)
4. **Sync to performers** → 21,527 total (+14,182 new)
5. **Re-run exact matching** vs full set → +998 slug, +139 title = +1,137
6. **Threw away non-straight items** (1,029 gay/trans) — separate problem
7. **Female-only matching pass** → +5 more
8. **Total new assignments today: ~2,700**

### Next Round Start Point

- **Remaining 4,049 straight NO_NAME items** are the dead end — amateur content, Portuguese titles, social media usernames. No performer name in title/slug matches any of 21K known performers.
- **1,029 gay/trans items** thrown away — could be handled separately if needed (would need male/trans performer DB)
- **`scrape_refdb_full.py`** — new script for directory scraping (don't delete, used for updates)
- **Content-type tagging** partially implemented (gender by slug) but not stored in DB yet

### Next Opportunities

- **Performer content tags**: Store `performer_tags` table with gender + DAP flags. Could use UniInfer to batch-classify performers.
- **DAP matching**: Items with "dap"/"double anal" in title (916 items). Match against performers confirmed doing DAP scenes.
- **Portuguese items**: 22% of remaining items are Portuguese (BR). Possible to match via name patterns known in Brazilian industry.
- **UniInfer proxy**: `amd1.mooo.com:8123`, key `test23@test34`, model `ollama@qwen3.5:0.8b`.

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
- Use `pytest`.
- Tests must be independent.
- Use fixtures and `tempfile` for isolation.
- Clean up resources.

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
Use Python's standard `logging`.

```python
import logging
logger = logging.getLogger(__name__)
logger.info("Operation started")
```

### Project-Specific Patterns
- **URL Templates**: Use `$variable` syntax (e.g., `https://site.com/id=$id`).
- **Status Tracking**: Maintain `url_status_tracking.txt` (`[ ]` pending, `[X]` done, `[-N]` failed).
- **Output Structure**: `data/scrapes/crawl_<timestamp>/config_name/`.
