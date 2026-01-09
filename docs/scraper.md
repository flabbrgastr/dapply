# Scraper Module

## Overview
The scraper module handles the actual HTTP requests and stores scraped content in the `data/scrapes/` directory. It supports different scraper types per URL including BeautifulSoup and w3m text rendering. The module is designed to be modular for future updates.

## Features

### Content Storage
- Saves scraped content to `data/scrapes/<crawl_session>/` directory
- Each crawl session gets its own directory with timestamp-based names
- Organizes files by domain (e.g., `data/scrapes/crawl_1234567890/com_example_net/`)
- Creates descriptive filenames based on URL path (e.g., `page_123_param_value.html`)
- For HTML content, extracts only the `<body>` section to reduce file size
- Includes metadata in saved files (source URL, timestamp, domain, crawl session)

### Scraper Types
- **Default Scraper**: Standard HTTP GET requests
- **BeautifulSoup Scraper**: Uses BeautifulSoup to extract clean text content
- **W3M Scraper**: Uses w3m text browser to render HTML as plain text
- **JS Scraper**: For JavaScript-heavy sites (placeholder for future enhancement)
- **Modular Design**: Easy to add new scraper types

### Configuration Options
- Delay between scrapes (configurable in seconds)
- Custom scraper type per URL
- Timeout and retry configurations
- Custom user agent

## Architecture

### BaseScraper Class
Abstract base class that defines the interface for all scraper types:

```python
class BaseScraper:
    def scrape(self, url: str) -> ScrapeResponse:
        raise NotImplementedError("Subclasses must implement scrape method")
```

### Available Scraper Types

#### DefaultScraper
- Makes standard HTTP GET requests
- Handles common status codes appropriately
- Implements basic retry logic for server errors

#### BeautifulSoupScraper
- Uses BeautifulSoup to parse HTML content
- Extracts clean text content while preserving structure (headings, paragraphs)
- Returns structured content with titles, headings, and paragraphs
- Reduces clutter from raw HTML markup

#### W3MScraper
- Uses system-installed w3m text browser to render HTML as plain text
- Converts HTML to human-readable text format
- Preserves formatting and structure as text
- Falls back to raw HTML if w3m is not installed or times out

#### HeadlessScraper (Placeholder)
- Designed for JavaScript-heavy sites
- Will use browser automation tools in future
- Currently falls back to standard requests

### ScraperModule
Main orchestrator class that:

- Manages HTTP sessions
- Handles content saving
- Supports different scraper types per URL
- Implements delay between requests

## Usage

### Basic Usage
```python
from scraper import ScraperModule

# Initialize the scraper module
scraper = ScraperModule(
    delay_between_requests=0.5,  # 0.5 second delay between requests
    output_dir="data/scrapes"    # Directory to store scraped content
)

# Scrape a single URL
response = scraper.scrape_url("https://example.com")

# Scrape a batch of URLs
urls = ["https://site1.com", "https://site2.com", "https://site3.com"]
results = scraper.scrape_batch(urls)
```

### Using Different Scraper Types Per URL
```python
# Define scraper types for specific URLs
url_scraper_types = {
    "https://javascript-heavy-site.com": "js",      # Use JS scraper
    "https://standard-site.com": "default",          # Use default scraper
    "https://news-site.com": "bs",                   # Use BeautifulSoup scraper
    "https://documentation.com": "w3m"              # Use w3m text scraper
}

# Scrape with custom scraper types per URL
results = scraper.scrape_batch(
    urls=["https://javascript-heavy-site.com", "https://standard-site.com", "https://news-site.com"],
    url_scraper_types=url_scraper_types
)
```

### Custom Delays
```python
# Use specific delay for this batch
results = scraper.scrape_batch(
    urls=["https://example1.com", "https://example2.com"],
    delay_override=1.0  # 1 second delay between requests
)
```

## Configuration Parameters

- `delay_between_requests`: Delay in seconds between each request (default: 0.1)
- `timeout`: Request timeout in seconds (default: 30)
- `max_retries`: Maximum retries for failed requests (default: 3)
- `user_agent`: User agent string (default: "Mozilla/5.0 (compatible; WebScraper/1.0)")
- `output_dir`: Directory for saving scraped content (default: "data/scrapes")

## ScrapeResponse Object

Each scrape operation returns a `ScrapeResponse` object with:

- `url`: The URL that was scraped
- `status_code`: HTTP status code
- `content`: The scraped content
- `headers`: Response headers
- `response_time`: Time taken for the request
- `result`: Success, failed, or retry status
- `error_message`: Error details if any
- `filename`: Path to saved file (if successful)

## File Organization

Scraped content is stored in `data/scrapes/` with the following structure:

```
data/scrapes/
├── ab/              # Subdirectory based on first 2 chars of URL hash
│   ├── abcdef1234567890abcdef1234567890.html     # Default scraper output
│   ├── abcdef1234567890abcdef1234567890_bs.html   # BeautifulSoup scraper output
│   └── abcdef1234567890abcdef1234567890_w3m.txt   # W3M scraper output
├── cd/
│   └── cdef1234567890abcdef1234567890.html
└── ...
```

Each file includes metadata:
```html
<!-- Scraped from: https://example.com/path -->
<!-- Scraper Type: default -->
<!-- Timestamp: 1234567890.123456 -->
[scraped content]
```

## Extending the Module

To add a new scraper type:

1. Create a new class inheriting from `BaseScraper`
2. Implement the `scrape` method
3. Register it in the `scraper_types` dictionary in `ScraperModule`

Example:
```python
class CustomScraper(BaseScraper):
    def scrape(self, url: str) -> ScrapeResponse:
        # Custom scraping logic
        pass

# Register in ScraperModule
self.scraper_types['custom'] = CustomScraper
```

## Crawling and Organization

### Human-Identifiable Structure
- **Crawl Sessions**: Content is organized into timestamped directories (e.g., `crawl_1234567890`)
- **Domain Organization**: Within each crawl session, content is organized by domain (`com_example_net/`)
- **File Naming**: Files use URL hashes to avoid invalid characters
- **Metadata**: Each file includes source URL, timestamp, domain, and crawl session details

### Cleanup Procedures
The scraper module provides cleanup capabilities to manage storage usage:

```python
from scraper import ScraperModule

# Initialize scraper
scraper = ScraperModule(output_dir="data/scrapes")

# Clean up old crawls, keeping only the last 5
scraper.cleanup_old_crawls(keep_last_n=5)
```