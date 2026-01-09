# Video Listings Scraper Project

## Overview
This project implements a scraper for video listings from websites. The scraper extracts video metadata, URLs, and related information from various video hosting platforms.

## Key Features
- Scrapes video listings from multiple platforms
- Extracts metadata like titles, descriptions, thumbnails, and durations
- Stores data in a structured format (database/CSV)
- Handles pagination and large datasets efficiently

## Technical Stack
- Python 3.x
- [uv](https://github.com/astral-sh/uv) as the Python package manager and environment manager
- BeautifulSoup/lxml for HTML parsing
- Requests/httpx for HTTP requests
- SQLite for data storage

## Setup Instructions
1. Install uv: `pip install uv`
2. Create virtual environment: `uv venv`
3. Activate environment: `source .venv/bin/activate` (Linux/Mac) or `.venv\Scripts\activate` (Windows)
4. Install dependencies: `uv pip install -r requirements.txt`

## Project Files
- `scraper.py` - Main scraper implementation
- `orchestator.py` - Coordinates scraping tasks
- `dbadd.py` - Database operations
- `db_viewer.py` - Database inspection utility
- `extractor.py` - Data extraction logic
- `models/` - Data models and schemas
- `requirements.txt` - Python dependencies