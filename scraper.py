"""
Scraper module for the web scraper system.

This module scrapes URLs and stores the content in data/scrapes/ directory.
Supports different scraper types per URL including BeautifulSoup and w3m text rendering.
Designed to be modular for future updates.
"""

import time
import requests
import os
import hashlib
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re


class ScrapeResult(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"


@dataclass
class ScrapeResponse:
    url: str
    status_code: int
    content: Optional[str]
    headers: Dict[str, str]
    response_time: float
    result: ScrapeResult
    error_message: Optional[str] = None
    filename: Optional[str] = None  # Path to saved file
    config_name: Optional[str] = "default"  # Name of the config that generated this URL


class BaseScraper:
    """Base class for different scraper types"""

    def __init__(self, session: requests.Session, timeout: int = 30):
        self.session = session
        self.timeout = timeout

    def scrape(self, url: str) -> ScrapeResponse:
        raise NotImplementedError("Subclasses must implement scrape method")


class DefaultScraper(BaseScraper):
    """Default scraper that makes HTTP GET requests"""

    def scrape(self, url: str) -> ScrapeResponse:
        start_time = time.time()

        try:
            response = self.session.get(url, timeout=self.timeout)
            response_time = time.time() - start_time

            # Determine result based on status code
            if response.status_code == 200:
                result = ScrapeResult.SUCCESS
                error_message = None
            elif 500 <= response.status_code < 600:
                # Server error - might be temporary
                result = ScrapeResult.RETRY
                error_message = f"Server error: {response.status_code}"
            else:
                # Client error - likely permanent
                result = ScrapeResult.FAILED
                error_message = f"Client error: {response.status_code}"

            return ScrapeResponse(
                url=url,
                status_code=response.status_code,
                content=response.text,
                headers=dict(response.headers),
                response_time=response_time,
                result=result,
                error_message=error_message
            )

        except requests.exceptions.Timeout:
            response_time = time.time() - start_time
            return ScrapeResponse(
                url=url,
                status_code=0,
                content=None,
                headers={},
                response_time=response_time,
                result=ScrapeResult.RETRY,
                error_message="Request timed out"
            )

        except requests.exceptions.RequestException as e:
            response_time = time.time() - start_time
            return ScrapeResponse(
                url=url,
                status_code=0,
                content=None,
                headers={},
                response_time=response_time,
                result=ScrapeResult.FAILED,
                error_message=str(e)
            )


class BeautifulSoupScraper(BaseScraper):
    """Scraper that uses BeautifulSoup to extract clean text content"""

    def scrape(self, url: str) -> ScrapeResponse:
        start_time = time.time()

        try:
            response = self.session.get(url, timeout=self.timeout)
            response_time = time.time() - start_time

            if response.status_code == 200:
                # Parse with BeautifulSoup to clean up the content
                soup = BeautifulSoup(response.text, 'html.parser')

                # Extract text content, preserving some structure
                title = soup.find('title')
                title_text = title.get_text() if title else ""

                # Get all paragraphs
                paragraphs = soup.find_all('p')
                paragraph_texts = [p.get_text().strip() for p in paragraphs if p.get_text().strip()]

                # Get headings
                headings = []
                for i in range(1, 7):
                    headings.extend([h.get_text().strip() for h in soup.find_all(f'h{i}') if h.get_text().strip()])

                # Combine content in a structured way
                content_parts = []
                if title_text:
                    content_parts.append(f"<h1>{title_text}</h1>")

                for heading in headings:
                    content_parts.append(f"<h2>{heading}</h2>")

                for para in paragraph_texts:
                    content_parts.append(f"<p>{para}</p>")

                # Join with line breaks for readability
                cleaned_content = "\n".join(content_parts) if content_parts else soup.get_text()

                return ScrapeResponse(
                    url=url,
                    status_code=response.status_code,
                    content=cleaned_content,
                    headers=dict(response.headers),
                    response_time=response_time,
                    result=ScrapeResult.SUCCESS
                )
            else:
                return ScrapeResponse(
                    url=url,
                    status_code=response.status_code,
                    content=None,
                    headers=dict(response.headers),
                    response_time=response_time,
                    result=ScrapeResult.FAILED,
                    error_message=f"HTTP {response.status_code}"
                )

        except requests.exceptions.Timeout:
            response_time = time.time() - start_time
            return ScrapeResponse(
                url=url,
                status_code=0,
                content=None,
                headers={},
                response_time=response_time,
                result=ScrapeResult.RETRY,
                error_message="Request timed out"
            )

        except requests.exceptions.RequestException as e:
            response_time = time.time() - start_time
            return ScrapeResponse(
                url=url,
                status_code=0,
                content=None,
                headers={},
                response_time=response_time,
                result=ScrapeResult.FAILED,
                error_message=str(e)
            )

        except Exception as e:
            response_time = time.time() - start_time
            return ScrapeResponse(
                url=url,
                status_code=0,
                content=None,
                headers={},
                response_time=response_time,
                result=ScrapeResult.FAILED,
                error_message=f"BeautifulSoup parsing error: {str(e)}"
            )


class W3MScraper(BaseScraper):
    """Scraper that uses w3m text browser to render HTML as plain text"""

    def scrape(self, url: str) -> ScrapeResponse:
        start_time = time.time()

        try:
            # First, download the content using requests
            response = self.session.get(url, timeout=self.timeout)
            response_time = time.time() - start_time

            if response.status_code == 200:
                html_content = response.text

                # Try to use w3m to convert HTML to text format
                # w3m can be called via subprocess with -dump flag to output text
                try:
                    # Call w3m from the command line to convert HTML to text
                    # We'll pass the HTML content via stdin
                    result = subprocess.run(
                        ['w3m', '-T', 'text/html', '-dump'],
                        input=html_content,
                        text=True,
                        capture_output=True,
                        timeout=self.timeout
                    )

                    if result.returncode == 0:
                        # Successfully converted with w3m
                        text_content = result.stdout
                        return ScrapeResponse(
                            url=url,
                            status_code=response.status_code,
                            content=text_content,
                            headers=dict(response.headers),
                            response_time=response_time,
                            result=ScrapeResult.SUCCESS
                        )
                    else:
                        # w3m conversion failed, fall back to raw content
                        return ScrapeResponse(
                            url=url,
                            status_code=response.status_code,
                            content=html_content,  # Fallback to raw HTML if w3m fails
                            headers=dict(response.headers),
                            response_time=response_time,
                            result=ScrapeResult.SUCCESS,
                            error_message=f"w3m conversion failed: {result.stderr}"
                        )
                except FileNotFoundError:
                    # w3m not available on system, return raw content with warning
                    return ScrapeResponse(
                        url=url,
                        status_code=response.status_code,
                        content=html_content,  # Return raw HTML if w3m not available
                        headers=dict(response.headers),
                        response_time=response_time,
                        result=ScrapeResult.SUCCESS,
                        error_message="w3m not installed, returning raw HTML"
                    )
                except subprocess.TimeoutExpired:
                    # w3m took too long, return raw content
                    return ScrapeResponse(
                        url=url,
                        status_code=response.status_code,
                        content=html_content,  # Return raw HTML if w3m times out
                        headers=dict(response.headers),
                        response_time=response_time,
                        result=ScrapeResult.SUCCESS,
                        error_message="w3m conversion timed out, using raw HTML"
                    )
            else:
                return ScrapeResponse(
                    url=url,
                    status_code=response.status_code,
                    content=None,
                    headers=dict(response.headers),
                    response_time=response_time,
                    result=ScrapeResult.FAILED,
                    error_message=f"HTTP {response.status_code}"
                )

        except requests.exceptions.Timeout:
            response_time = time.time() - start_time
            return ScrapeResponse(
                url=url,
                status_code=0,
                content=None,
                headers={},
                response_time=response_time,
                result=ScrapeResult.RETRY,
                error_message="Request timed out"
            )

        except requests.exceptions.RequestException as e:
            response_time = time.time() - start_time
            return ScrapeResponse(
                url=url,
                status_code=0,
                content=None,
                headers={},
                response_time=response_time,
                result=ScrapeResult.FAILED,
                error_message=str(e)
            )


class HeadlessScraper(BaseScraper):
    """Scraper for JavaScript-heavy sites that require browser automation (placeholder for future)"""

    def scrape(self, url: str) -> ScrapeResponse:
        # This would use Selenium or Playwright in a future implementation
        start_time = time.time()

        # For now, just make a regular request
        try:
            response = self.session.get(url, timeout=self.timeout)
            response_time = time.time() - start_time

            if response.status_code == 200:
                result = ScrapeResult.SUCCESS
                error_message = None
            else:
                result = ScrapeResult.FAILED
                error_message = f"HTTP {response.status_code}"

            return ScrapeResponse(
                url=url,
                status_code=response.status_code,
                content=response.text,
                headers=dict(response.headers),
                response_time=response_time,
                result=result,
                error_message=error_message
            )

        except requests.exceptions.RequestException as e:
            response_time = time.time() - start_time
            return ScrapeResponse(
                url=url,
                status_code=0,
                content=None,
                headers={},
                response_time=response_time,
                result=ScrapeResult.FAILED,
                error_message=str(e)
            )


class ScraperModule:
    """
    Scraper module that handles the actual HTTP requests and stores scraped content.
    Supports different scraper types per URL and configurable delays.
    """

    def __init__(self,
                 delay_between_requests: float = 0.1,
                 timeout: int = 30,
                 max_retries: int = 3,
                 user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                 output_dir: str = "data/scrapes",
                 crawl_name: str = None):
        """
        Initialize the scraper module.

        Args:
            delay_between_requests: Delay between requests in seconds
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for failed requests
            user_agent: User agent string for requests
            output_dir: Directory to store scraped content
            crawl_name: Name for the current crawl session (for organization)
        """
        self.delay_between_requests = delay_between_requests
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)  # Create directory if it doesn't exist

        # Create crawl-specific directory with timestamp if no name provided
        if not crawl_name:
            crawl_name = f"crawl_{int(time.time())}"

        self.crawl_dir = self.output_dir / crawl_name
        self.crawl_dir.mkdir(parents=True, exist_ok=True)  # Create crawl directory

        # Initialize session
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': self.user_agent})

        # Register scraper types
        self.scraper_types = {
            'default': DefaultScraper,
            'bs': BeautifulSoupScraper,   # BeautifulSoup scraper for clean text extraction
            'w3m': W3MScraper,            # w3m text browser scraper
            'js': HeadlessScraper,        # For JavaScript-heavy sites (future implementation),
        }

    def _get_scraper_for_url(self, url: str, scraper_type: str = 'default') -> BaseScraper:
        """Get appropriate scraper instance for a URL"""
        if scraper_type not in self.scraper_types:
            scraper_type = 'default'  # fallback to default

        scraper_class = self.scraper_types[scraper_type]
        return scraper_class(self.session, self.timeout)

    def _save_content(self, url: str, content: str, headers: Dict[str, str], config_name: str = "default") -> str:
        """Save scraped content to file with organized structure by config name and crawl session, extracting only body"""
        from urllib.parse import unquote

        # Parse URL to extract path and create better filename
        parsed_url = urlparse(url)
        path = parsed_url.path.strip('/') or 'index'

        # Create a more descriptive filename based on URL path
        # Convert path segments to readable filename
        path_segments = path.split('/')
        sanitized_segments = []

        for segment in path_segments:
            # Sanitize segment to be safe for filenames
            sanitized = re.sub(r'[^\w\-_.]', '_', unquote(segment))
            if sanitized:  # Only add non-empty segments
                sanitized_segments.append(sanitized)

        # Join with underscores as path separators to create filename
        if sanitized_segments:
            path_filename = '_'.join(sanitized_segments)
        else:
            path_filename = 'index'

        # Add query parameters if present to make filename more specific
        if parsed_url.query:
            query_filename = re.sub(r'[^\w\-_.]', '_', unquote(parsed_url.query))
            path_filename = f"{path_filename}_{query_filename}"

        # Limit length to prevent OS issues
        max_filename_length = 100
        if len(path_filename) > max_filename_length:
            path_filename = path_filename[:max_filename_length]

        # Create config-name specific subdirectory for better organization
        config_dir = self.crawl_dir / config_name.replace(' ', '_').replace('/', '_').replace('\\', '_')
        config_dir.mkdir(exist_ok=True)

        # Determine file extension based on content type and scraper
        content_type = headers.get('Content-Type', '').lower()
        if 'text/plain' in content_type or '_w3m' in url:
            extension = '.txt'
        elif 'json' in content_type:
            extension = '.json'
        else:
            extension = '.html'

        # Create filename with URL-derived name
        filename = f"{path_filename}{extension}"
        filepath = config_dir / filename

        # Extract only the body content if it's HTML
        if extension == '.html' and '<body' in content:
            # Use BeautifulSoup to extract body content
            soup = BeautifulSoup(content, 'html.parser')
            body_tag = soup.find('body')

            if body_tag:
                # Get just the content inside the body tag
                body_content = body_tag.decode_contents()
                # Wrap just the content inside a minimal body tag
                content = f"<body>{body_content}</body>"
            else:
                # If no body tag, try to extract content between body tags if present
                body_pattern = re.compile(r'<body[^>]*>(.*?)</body>', re.DOTALL | re.IGNORECASE)
                body_match = body_pattern.search(content)
                if body_match:
                    content = f"<body>{body_match.group(1)}</body>"
                # If no body found, just keep original content

        # Prepare content with metadata
        metadata = f"<!-- Scraped from: {url} -->\n<!-- Timestamp: {time.time()} -->\n<!-- Config: {config_name} -->\n<!-- Domain: {parsed_url.netloc} -->\n<!-- Crawl Session: {self.crawl_dir.name} -->\n"
        full_content = metadata + content

        # Write content to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(full_content)

        return str(filepath.relative_to(Path('.')))

    def _infer_scraper_type_from_content(self, content: Optional[str]) -> str:
        """Infer what type of scraper was used based on content characteristics"""
        if content is None:
            return "unknown"
        if content.startswith("<?xml") or "<!DOCTYPE html" in content:
            return "default"
        elif "w3m" in content.lower() or "\t" in content:  # w3m typically preserves tabs
            return "w3m"
        elif "<h1>" in content or "<h2>" in content or "<p>" in content:
            return "bs"
        else:
            return "default"

    def scrape_url(self, url: str, scraper_type: str = 'default', config_name: str = "default") -> ScrapeResponse:
        """
        Scrape a single URL and save the content.

        Args:
            url: The URL to scrape
            scraper_type: The type of scraper to use ('default', 'bs', 'w3m', 'js', etc.)
            config_name: The configuration name that generated this URL (for organization)

        Returns:
            ScrapeResponse object containing the result
        """
        scraper = self._get_scraper_for_url(url, scraper_type)
        response = scraper.scrape(url)
        response.config_name = config_name

        # If successful, save the content
        if response.result == ScrapeResult.SUCCESS and response.content is not None:
            try:
                filename = self._save_content(response.url, response.content, response.headers, config_name)
                response.filename = filename
            except Exception as e:
                # If saving fails, mark as failed but keep original error
                original_error = response.error_message
                response.error_message = f"{original_error}; Failed to save content: {str(e)}"
                response.result = ScrapeResult.FAILED

        return response

    def scrape_batch(self,
                     urls: List[str],
                     max_concurrent: int = 5,
                     url_scraper_types: Optional[Dict[str, str]] = None,
                     url_config_names: Optional[Dict[str, str]] = None,
                     delay_override: Optional[float] = None,
                     random_delay: Optional[tuple] = None) -> List[ScrapeResponse]:
        """
        Scrape a batch of URLs with configurable settings.

        Args:
            urls: List of URLs to scrape
            max_concurrent: Maximum number of concurrent requests (not yet implemented for sequential version)
            url_scraper_types: Dictionary mapping URLs to specific scraper types
            url_config_names: Dictionary mapping URLs to configuration names for organization
            delay_override: Override for fixed delay between requests
            random_delay: Tuple of (min, max) for random delay between requests

        Returns:
            List of ScrapeResponse objects
        """
        import random
        results = []
        delay = delay_override if delay_override is not None else self.delay_between_requests
        url_scraper_types = url_scraper_types or {}
        url_config_names = url_config_names or {}

        for i, url in enumerate(urls):
            if i > 0:
                if random_delay and isinstance(random_delay, tuple) and len(random_delay) == 2:
                    # Specific range provided
                    actual_delay = random.uniform(random_delay[0], random_delay[1])
                    time.sleep(actual_delay)
                elif delay > 0:
                    # Apply +- 25% jitter to the base delay
                    jitter = delay * 0.25
                    actual_delay = random.uniform(delay - jitter, delay + jitter)
                    time.sleep(actual_delay)

            # Get scraper type and config name for this URL
            scraper_type = url_scraper_types.get(url, 'default')
            config_name = url_config_names.get(url, 'default')
            response = self.scrape_url(url, scraper_type, config_name)
            results.append(response)

        return results

    def cleanup_old_crawls(self, keep_last_n: int = 5) -> None:
        """
        Remove old crawl directories, keeping only the most recent N.

        Args:
            keep_last_n: Number of most recent crawl directories to keep
        """
        crawl_dirs = [d for d in self.output_dir.iterdir() if d.is_dir() and d.name.startswith("crawl_")]
        crawl_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        # Remove all but the most recent ones
        for old_dir in crawl_dirs[keep_last_n:]:
            try:
                import shutil
                shutil.rmtree(old_dir)
                print(f"Removed old crawl directory: {old_dir}")
            except Exception as e:
                print(f"Error removing {old_dir}: {e}")


