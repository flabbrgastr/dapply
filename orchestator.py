"""
Orchestator module for the web scraper system.

This module coordinates the workflow between URL generation, scraping,
and status tracking components.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from scraper import ScraperModule
from url_generator import URLGenerator
from dbadd import add_performers_from_items


class Orchestator:
    """
    Main orchestator that coordinates the scraping workflow.

    The orchestator manages the complete lifecycle:
    1. URL generation using configuration
    2. Handoff to scraper module
    3. Status tracking and monitoring
    """

    def __init__(
        self,
        config_file: str = "urls.yaml",
        status_file: str = "url_status_tracking.txt",
        delay_between_requests: float = 5.0,
        max_concurrent: int = 5,
        output_dir: str = "data/scrapes",
        crawl_name: str = None,
    ):
        """
        Initialize the orchestator.

        Args:
            config_file: Path to the URL configuration file
            status_file: Path to the status tracking file
            delay_between_requests: Default delay between requests
            max_concurrent: Default maximum number of concurrent requests
            output_dir: Directory to store scraped content
            crawl_name: Name for the current crawl session (for organization)
        """
        self.config_file = config_file
        self.status_file = status_file
        self.delay_between_requests = delay_between_requests
        self.max_concurrent = max_concurrent
        self.output_dir = output_dir
        if not crawl_name:
            crawl_name = f"crawl_{int(time.time())}"
        self.crawl_name = crawl_name

        self.url_generator = URLGenerator(config_file=config_file)
        self.url_generator.status_file = status_file

        # Set up logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def generate_urls(self) -> List[str]:
        """
        Step 1: Generate the complete list of URLs from configuration.

        Returns:
            List of URLs to be processed
        """
        self.logger.info("Starting URL generation phase...")

        urls = self.url_generator.generate_all_urls()
        self.logger.info(f"Generated {len(urls)} URLs for processing")

        # Initialize all URLs with pending status if not already tracked
        for url in urls:
            if not self.url_generator.is_url_done(
                url
            ) and not self.url_generator.is_url_failed(url):
                # Status file already has [ ] for pending URLs when calling reset_status()
                pass

        self.logger.info("URL generation phase completed")
        return urls

    def get_urls_to_process(
        self, limit_per_type: Optional[int] = None, site_filter: Optional[str] = None
    ) -> List[str]:
        """
        Get the list of URLs to scrape.

        When limit_per_type is set: generates fresh URLs from config, ignores status
        (so repeated runs always scrape the requested pages).

        When limit_per_type is None: uses status tracking to resume where left off.

        Args:
            limit_per_type: Max pages per site. When set, ignores done/failed status.
            site_filter: Only return URLs from the specified site/config name

        Returns:
            List of URLs to scrape
        """
        # When limit is specified: ignore status, generate fresh URLs
        if limit_per_type is not None:
            all_urls = self.url_generator.generate_all_urls()

            if site_filter:
                url_config_names = self._get_url_config_names(all_urls)
                all_urls = [
                    url for url in all_urls
                    if url_config_names.get(url) == site_filter
                ]

            urls_by_type = self._group_urls_by_type(all_urls)
            result = []
            for url_type, urls in urls_by_type.items():
                result.extend(urls[:limit_per_type])
            return result

        # No limit: use status tracking for resume
        all_todo_urls = self.url_generator.get_todo_urls()

        if site_filter:
            url_config_names = self._get_url_config_names(all_todo_urls)
            all_todo_urls = [
                url for url in all_todo_urls
                if url_config_names.get(url) == site_filter
            ]

        return all_todo_urls

    def download_n_of_each_type(self, n: int = 3) -> None:
        """
        Download N pages of each URL type without cleaning up old crawls.

        Args:
            n: Number of pages to download per URL type (default 3)
        """
        # Run the crawl with n pages per type without cleanup
        self.logger.info(
            f"Downloading {n} pages of each URL type (no cleanup will be performed)..."
        )
        self.start_scraping_workflow(limit_per_url_type=n)

        self.logger.info(
            f"Downloaded {n} pages of each URL type. Crawls preserved for analysis."
        )

    def cleanup_and_download_n_of_each_type(
        self, n: int = 3, keep_crawls: int = 5
    ) -> None:
        """
        Clean up old crawls and download N pages of each URL type.

        Args:
            n: Number of pages to download per URL type (default 3)
            keep_crawls: Number of most recent crawl directories to keep (default 5)
        """
        # First, clean up old crawls
        self.cleanup_crawls(keep_last_n=keep_crawls)

        # Then run the crawl with n pages per type
        self.logger.info(
            f"Cleaning up old crawls and downloading {n} pages of each URL type..."
        )
        self.start_scraping_workflow(limit_per_url_type=n)

        self.logger.info(
            f"Downloaded {n} pages of each URL type, keeping last {keep_crawls} crawls."
        )

    def _group_urls_by_type(self, urls: List[str]) -> Dict[str, List[str]]:
        """
        Group URLs by their type based on the original configuration.
        This looks at the configuration to determine which URLs came from the same template.

        Args:
            urls: List of URLs to group

        Returns:
            Dictionary mapping URL type patterns to lists of URLs
        """
        # Load config to understand which URLs came from which template
        all_generated_urls_with_config = {}

        for url_config in self.url_generator.config["urls"]:
            generated_urls = self.url_generator.generate_urls_for_config(url_config)
            config_name = url_config["name"]
            for url in generated_urls:
                all_generated_urls_with_config[url] = config_name

        groups = {}

        for url in urls:
            # Find which config this URL came from
            config_name = all_generated_urls_with_config.get(url, "unknown")

            if config_name not in groups:
                groups[config_name] = []
            groups[config_name].append(url)

        return groups

    def start_scraping_workflow(
        self,
        max_concurrent: Optional[int] = None,
        delay_between_requests: Optional[float] = None,
        limit_per_url_type: Optional[int] = None,
        site_filter: Optional[str] = None,
        random_delay_range: Optional[tuple] = None,
        stop_on_no_new: bool = False,
    ):
        """
        Start the complete scraping workflow.

        This method orchestrates the complete workflow:
        1. Generate URLs
        2. Hand off to scraper module
        3. Handle results and update status

        Args:
            max_concurrent: Maximum number of concurrent scraping operations
            delay_between_requests: Delay between requests in seconds
            limit_per_url_type: Maximum number of URLs to process per URL type (None for no limit)
            site_filter: Only process URLs from the specified site/config name
            random_delay_range: Tuple of (min, max) for random delay between requests
            stop_on_no_new: If True, stop scraping a site when a page yields no new URLs (based on extracted.csv)
        """
        max_concurrent = max_concurrent or self.max_concurrent
        delay_between_requests = delay_between_requests or self.delay_between_requests

        self.logger.info("Starting scraping workflow...")

        # Step 1: Generate URLs
        all_urls = self.generate_urls()

        # Step 2: Get URLs to process (with limit per type if specified)
        urls_to_process = self.get_urls_to_process(
            limit_per_type=limit_per_url_type, site_filter=site_filter
        )

        self.logger.info(
            f"Found {len(urls_to_process)} URLs to process out of {len(all_urls)} total"
        )
        if limit_per_url_type is not None:
            self.logger.info(f"Limit: maximum {limit_per_url_type} per URL type")

        if not urls_to_process:
            self.logger.info("No URLs to process. Workflow completed.")
            return

        # Step 3: Hand off to scraper module (with optional auto-stop logic)
        self._handoff_to_scraper(
            urls_to_process,
            max_concurrent,
            delay_between_requests,
            limit_per_url_type=limit_per_url_type,
            random_delay_range=random_delay_range,
            stop_on_no_new=stop_on_no_new,
        )

        self.logger.info("Scraping workflow completed")

    def _filter_novel_items(self, items: List[Dict], session_known_urls: Set[str]) -> Tuple[List[Dict], List[Dict]]:
        """
        Filter out items that are already known, checking ad-hoc against extracted.csv.
        
        Args:
            items: List of items extracted from a page
            session_known_urls: Set of URLs found in the current scraping session
            
        Returns:
            Tuple of (novel_items, all_items)
        """
        if not items:
            return [], []

        # 1. First check against the current session's known URLs
        potentially_new = [
            item for item in items if item["item_url"] not in session_known_urls
        ]
        
        if not potentially_new:
            return [], items

        # 2. Check ad-hoc against extracted.csv using pandas chunks
        if os.path.exists("extracted.csv"):
            try:
                import pandas as pd
                
                # Get the list of URLs we are looking for
                urls_to_check = {item["item_url"] for item in potentially_new}
                known_in_csv = set()
                
                # Read in chunks to be memory efficient
                chunk_size = 50000
                for chunk in pd.read_csv(
                    "extracted.csv",
                    usecols=["item_url"],
                    dtype={"item_url": "str"},
                    chunksize=chunk_size,
                ):
                    # Check which of our urls_to_check are in this chunk
                    found = set(chunk[chunk["item_url"].isin(urls_to_check)]["item_url"])
                    known_in_csv.update(found)
                    
                    # Remove found URLs from our check set to speed up next chunks
                    urls_to_check -= found
                    
                    # If we've found all of them, we can stop reading the file
                    if not urls_to_check:
                        break
                
                # Filter out those found in CSV
                novel_items = [
                    item for item in potentially_new if item["item_url"] not in known_in_csv
                ]
                return novel_items, items
                
            except Exception as e:
                self.logger.warning(f"Ad-hoc novelty check failed: {e}")
                # Fallback: assume all potentially_new are novel if check fails
                return potentially_new, items
        
        # If file doesn't exist, all potentially_new are novel
        return potentially_new, items

    def _append_items_to_csv(self, items: List[Dict], csv_path: str = "extracted.csv") -> None:
        """
        Append new items to the extracted CSV file.

        Args:
            items: List of item dictionaries to persist
            csv_path: Path to the extracted CSV file
        """
        if not items:
            return

        import csv

        fieldnames = [
            "item_url",
            "title",
            "performers",
            "item_date",
            "hits",
            "last_updated",
            "crawls",
            "source_file",
        ]

        csv_file = Path(csv_path)
        file_exists = csv_file.exists()

        with csv_file.open("a" if file_exists else "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()

            for item in items:
                row = {key: item.get(key, "") for key in fieldnames}
                writer.writerow(row)

    def _handoff_to_scraper(
        self,
        urls: List[str],
        max_concurrent: int,
        delay: float,
        limit_per_url_type: Optional[int] = None,
        random_delay_range: Optional[tuple] = None,
        stop_on_no_new: bool = False,
    ):
        """
        Handoff URLs to the scraper module.

        Args:
            urls: List of URLs to be scraped
            max_concurrent: Maximum number of concurrent operations
            delay: Delay between requests
            random_delay_range: Tuple of (min, max) for random delay
            stop_on_no_new: Whether to stop if no new items are found
        """
        self.logger.info(f"Handing off {len(urls)} URLs to scraper module...")

        # Initialize the scraper module
        scraper = ScraperModule(
            delay_between_requests=delay,
            max_retries=3,
            output_dir=self.output_dir,
            crawl_name=self.crawl_name,
        )

        # Map URLs to their configuration names
        url_config_names = self._get_url_config_names(urls)

        # Process URLs
        from extractor import extract_from_file
        from scraper import ScrapeResult

        # Group URLs by site/config name for round-robin processing
        urls_by_site: Dict[str, List[str]] = {}
        for url in urls:
            site = url_config_names.get(url, "default")
            if site not in urls_by_site:
                urls_by_site[site] = []
            urls_by_site[site].append(url)

        # Track URLs found per site in the current session
        session_known_by_site: Dict[str, Set[str]] = {
            site: set() for site in urls_by_site
        }

        # Per-site indices and active site list for round-robin
        site_indices: Dict[str, int] = {site: 0 for site in urls_by_site}
        active_sites: List[str] = [
            site for site, site_urls in urls_by_site.items() if site_urls
        ]

        # Global step counter to control when to apply random delay
        step = 0

        while active_sites:
            for site in list(active_sites):
                site_urls = urls_by_site[site]
                index = site_indices[site]

                if index >= len(site_urls):
                    active_sites.remove(site)
                    continue

                url = site_urls[index]
                site_indices[site] = index + 1

                self.logger.info(f"Crawling {url}...")
                response = scraper.scrape_batch(
                    [url],
                    max_concurrent=1,
                    url_config_names={url: site},
                    random_delay=None if step == 0 else random_delay_range,
                )[0]

                step += 1

                if response.result == ScrapeResult.SUCCESS and response.filename:
                    self.logger.info(f"Indexing {url}...")
                    items = extract_from_file(response.filename)

                    new_items, all_items = self._filter_novel_items(
                        items, session_known_by_site[site]
                    )
                    novelty_count = len(new_items)
                    self.logger.info(f"  -> {novelty_count} new items found")

                    if new_items:
                        self._append_items_to_csv(new_items)
                        # Also add to the database immediately
                        try:
                            add_performers_from_items(new_items)
                        except Exception as e:
                            self.logger.error(f"Failed to add performers to DB: {e}")

                    if site == "anvids_dapmodels" and new_items:
                        performer_names = []
                        for item in new_items:
                            performers_str = item.get("performers") or ""
                            if performers_str and performers_str != "NO_NAME":
                                for name in performers_str.split(";"):
                                    name = name.strip()
                                    if name:
                                        performer_names.append(name)
                            elif item.get("title", "").startswith("Model: "):
                                name = item["title"].replace("Model:", "").strip()
                                if name:
                                    performer_names.append(name)

                        unique_names = sorted({name for name in performer_names})
                        if unique_names:
                            max_to_show = 10
                            shown = unique_names[:max_to_show]
                            self.logger.info(
                                "    New performers: " + ", ".join(shown)
                            )
                            remaining = len(unique_names) - len(shown)
                            if remaining > 0:
                                self.logger.info(
                                    f"    (+{remaining} more performers)"
                                )

                    # Mark as done with X<count> tag
                    self._process_scrape_response(response, tag=f"X{novelty_count}")

                    if stop_on_no_new and novelty_count == 0:
                        if all_items:
                            self.logger.info(
                                f"--- NOVELTY ALERT: No new content found for site '{site}'. Stopping this site early. ---"
                            )
                        else:
                            self.logger.info(
                                f"--- EMPTY PAGE ALERT: No items found on page for site '{site}'. Stopping this site early. ---"
                            )

                        # Mark only the very next URL for this site as AUTOEXIT to show where we stopped
                        next_index = site_indices[site]
                        if next_index < len(site_urls):
                            self.url_generator.mark_url_done(
                                site_urls[next_index], tag="AUTOEXIT"
                            )

                        # Remove this site from further round-robin processing
                        active_sites.remove(site)
                    elif all_items:
                        # Update session_known_urls for this site for the next pages of the same site
                        for item in new_items:
                            session_known_by_site[site].add(item["item_url"])
                else:
                    self._process_scrape_response(response)

    def _process_scrape_response(self, response, tag="X"):
        """Process a single scrape response and update status."""
        url = response.url
        if response.result.value == "success":
            self.url_generator.mark_url_done(url, tag=tag)
        elif response.result.value == "failed":
            self.url_generator.mark_url_failed(url)
            self.logger.info(f"  ✗ Failed to process: {url} - {response.error_message}")
        elif response.result.value == "retry":
            self.url_generator.mark_url_failed(url)
            self.logger.info(f"  ⚀ Need to retry: {url} - {response.error_message}")

    def process_single_url(self, url: str, **kwargs):
        """
        Process a single specific URL to test duplication detection.

        Args:
            url: The specific URL to process
        """
        from extractor import extract_from_file
        from scraper import ScrapeResult, ScraperModule

        self.logger.info(f"Processing single URL: {url}")

        # Initialize the scraper module
        scraper = ScraperModule(
            delay_between_requests=kwargs.get(
                "delay_between_requests", self.delay_between_requests
            ),
            max_retries=kwargs.get("max_retries", 3),
            output_dir=self.output_dir,
            crawl_name=self.crawl_name,
        )

        # Determine configuration name for this URL
        url_config_names = self._get_url_config_names([url])
        config_name = url_config_names.get(url, "default")

        # Scrape the single URL
        response = scraper.scrape_batch(
            [url],
            max_concurrent=1,
            url_config_names={url: config_name},
            random_delay=kwargs.get("random_delay_range", None),
        )[0]

        # Process the response
        self._process_scrape_response(response)

        if response.result == ScrapeResult.SUCCESS and response.filename:
            self.logger.info(f"Indexing {url}...")
            items = extract_from_file(response.filename)
            
            # Ad-hoc novelty check
            new_items, all_items = self._filter_novel_items(items, set())
            novelty_count = len(new_items)
            self.logger.info(
                f"  -> {novelty_count} new items found out of {len(items)} total items"
            )

            # Update status with novelty count
            self._process_scrape_response(response, tag=f"X{novelty_count}")

            return novelty_count, len(items), new_items
        else:
            return 0, 0, []

    def _get_url_config_names(self, urls: List[str]) -> Dict[str, str]:
        """
        Get the configuration name for each URL to enable proper directory organization.

        Args:
            urls: List of URLs to map to configuration names

        Returns:
            Dictionary mapping URLs to their configuration names
        """
        # Load config to understand which URLs came from which template
        url_config_mapping = {}

        for url_config in self.url_generator.config["urls"]:
            generated_urls = self.url_generator.generate_urls_for_config(url_config)
            config_name = url_config["name"]
            for url in generated_urls:
                url_config_mapping[url] = config_name

        # Map the URLs being processed to their config names
        result = {}
        for url in urls:
            config_name = url_config_mapping.get(url, "default")
            result[url] = config_name

        return result

    def get_status_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the current scraping status.

        Returns:
            Dictionary with status counts and progress
        """
        all_urls = self.url_generator.generate_all_urls()
        total_count = len(all_urls)
        completed_count = len(
            [url for url in all_urls if self.url_generator.is_url_done(url)]
        )
        failed_count = len(
            [url for url in all_urls if self.url_generator.is_url_failed(url)]
        )
        pending_count = len(
            [
                url
                for url in all_urls
                if not self.url_generator.is_url_done(url)
                and not self.url_generator.is_url_failed(url)
            ]
        )

        return {
            "total": total_count,
            "completed": completed_count,
            "failed": failed_count,
            "pending": pending_count,
            "progress_percent": (completed_count / total_count * 100)
            if total_count > 0
            else 0,
        }

    def reset_workflow(self):
        """
        Reset the entire workflow to initial state.
        """
        self.logger.info("Resetting workflow...")
        self.url_generator.reset_status()

    def cleanup_crawls(self, keep_last_n: int = 5) -> None:
        """
        Remove old crawl directories, keeping only the most recent N.

        Args:
            keep_last_n: Number of most recent crawl directories to keep
        """
        from scraper import ScraperModule

        # Create a temporary scraper instance to perform cleanup
        temp_scraper = ScraperModule(output_dir=self.output_dir)
        temp_scraper.cleanup_old_crawls(keep_last_n)
        self.logger.info(
            f"Cleanup completed. Kept last {keep_last_n} crawl directories."
        )

    def list_crawls(self):
        """
        List all available crawl directories.

        Returns:
            List of crawl directory paths
        """
        from pathlib import Path

        output_path = Path(self.output_dir)
        crawl_dirs = [
            d
            for d in output_path.iterdir()
            if d.is_dir() and d.name.startswith("crawl_")
        ]
        crawl_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        self.logger.info(
            f"Found {len(crawl_dirs)} crawl directories in {self.output_dir}:"
        )
        for i, crawl_dir in enumerate(crawl_dirs, 1):
            self.logger.info(
                f"  {i:2d}. {crawl_dir.name} (Modified: {crawl_dir.stat().st_mtime})"
            )

        return crawl_dirs


