# Agent Guidelines for Dapply Project

## Build, Lint, and Test Commands

This Python project uses `uv` as the package and environment manager.

```bash
# Install dependencies
uv pip install -r requirements.txt

# Run all tests
uv run pytest

# Run specific test file
uv run pytest test/unit/test_scraper.py

# Run single test (preferred)
uv run pytest test/unit/test_scraper.py::test_scraper_initialization

# Run all unit/integration tests
uv run pytest test/unit/
uv run pytest test/integration/

# Run with coverage or verbose
uv run pytest --cov=.
uv run pytest -v

# Run the web viewer
uv run python db_viewer.py

# Run the orchestrator with default site
uv run python orchestator.py -site anvids_dapmodels -n 30 --auto --delay 0.5 --no-stop --reset
```

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