def main():
    """
    Simple test for the scraper module.
    """
    print("Testing Scraper Module")
    print("=" * 30)

    # Test with a custom crawl name
    scraper = ScraperModule(delay_between_requests=0.1, crawl_name="test_crawl")

    # Test with a few URLs
    test_urls = [
        "https://httpbin.org/html",  # Should succeed
        "https://httpbin.org/json",  # Should succeed
        "https://httpbin.org/status/404",  # Should fail
    ]

    # Define config names for these URLs
    url_config_names = {
        test_urls[0]: "html_pages",
        test_urls[1]: "json_data",
        test_urls[2]: "status_tests"
    }

    print(f"Scraping {len(test_urls)} test URLs...")
    results = scraper.scrape_batch(test_urls, max_concurrent=2, url_config_names=url_config_names)

    for i, result in enumerate(results):
        print(f"\nResult {i+1}:")
        print(f"  URL: {result.url}")
        print(f"  Status: {result.status_code}")
        print(f"  Result: {result.result.value}")
        print(f"  Response Time: {result.response_time:.2f}s")
        print(f"  Config: {result.config_name}")
        if result.filename:
            print(f"  Saved to: {result.filename}")
        if result.error_message:
            print(f"  Error: {result.error_message}")


if __name__ == "__main__":
    main()
