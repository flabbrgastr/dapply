#!/usr/bin/env python3
"""
Simple runner for the anvids_dapmodels scraper.

This script provides an easy way to run the anvids_dapmodels scraper
with default settings.
"""

import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent))

from anvids_dapmodels_scraper import AnvidsDapModelsScraperModule


def run_anvids_dapmodels_scraper():
    """Run the anvids_dapmodels scraper with default settings."""
    print("Running Anvids DAP Models Scraper")
    print("=" * 35)

    # Initialize the scraper
    scraper = AnvidsDapModelsScraperModule(
        delay_between_requests=1.0,  # Respectful delay
        crawl_name="anvids_dapmodels_run",
    )

    # Example: Scrape a few sample pages
    sample_urls = [
        "https://www.analvids.com/models/niche/double_anal/page/1/",
        "https://www.analvids.com/models/niche/double_anal/page/2/",
    ]

    print(f"Scraping {len(sample_urls)} sample pages...")
    results = scraper.scrape_multiple_pages(sample_urls, config_name="anvids_dapmodels")

    # Print results summary
    for i, result in enumerate(results):
        print(
            f"Page {i + 1}: {result.url} - {result.result.value} - {result.extracted_data.get('models_count', 0) if result.extracted_data else 0} models"
        )

    # Save aggregated data
    csv_path = scraper.save_aggregated_models(config_name="anvids_dapmodels")

    if csv_path:
        print(f"\nAggregated data saved! Check: {csv_path}")
        print("Data includes: model names, profile URLs, thumbnails, video counts")


if __name__ == "__main__":
    run_anvids_dapmodels_scraper()
