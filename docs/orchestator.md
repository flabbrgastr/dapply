# Orchestator Module

## Overview
The orchestator module coordinates the complete web scraping workflow, managing the interaction between the URL generator and the scraper module. It now supports organized storage and cleanup procedures for scraped content.

## Architecture

The orchestator implements the following workflow:

1. **URL Generation Phase**: Uses the URL generator to create a list of URLs from configuration
2. **Scraping Phase**: Hands off URLs to the scraper module for processing
3. **Status Tracking Phase**: Updates the status of each URL based on scraping results

## Components

### Orchestator Class
Main class that manages the workflow:

- `generate_urls()`: Generates the complete list of URLs from configuration
- `get_urls_to_process()`: Gets URLs that need processing (not completed)
- `start_scraping_workflow()`: Initiates the complete workflow
- `_handoff_to_scraper()`: Internal method that coordinates with the scraper
- `get_status_summary()`: Returns a summary of scraping status
- `reset_workflow()`: Resets the workflow to initial state
- `cleanup_crawls()`: Removes old crawl directories (keeping only the most recent)
- `list_crawls()`: Lists all available crawl directories

## Usage

### Command Line Interface (CLI)

The orchestator can be run directly from the command line with the following parameters:

```bash
uv run python orchestator.py [options]
```

**Options:**
- `-n`, `--limit <int>`: Limit the number of pages to process per site/URL type (default: 10).
- `-site`, `--site <name>`: Only process the specified site name from the configuration.
- `--concurrent <int>`: Maximum concurrent requests (default: 3).
- `--delay <float>`: Base delay between requests in seconds (default: 5.0). **Note:** A jitter of ±25% is automatically applied to this value (e.g., a 1.0s delay results in a random wait between 0.75s and 1.25s).
- `--extract <dir>`: Extract data from HTML files in the specified crawl directory.
- `--dbadd`: Optional flag to update the `performers.db` immediately after extraction.
- `--auto`: Combined flag to automatically trigger extraction and DB update after a scraping session.
- `--stop-on-old`: Intelligent auto-stop. Stops the scraping session early if a page contains only URLs that are already present in `extracted.csv`. (Enabled by default).
- `--no-stop`: Disable the intelligent auto-stop mechanism.
- `--reset`: Reset the workflow status (clears all completed and failed marks).
- `-h`, `--help`: Show the help message and exit.

**Examples:**
```bash
# Process only the sxyprn site, limited to 10 pages
uv run python orchestator.py -site sxyprn -n 10

# Reset status and run for all sites with a 0.5s delay
uv run python orchestator.py --reset --delay 0.5
```

### Programmatic Usage
```python
from orchestator import Orchestator

# Initialize the orchestator
orchestator = Orchestator(
    config_file='urls.yaml',
    status_file='url_status_tracking.txt',
    delay_between_requests=0.1,
    max_concurrent=5,
    output_dir="data/scrapes",               # Directory to store scraped content
    crawl_name="my_crawl_session"           # Name for this crawl session
)

# Start the complete workflow
orchestator.start_scraping_workflow(
    limit_per_url_type=10,
    site_filter="sxyprn"
)
```

## Configuration Parameters

- `config_file`: Path to the URL configuration file (default: 'urls.yaml')
- `status_file`: Path to the status tracking file (default: 'url_status_tracking.txt')
- `delay_between_requests`: Default delay between requests in seconds (default: 0.1)
- `max_concurrent`: Default maximum number of concurrent requests (default: 5)
- `output_dir`: Directory to store scraped content (default: 'data/scrapes')
- `crawl_name`: Name for the current crawl session (default: auto-generated with timestamp)

## Crawling and Storage Organization

### Structured Data Storage
- Each crawl gets its own directory: `data/scrapes/crawl_1234567890/`
- Within each crawl, content is organized by domain: `com_example_net/`
- Content includes metadata: source URL, timestamp, domain, and crawl session

### Cleanup Procedures
The orchestator manages the cleanup of old crawls:
- Automatically organizes content by crawl session
- Provides methods to list and cleanup old crawl directories
- Default behavior keeps only the most recent crawls

## Status Tracking Integration

The orchestator seamlessly integrates with the status tracking system:
- Automatically updates URL status to `[X]` when successfully processed
- Marks URLs as `[-N]` when scraping fails (with failure count)
- Respects the current status when determining which URLs to process

## Error Handling

The orchestator handles errors gracefully:
- Network errors from the scraper are converted to failed status
- Failed URLs remain in the processing queue for potential retry
- Status is preserved across application restarts