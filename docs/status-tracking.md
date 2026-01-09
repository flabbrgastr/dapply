# Status Tracking System

## Overview
The status tracking system monitors the progress of URL scraping operations and maintains persistent state across sessions.

## Status States

There are three distinct status states for each URL:

### Pending `[ ]`
- Default state for URLs that have not been processed
- Ready to be scraped in upcoming operations
- Shown as `[ ]` in the status file

### Completed `[X]`
- State for URLs successfully processed
- Indicates successful completion of scraping operation
- Shown as `[X]` in the status file

### Failed `[-N]`
- State for URLs that failed during scraping
- N represents the number of consecutive failures
- Used for retry logic and failure analysis
- Shown as `[-N]` in the status file (displayed as `[-1]`, `[-2]`, etc.)

## Persistence

Status information is stored in `url_status_tracking.txt` in the following format:
```
[X] https://example.com/page1
[ ] https://example.com/page2
[-2] https://example.com/page3
```

## Programmatic Interface

### Marking URLs as Done
```python
from url_generator import URLGenerator

generator = URLGenerator()
generator.mark_url_done(url)
```

### Marking URLs as Failed
```python
generator.mark_url_failed(url)
```

### Checking URL Status
```python
# Check if URL is completed
is_complete = generator.is_url_done(url)

# Check if URL has failed
is_failed = generator.is_url_failed(url)

# Get failure count
failure_count = generator.get_failure_count(url)
```

### Retrieving URLs by Status
```python
# All URLs that need processing (not completed)
todo_urls = generator.get_todo_urls()

# Only URLs that have never been attempted
pending_urls = generator.get_pending_urls()
```

### Reset Status (for testing)
```python
generator.reset_status()
```

## Failure Handling

The system implements intelligent failure handling:

1. **Failure Counting**: Each failure increments the counter
2. **Retry Logic**: Failed URLs remain in the processing queue
3. **Error Analysis**: High failure counts indicate problematic URLs
4. **Progress Tracking**: Distinguishes between pending and failed states