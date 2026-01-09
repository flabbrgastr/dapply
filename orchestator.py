"""
Orchestator module for the web scraper system.

This module coordinates the workflow between URL generation, scraping,
and status tracking components.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from scraper import ScraperModule
from url_generator import URLGenerator


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
        Get the list of URLs that need to be processed (not completed).

        Args:
            limit_per_type: Maximum number of URLs to return per type (if specified)
            site_filter: Only return URLs from the specified site/config name

        Returns:
            List of URLs that are pending or failed
        """
        all_todo_urls = self.url_generator.get_todo_urls()

        # If site filter is specified, only include URLs from that site
        if site_filter:
            url_config_names = self._get_url_config_names(all_todo_urls)
            all_todo_urls = [
                url for url in all_todo_urls if url_config_names.get(url) == site_filter
            ]

        if limit_per_type is None:
            return all_todo_urls
        else:
            # Group URLs by type and take only the first N of each type
            urls_by_type = self._group_urls_by_type(all_todo_urls)
            limited_urls = []

            for url_type, urls in urls_by_type.items():
                limited_urls.extend(urls[:limit_per_type])

            return limited_urls

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
            random_delay_range=random_delay_range,
            stop_on_no_new=stop_on_no_new,
        )

        self.logger.info("Scraping workflow completed")

    def _handoff_to_scraper(
        self,
        urls: List[str],
        max_concurrent: int,
        delay: float,
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

        # Load known URLs if auto-stop is enabled - memory efficient with pandas
        known_urls = set()
        if stop_on_no_new:
            try:
                import os

                import pandas as pd

                if os.path.exists("extracted.csv"):
                    # Read only the item_url column to minimize memory usage
                    df = pd.read_csv(
                        "extracted.csv", usecols=["item_url"], dtype={"item_url": "str"}
                    )
                    # Create set from non-null values for fast lookup
                    known_urls = set(df["item_url"].dropna().values)
                self.logger.info(
                    f"Loaded {len(known_urls)} known URLs for novelty check"
                )
            except Exception as e:
                self.logger.warning(
                    f"Could not load extracted.csv for novelty check: {e}"
                )

        # Process URLs
        if not stop_on_no_new:
            # Regular batch processing
            for i, url in enumerate(urls):
                self.logger.info(f"Crawling {url}...")
                response = scraper.scrape_batch(
                    [url],
                    max_concurrent=1,
                    url_config_names={url: url_config_names.get(url, "default")},
                    random_delay=None if i == 0 else random_delay_range,
                )[0]
                self._process_scrape_response(response)
        else:
            # Incremental processing with early exit
            from extractor import extract_from_file
            from scraper import ScrapeResult

            for i, url in enumerate(urls):
                self.logger.info(f"Crawling {url}...")
                response = scraper.scrape_batch(
                    [url],
                    max_concurrent=1,
                    url_config_names={url: url_config_names.get(url, "default")},
                    random_delay=None if i == 0 else random_delay_range,
                )[0]

                if response.result == ScrapeResult.SUCCESS and response.filename:
                    self.logger.info(f"Indexing {url}...")
                    items = extract_from_file(response.filename)
                    new_items = [
                        item for item in items if item["item_url"] not in known_urls
                    ]
                    novelty_count = len(new_items)
                    self.logger.info(f"  -> {novelty_count} new items found")

                    # Mark as done with X<count> tag
                    self._process_scrape_response(response, tag=f"X{novelty_count}")

                    # Check if current page has no new content or no items extracted at all
                    if novelty_count == 0:
                        if items:  # Page had items but none were new
                            self.logger.info(
                                f"--- NOVELTY ALERT: No new content found. Stopping early. ---"
                            )
                        else:  # Page had no items extracted at all (might be empty/invalid page)
                            self.logger.info(
                                f"--- EMPTY PAGE ALERT: No items found on page. Stopping early. ---"
                            )

                        # Mark only the VERY NEXT URL as AUTOEXIT to show where we stopped
                        if i + 1 < len(urls):
                            self.url_generator.mark_url_done(
                                urls[i + 1], tag="AUTOEXIT"
                            )
                        break
                    elif items:
                        # Update known_urls for the next page in same session
                        for item in new_items:
                            known_urls.add(item["item_url"])
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
            # Load known URLs for novelty check
            import pandas as pd

            known_urls = set()
            if os.path.exists("extracted.csv"):
                try:
                    df = pd.read_csv(
                        "extracted.csv", usecols=["item_url"], dtype={"item_url": "str"}
                    )
                    known_urls = set(df["item_url"].dropna().values)
                except Exception as e:
                    self.logger.warning(
                        f"Could not load extracted.csv for novelty check: {e}"
                    )

            new_items = [item for item in items if item["item_url"] not in known_urls]
            novelty_count = len(new_items)
            self.logger.info(
                f"  -> {novelty_count} new items found out of {len(items)} total items"
            )

            # Update status with novelty count
            self._process_scrape_response(response, tag=f"X{novelty_count}")

            # Update known_urls for the next processing
            for item in new_items:
                known_urls.add(item["item_url"])

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
    Main entry point for the orchestator with CLI arguments.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Web Scraper Orchestator")
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        help="Limit number of pages per site (default: 10)",
    )
    parser.add_argument(
        "-site", "--site", type=str, help="Only process the specified site name"
    )
    parser.add_argument(
        "--concurrent", type=int, default=3, help="Maximum concurrent requests"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Delay between requests in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--jitter",
        type=float,
        nargs=2,
        metavar=("MIN", "MAX"),
        help="Random delay range between requests",
    )
    parser.add_argument(
        "--reset", action="store_true", help="Reset the workflow status"
    )
    parser.add_argument(
        "--extract",
        type=str,
        metavar="DIR",
        help="Extract data from HTML files in the specified directory",
    )
    parser.add_argument(
        "--dbadd",
        action="store_true",
        help="Update performers database after extraction",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Automatically extract and update DB after scraping",
    )
    parser.add_argument(
        "--stop-on-old",
        action="store_true",
        default=True,
        help="Stop scraping when a page yields no new URLs (default: True)",
    )
    parser.add_argument(
        "--no-stop",
        action="store_false",
        dest="stop_on_old",
        help="Disable auto-stop on old content",
    )
    parser.add_argument(
        "--rm",
        type=str,
        metavar="SITE",
        help="Remove all items for the specified site from CSV and DB",
    )
    parser.add_argument(
        "--url",
        type=str,
        metavar="URL",
        help="Process a specific single URL for testing duplication",
    )

    args = parser.parse_args()

    orchestator = Orchestator()

    jitter = tuple(args.jitter) if args.jitter else None

    if args.reset:
        orchestator.reset_workflow()
        print("Workflow status reset.")

    if args.rm:
        from remover import remove_site_data

        print(f"Removal Mode: Removing data for site '{args.rm}'...")
        remove_site_data(args.rm)
        return

    print("Web Scraper Orchestator")
    print("=" * 30)

    # Show initial status
    status = orchestator.get_status_summary()
    print(f"Total URLs: {status['total']}")
    print(f"Completed: {status['completed']}")
    print(f"Failed: {status['failed']}")
    print(f"Pending: {status['pending']}")
    print(f"Progress: {status['progress_percent']:.1f}%")
    print()

    if args.extract:
        from extractor import process_html_files

        print(f"Extraction Mode: Processing {args.extract}...")
        process_html_files(args.extract, "extracted.csv")

        if args.dbadd:
            from dbadd import add_performers_from_csv

            print("Database Mode: Updating performers.db...")
            add_performers_from_csv("extracted.csv", "performers.db")
        return

    if args.url:
        print(f"Processing single URL: {args.url}")
        # Process the specific URL for testing duplication
        novelty_count, total_items, new_items = orchestator.process_single_url(
            url=args.url, delay_between_requests=args.delay, random_delay_range=jitter
        )
        print(f"Processed {args.url}")
        print(f"Total items found: {total_items}")
        print(f"New items (not duplicates): {novelty_count}")
        print(f"Already existed (duplicates): {total_items - novelty_count}")
        return

    # Start the workflow
    print(f"Starting scraping workflow (limit={args.limit}, site={args.site})...")
    orchestator.start_scraping_workflow(
        max_concurrent=args.concurrent,
        delay_between_requests=args.delay,
        limit_per_url_type=args.limit,
        site_filter=args.site,
        random_delay_range=jitter,
        stop_on_no_new=args.stop_on_old,
    )

    # Auto-process if requested
    if args.auto and orchestator.crawl_name:
        import os

        from dbadd import add_performers_from_csv
        from extractor import process_html_files

        crawl_path = os.path.join(orchestator.output_dir, orchestator.crawl_name)
        if os.path.exists(crawl_path):
            print(f"\nAuto-processing results from {crawl_path}...")
            process_html_files(crawl_path, "extracted.csv")
            add_performers_from_csv("extracted.csv", "performers.db")
        else:
            print(f"\nNote: Skip auto-processing, directory not found: {crawl_path}")

    # Show final status
    print("\nFinal Status:")
    final_status = orchestator.get_status_summary()
    print(f"Total URLs: {final_status['total']}")
    print(f"Completed: {final_status['completed']}")
    print(f"Failed: {final_status['failed']}")
    print(f"Pending: {final_status['pending']}")
    print(f"Progress: {final_status['progress_percent']:.1f}%")


if __name__ == "__main__":
    main()