def main():
    """
    Scrape sites, extract performer data, and store in the database.

    Daily update (scrapes 3 fresh pages from each site):
      uv run python orchestator.py

    More pages or specific site:
      uv run python orchestator.py -site anvids_dapmodels -n 5 --delay 1
      uv run python orchestator.py -n 30 --delay 0.5 --no-stop

    Batch extract old HTML files:
      uv run python orchestator.py --extract data/scrapes/crawl_12345
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape performer data from adult sites"
    )
    parser.add_argument(
        "-site", "--site", type=str,
        help="Site to scrape (from urls.yaml). Default: all sites",
    )
    parser.add_argument(
        "-n", "--limit", type=int, default=3,
        help="Pages to scrape per site (default: 3)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.5,
        help="Delay between requests in seconds (default: 1.5)",
    )
    parser.add_argument(
        "--no-stop", action="store_false", dest="stop_on_old", default=True,
        help="Don't stop when a page has no new content",
    )
    parser.add_argument(
        "--extract", type=str, metavar="DIR",
        help="Extract HTML files from a crawl directory into CSV + DB",
    )

    args = parser.parse_args()
    orchestator = Orchestator()

    if args.extract:
        from dbadd import add_performers_from_csv
        from extractor import process_html_files

        print(f"Extracting from {args.extract}...")
        process_html_files(args.extract, "extracted.csv")
        print("Updating database...")
        add_performers_from_csv("extracted.csv", "performers.db")
        return

    site = args.site or "all sites"
    print(f"Scraping {args.limit} page(s) from {site}...")
    orchestator.start_scraping_workflow(
        max_concurrent=1,
        delay_between_requests=args.delay,
        limit_per_url_type=args.limit,
        site_filter=args.site,
        stop_on_no_new=args.stop_on_old,
    )

    print(f"\nDone — check https://booksi.duckdns.org:8007/performers/")


if __name__ == "__main__":
    main()
