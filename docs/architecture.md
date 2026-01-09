# Architecture Overview

## System Components

The web scraper and analytics module consists of the following main components:

### 1. URL Generator
- Reads configuration from `urls.yaml`
- Supports variable-based templating (e.g., `$inc`)
- Generates URL lists based on defined patterns
- Handles different increment types and parameters
- Maintains status tracking for each URL

### 2. Status Tracker
- Maintains status of each URL: `[ ]` (pending), `[X]` (completed), `[-N]` (failed N times)
- Persists status to `url_status_tracking.txt`
- Allows marking URLs as done or failed
- Tracks failure counts for retry logic

### 3. Orchestator Engine
- Coordinates the complete workflow between URL generation and scraping
- Manages crawl sessions with organized storage
- Supports different scraper types per URL
- Handles cleanup of old crawl directories
- Provides methods for limiting and analyzing downloads

### 4. Scraper Engine
- Processes generated URLs sequentially or in batches
- Implements respectful scraping policies
- Handles retries and error management
- Supports multiple scraper types (default, BeautifulSoup, w3m)
- Organizes content by domain and crawl session
- Extracts only body content from HTML for reduced storage size
- Includes metadata in saved files

### 5. Analytics Module
- Collects and processes scraped data
- Generates reports and insights
- Provides data visualization capabilities
- Stores processed data for analysis

## Data Flow

1. Configuration → URL Generator → URL List
2. URL List + Status Tracker → Pending URLs
3. Orchestator → Coordinate Workflow → Process URLs
4. Scraper Engine → Process URLs → Saved Content
5. Processed Data → Analytics Module → Reports

## Storage Architecture

### Organized Directory Structure
- **Crawl Sessions**: Each scrape operation creates a timestamped directory (`data/scrapes/crawl_1234567890/`)
- **Domain Organization**: Content organized by domain (`com_example_net/`) within each crawl
- **Config Grouping**: Files grouped by configuration name for easier analysis
- **Metadata Inclusion**: Each saved file includes source URL, timestamp, domain, and crawl session

### File Storage
- HTML content stored with extracted body only
- Different file extensions based on scraper type
  - `.html` for default scraper
  - `_bs.html` for BeautifulSoup scraper
  - `_w3m.txt` for w3m scraper
- Metadata embedded in file headers

## Technology Stack

- Python 3.11+
- YAML for configuration
- Plain text file storage for status tracking
- Requests for HTTP operations
- BeautifulSoup for HTML parsing
- w3m for text browser rendering
- Virtual environments managed with uv

## Scraper Types

### Default Scraper
- Standard HTTP GET requests
- Saves full HTML content

### BeautifulSoup Scraper
- Parses HTML and extracts clean text content
- Preserves document structure (headings, paragraphs)

### W3M Scraper
- Renders HTML as plain text using system w3m
- Provides clean text output

### JS Scraper (Placeholder)
- Designed for JavaScript-heavy sites
- Currently falls back to standard requests

## Key Features

### Crawl Management
- Automatic organization of scraped content by crawl session
- Configurable retention of crawl history
- Methods to limit download quantity per URL type
- Analysis-friendly storage structure

### Status Tracking
- Persistent tracking across application restarts
- Detailed failure analysis with count tracking
- Flexible status querying and filtering

### Scalability
- Configurable concurrency settings
- Adjustable delay between requests
- Modular design for extending functionality