"""
Specialized scraper for AnalVids DAP Models pages.

This module scrapes model profile pages from AnalVids, focusing on performers in the
double anal niche. It extracts model information and links to their videos.

URL pattern: https://www.analvids.com/models/niche/double_anal/page/$inc/
"""

import csv
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


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
    extracted_data: Optional[Dict] = None  # Special field for extracted model data


class BaseModelScraper:
    """Base class for different scraper types"""

    def __init__(self, session: requests.Session, timeout: int = 30):
        self.session = session
        self.timeout = timeout

    def scrape(self, url: str) -> ScrapeResponse:
        raise NotImplementedError("Subclasses must implement scrape method")


class AnvidsModelsScraper(BaseModelScraper):
    """Specialized scraper for AnalVids models pages that extracts model information"""

    def scrape(self, url: str) -> ScrapeResponse:
        start_time = time.time()

        try:
            response = self.session.get(url, timeout=self.timeout)
            response_time = time.time() - start_time

            if response.status_code == 200:
                # Parse with BeautifulSoup to extract model information
                soup = BeautifulSoup(response.text, "html.parser")

                # Extract model data
                models_data = self._extract_models_data(soup, url)

                # Format content as structured data plus readable text
                content = self._format_content(soup, models_data)

                return ScrapeResponse(
                    url=url,
                    status_code=response.status_code,
                    content=content,
                    headers=dict(response.headers),
                    response_time=response_time,
                    result=ScrapeResult.SUCCESS,
                    extracted_data=models_data,
                )
            else:
                return ScrapeResponse(
                    url=url,
                    status_code=response.status_code,
                    content=None,
                    headers=dict(response.headers),
                    response_time=response_time,
                    result=ScrapeResult.FAILED,
                    error_message=f"HTTP {response.status_code}",
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
                error_message="Request timed out",
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
                error_message=str(e),
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
                error_message=f"Parsing error: {str(e)}",
            )

    def _extract_models_data(
        self, soup: BeautifulSoup, base_url: str
    ) -> Dict[str, Any]:
        """Extract model information from the page"""
        models = []

        # Find all model profile containers
        model_containers = (
            soup.find_all("div", class_="model-item")
            or soup.find_all("div", class_=re.compile(r".*model.*", re.I))
            or soup.find_all("a", class_=re.compile(r".*model.*", re.I))
        )

        # If no model-items found, try generic approaches
        if not model_containers:
            model_containers = (
                soup.find_all("div", attrs={"data-model-id": True})
                or soup.find_all("article", class_=re.compile(r".*model.*", re.I))
                or soup.find_all("figure", class_=re.compile(r".*model.*", re.I))
            )

        # More flexible approach - look for links with model-related paths
        if not model_containers:
            # Look for links that seem to be to model profiles
            all_links = soup.find_all(
                "a", href=re.compile(r"/model|/models|/performer|/performers", re.I)
            )

            # Filter for those in sections that look like listings
            container_parent = soup.find(
                class_=re.compile(r".*(grid|list|browse|gallery).*", re.I)
            )
            if container_parent:
                all_links = container_parent.find_all(
                    "a", href=re.compile(r"/model|/models|/performer|/performers", re.I)
                )

            # Process unique links only
            processed_hrefs = set()
            for link in all_links:
                href = link.get("href")
                if href and href not in processed_hrefs:
                    processed_hrefs.add(href)

                    # Check if this looks like a model profile link
                    full_url = urljoin(base_url, href)
                    if re.search(
                        r"/model|/models|/performer|/performers", full_url, re.I
                    ):
                        img_tag = link.find("img")
                        img_src = img_tag.get("src") if img_tag else None
                        if img_src:
                            img_src = urljoin(base_url, img_src)

                        model_info = {
                            "name": link.get_text(strip=True) or "Unknown",
                            "profile_url": full_url,
                            "thumbnail": img_src,
                            "page_source": "link_based_extraction",
                        }
                        models.append(model_info)

        # If the above approach worked well, return the data
        if models:
            return {
                "models_count": len(models),
                "models": models,
                "base_url": base_url,
                "extraction_method": "link_based",
            }

        # Traditional approach - try to find models in the containers
        for container in model_containers[:50]:  # Limit to prevent excessive processing
            try:
                # Look for the model link first to get profile URL
                profile_link = container.find(
                    "a", href=re.compile(r"/model|/models|/performer", re.I)
                )
                if not profile_link:
                    continue

                profile_url = urljoin(base_url, profile_link.get("href"))
                model_name = profile_link.get_text(strip=True)

                # If name is empty, try to get it differently
                if not model_name:
                    name_tag = container.find(
                        ["span", "div", "h3", "h4"],
                        class_=re.compile(r".*(name|title|model).*", re.I),
                    )
                    model_name = (
                        name_tag.get_text(strip=True) if name_tag else "Unknown"
                    )

                # Find thumbnail
                img_tag = container.find("img")
                thumbnail_url = None
                if img_tag:
                    thumbnail_url = img_tag.get("src") or img_tag.get("data-src")
                    if thumbnail_url:
                        thumbnail_url = urljoin(base_url, thumbnail_url)

                # Count videos if available
                video_count_elem = container.find(
                    class_=re.compile(r".*(video|count|film).*", re.I)
                )
                video_count = 0
                if video_count_elem:
                    count_text = video_count_elem.get_text()
                    count_matches = re.findall(r"\d+", count_text)
                    if count_matches:
                        video_count = int(count_matches[0])

                model_info = {
                    "name": model_name,
                    "profile_url": profile_url,
                    "thumbnail": thumbnail_url,
                    "video_count": video_count,
                    "container_html_class": str(container.get("class", [])),
                    "page_source": "container_based_extraction",
                }

                models.append(model_info)
            except Exception as e:
                continue  # Skip problematic containers

        return {
            "models_count": len(models),
            "models": models,
            "base_url": base_url,
            "extraction_method": "container_based" if models else "none_found",
        }

    def _format_content(self, soup: BeautifulSoup, models_data: Dict) -> str:
        """Format scraped content for storage"""
        title = soup.find("title")
        title_text = title.get_text() if title else "AnalVids Models Page"

        # Create structured content
        content_parts = [
            f"<h1>{title_text}</h1>",
            f"<p>Total models found: {models_data.get('models_count', 0)}</p>",
            "<h2>Models Data:</h2>",
        ]

        for model in models_data.get("models", [])[:20]:  # Show first 20 models
            content_parts.append(f"<h3>{model.get('name', 'Unknown')}</h3>")
            content_parts.append(f"<p>Profile: {model.get('profile_url', '')}</p>")
            content_parts.append(f"<p>Videos: {model.get('video_count', 'N/A')}</p>")
            content_parts.append("<hr>")

        # Add original page content as fallback
        content_parts.append("<h2>Original Page Content:</h2>")
        content_parts.append(str(soup.body or soup))

        return "\n".join(content_parts)


