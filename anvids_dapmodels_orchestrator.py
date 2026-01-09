#!/usr/bin/env python3
"""
Orchestrator for the anvids_dapmodels scraper.

This script integrates the anvids_dapmodels scraper with the existing URL generator
to process the specific URLs from the configuration.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent))

from anvids_dapmodels_scraper import AnvidsDapModelsScraperModule
from url_generator import URLGenerator


def main():
    print("Anvids DAP Models Scraper Orchestrator")
    print("=" * 40)

    # Initialize URL generator to get URLs
    url_gen = URLGenerator()

    # Get the anvids_dapmodels URLs from the config
    all_urls = url_gen.generate_all_urls()
    anvids_dapmodels_urls = [
        url
        for url in all_urls
        if "anvids_dapmodels" in url_gen.config["urls"][0]["name"]
        or "models/niche/double_anal" in url
    ]

    # More robust way to get the specific URLs
    anvids_dapmodels_urls = []
    for url_config in url_gen.config["urls"]:
        if url_config["name"] == "anvids_dapmodels":
            # Regenerate URLs for this specific config
            temp_urls = url_gen.generate_urls_for_config(url_config)
            anvids_dapmodels_urls.extend(temp_urls)

    if not anvids_dapmodels_urls:
        print("No anvids_dapmodels URLs found in the configuration.")
        print("Looking for all URLs matching the pattern...")
        # Fallback: find URLs that match the expected pattern
        anvids_dapmodels_urls = [
            url for url in all_urls if "models/niche/double_anal/page" in url
        ]

    print(f"Found {len(anvids_dapmodels_urls)} anvids_dapmodels URLs to process")

    if not anvids_dapmodels_urls:
        print("No URLs to process. Please check your urls.yaml configuration.")
        return

    print("\nURLs to process:")
    for i, url in enumerate(anvids_dapmodels_urls, 1):
        print(f"  {i}. {url}")

    # Automatically proceed for automated execution
    print("\nProceeding automatically without confirmation for demo purposes...")
    print(f"Will scrape {len(anvids_dapmodels_urls)} URLs")

    # Initialize the scraper
    scraper = AnvidsDapModelsScraperModule(
        delay_between_requests=1.5,  # Respectful delay
        crawl_name="anvids_dapmodels_orchestrated",
    )

    print(f"\nStarting to scrape {len(anvids_dapmodels_urls)} pages...")

    # Scrape the pages
    results = scraper.scrape_multiple_pages(
        anvids_dapmodels_urls, config_name="anvids_dapmodels"
    )

    # Print summary
    successful = sum(1 for r in results if r.result.value == "success")
    failed = sum(1 for r in results if r.result.value == "failed")
    retry = sum(1 for r in results if r.result.value == "retry")

    print(f"\nScraping Summary:")
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")
    print(f"  Retry: {retry}")
    print(f"  Total: {len(results)}")

    # Save aggregated models
    csv_path = scraper.save_aggregated_models(config_name="anvids_dapmodels")

    if csv_path:
        print(f"\nAggregated models saved to: {csv_path}")
        print("Data includes: model names, profile URLs, thumbnails, video counts")


if __name__ == "__main__":
    main()