class AnvidsDapModelsScraperModule:
    """
    Specialized scraper module for AnalVids DAP Models pages.
    Handles scraping and saving model data from multiple pages.
    """

    def __init__(
        self,
        delay_between_requests: float = 1.0,  # Slightly higher delay for respectful scraping
        timeout: int = 30,
        max_retries: int = 3,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        output_dir: str = "data/anvids_dapmodels",
        crawl_name: str = None,
    ):
        """
        Initialize the Anvids DAP Models scraper module.

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
        self.output_dir.mkdir(
            parents=True, exist_ok=True
        )  # Create directory if it doesn't exist

        # Create crawl-specific directory with timestamp if no name provided
        if not crawl_name:
            crawl_name = f"dapmodels_crawl_{int(time.time())}"

        self.crawl_dir = self.output_dir / crawl_name
        self.crawl_dir.mkdir(parents=True, exist_ok=True)  # Create crawl directory

        # Initialize session
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            }
        )

    def _save_content(
        self,
        url: str,
        content: str,
        headers: Dict[str, str],
        extracted_data: Optional[Dict] = None,
        config_name: str = "dapmodels",
    ) -> str:
        """Save scraped content to file with organized structure, and save extracted data separately."""
        from urllib.parse import unquote

        # Parse URL to extract path and create better filename
        parsed_url = urlparse(url)
        path = parsed_url.path.strip("/") or "index"

        # Create a more descriptive filename based on URL path
        path_segments = path.split("/")
        sanitized_segments = []

        for segment in path_segments:
            # Sanitize segment to be safe for filenames
            sanitized = re.sub(r"[^\w\-_.]", "_", unquote(segment))
            if sanitized:  # Only add non-empty segments
                sanitized_segments.append(sanitized)

        # Join with underscores as path separators to create filename
        if sanitized_segments:
            path_filename = "_".join(sanitized_segments)
        else:
            path_filename = "index"

        # Add query parameters if present to make filename more specific
        if parsed_url.query:
            query_filename = re.sub(r"[^\w\-_.]", "_", unquote(parsed_url.query))
            path_filename = f"{path_filename}_{query_filename}"

        # Limit length to prevent OS issues
        max_filename_length = 100
        if len(path_filename) > max_filename_length:
            path_filename = path_filename[:max_filename_length]

        # Create config-name specific subdirectory for better organization
        config_dir = self.crawl_dir / config_name.replace(" ", "_").replace(
            "/", "_"
        ).replace("\\", "_")
        config_dir.mkdir(exist_ok=True)

        # Save main HTML content
        html_filepath = config_dir / f"{path_filename}.html"

        # Prepare content with metadata
        metadata = f"<!-- Scraped from: {url} -->\n<!-- Timestamp: {time.time()} -->\n<!-- Config: {config_name} -->\n<!-- Domain: {parsed_url.netloc} -->\n<!-- Crawl Session: {self.crawl_dir.name} -->\n"
        full_content = metadata + content

        # Write HTML content to file
        with open(html_filepath, "w", encoding="utf-8") as f:
            f.write(full_content)

        # If we have extracted data, save it separately as JSON
        if extracted_data:
            json_filepath = config_dir / f"{path_filename}_extracted.json"
            with open(json_filepath, "w", encoding="utf-8") as f:
                json.dump(extracted_data, f, indent=2, ensure_ascii=False)

            # Also save as CSV if there are models
            models = extracted_data.get("models", [])
            if models:
                csv_filepath = config_dir / f"{path_filename}_models.csv"
                with open(csv_filepath, "w", newline="", encoding="utf-8") as f:
                    if models:
                        writer = csv.DictWriter(f, fieldnames=models[0].keys())
                        writer.writeheader()
                        for model in models:
                            writer.writerow({k: v for k, v in model.items()})

        return str(html_filepath.relative_to(Path(".")))

    def scrape_page(self, url: str, config_name: str = "dapmodels") -> ScrapeResponse:
        """
        Scrape a single page from AnalVids models section and extract model information.

        Args:
            url: The URL to scrape (should be a models page)
            config_name: The configuration name (for organization, defaults to dapmodels)

        Returns:
            ScrapeResponse object containing the result and extracted data
        """
        scraper = AnvidsModelsScraper(self.session, self.timeout)
        response = scraper.scrape(url)
        response.config_name = config_name

        # If successful, save the content
        if response.result == ScrapeResult.SUCCESS:
            try:
                filename = self._save_content(
                    response.url,
                    response.content,
                    response.headers,
                    response.extracted_data,
                    config_name,
                )
                response.filename = filename
            except Exception as e:
                # If saving fails, mark as failed but keep original error
                original_error = response.error_message
                response.error_message = (
                    f"{original_error}; Failed to save content: {str(e)}"
                )
                response.result = ScrapeResult.FAILED

        return response

    def scrape_multiple_pages(
        self, urls: List[str], config_name: str = "dapmodels"
    ) -> List[ScrapeResponse]:
        """
        Scrape multiple pages with appropriate delays.

        Args:
            urls: List of model listing URLs to scrape
            config_name: The configuration name (for organization)

        Returns:
            List of ScrapeResponse objects
        """
        import random

        results = []

        for i, url in enumerate(urls):
            if i > 0:
                # Apply delay with some randomness to be respectful to the server
                jitter = self.delay_between_requests * 0.25
                actual_delay = random.uniform(
                    self.delay_between_requests - jitter,
                    self.delay_between_requests + jitter,
                )
                time.sleep(actual_delay)

            response = self.scrape_page(url, config_name)
            results.append(response)

        return results

    def aggregate_all_models(self, config_name: str = "dapmodels") -> List[Dict]:
        """
        Aggregate all models from all scraped pages and return a unified list.

        Args:
            config_name: The configuration name to look for

        Returns:
            List of all models found across all pages
        """
        all_models = []
        config_dir = self.crawl_dir / config_name.replace(" ", "_").replace(
            "/", "_"
        ).replace("\\", "_")

        if not config_dir.exists():
            return all_models

        # Look for all JSON files with extracted data
        json_files = list(config_dir.glob("*_extracted.json"))

        for json_file in json_files:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    models = data.get("models", [])
                    all_models.extend(models)
            except Exception as e:
                print(f"Error reading {json_file}: {e}")

        return all_models

    def save_aggregated_models(self, config_name: str = "dapmodels") -> str:
        """
        Save aggregated models to a single CSV and JSON file.

        Args:
            config_name: The configuration name to look for

        Returns:
            Path to the saved CSV file
        """
        all_models = self.aggregate_all_models(config_name)

        if not all_models:
            print("No models found to aggregate.")
            return ""

        # Create a file with timestamp
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        csv_filename = self.crawl_dir / f"all_dapmodels_{timestamp}.csv"
        json_filename = self.crawl_dir / f"all_dapmodels_{timestamp}.json"

        # Save to CSV
        with open(csv_filename, "w", newline="", encoding="utf-8") as f:
            if all_models:
                writer = csv.DictWriter(f, fieldnames=all_models[0].keys())
                writer.writeheader()
                for model in all_models:
                    writer.writerow({k: v for k, v in model.items()})

        # Save to JSON
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(all_models, f, indent=2, ensure_ascii=False)

        print(f"Saved aggregated models: {len(all_models)} total models")
        print(f"CSV: {csv_filename}")
        print(f"JSON: {json_filename}")

        return str(csv_filename)


