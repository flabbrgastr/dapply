"""
Multi-site HTML Extractor - Extract structured data following the standard output schema
Supports sxyprn.com and analvids.com
"""

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def extract_from_file(html_file_path):
    """
    Extract structured data from HTML files, detecting site-specific logic automatically.

    Args:
        html_file_path (str): Path to the HTML file to extract from

    Returns:
        list: List of dictionaries containing extracted data
    """
    with open(html_file_path, "r", encoding="utf-8") as file:
        content = file.read()

    soup = BeautifulSoup(content, "html.parser")

    # Detect domain from metadata comments
    domain = ""
    domain_match = re.search(r"<!-- Domain: (.*?) -->", content)
    if domain_match:
        domain = domain_match.group(1).strip()

    # Fallback detection
    if not domain:
        full_path = str(html_file_path).lower()
        if "sxyprn" in full_path:
            domain = "sxyprn.com"
        elif "analvids" in full_path:
            domain = "www.analvids.com"

    if "sxyprn.com" in domain:
        return _extract_sxyprn(soup, html_file_path)
    elif "analvids.com" in domain:
        return _extract_analvids(soup, html_file_path)
    else:
        # Generic fallback or empty
        return []


def _extract_sxyprn(soup, html_file_path):
    """Specific extraction for sxyprn.com"""
    results = []
    post_containers = soup.find_all("div", class_="post_el_small")

    for container in post_containers:
        post_text_elem = container.find(class_="post_text")
        if not post_text_elem:
            continue

        title = post_text_elem.get_text(separator=" ", strip=True)
        title = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", title)
        title = re.sub(r"([a-zA-Z])-\s*", r"\1 - ", title)
        title = " ".join(title.split())

        performers = []
        ps_link_elements = container.find_all(
            class_="ps_link", attrs={"data-subkey": True}
        )
        for ps_link_elem in ps_link_elements:
            subkey_val = ps_link_elem.get("data-subkey")
            if subkey_val and subkey_val.strip() and subkey_val not in performers:
                if "+" not in subkey_val or not any(
                    word in subkey_val.lower()
                    for word in ["legal", "porno", "only", "fans", "porn", "box"]
                ):
                    performers.append(subkey_val.strip())

        item_date = ""
        hits = ""
        post_time_elem = container.find(class_="post_control_time")
        if post_time_elem:
            time_text = post_time_elem.get_text(strip=True)
            if "·" in time_text:
                parts = time_text.split("·", 1)
                item_date = parts[0].strip()
                hits_match = re.search(r"(\d+(?:[,]\d+)*)", parts[1].strip())
                hits = hits_match.group(1).replace(",", "") if hits_match else ""

        item_url = ""
        for link in container.find_all("a", href=True):
            href = link.get("href")
            if "/post/" in href and ("?sk=" in href or "&sk=" in href):
                # Extract the base post URL without session parameters for uniqueness
                # e.g., https://sxyprn.com/post/63ed75271e1ce.html?sk=abc -> https://sxyprn.com/post/63ed75271e1ce.html
                full_url = urljoin("https://sxyprn.com", href)
                # Split at the first '?' to remove query parameters
                item_url = full_url.split("?")[0]
                break

        if title:
            results.append(
                {
                    "item_url": item_url,
                    "title": title,
                    "performers": "; ".join(performers) if performers else "",
                    "item_date": item_date,
                    "hits": hits,
                    "last_updated": datetime.today().strftime("%Y-%m-%d"),
                    "crawls": "1",
                    "source_file": str(html_file_path),
                }
            )
    return results


def _extract_analvids(soup, html_file_path):
    """Specific extraction for analvids.com"""
    results = []

    # Try scenes first (standard videos)
    cards = soup.find_all("div", class_=lambda x: x and "card-scene" in x)

    for card in cards:
        text_container = card.find("div", class_="card-scene__text")
        if not text_container:
            continue

        a_tag = text_container.find("a")
        if not a_tag:
            continue

        title = a_tag.get("title") or a_tag.get_text(strip=True)
        item_url = a_tag.get("href", "")

        # Performer extraction removed (previously used heuristics/filters)
        performers = []

        item_date = ""
        time_tag = card.find("div", class_="label--time")
        if time_tag:
            item_date = time_tag.get_text(strip=True)

        hits = ""

        if title:
            results.append(
                {
                    "item_url": item_url,
                    "title": title,
                    "performers": "; ".join(performers) if performers else "NO_NAME",
                    "item_date": item_date,
                    "hits": hits,
                    "last_updated": datetime.today().strftime("%Y-%m-%d"),
                    "crawls": "1",
                    "source_file": str(html_file_path),
                }
            )

    # Try models (performer listings) if no scenes found or in addition
    model_cards = soup.find_all("div", class_="model-top")
    for card in model_cards:
        name_div = card.find("div", class_="model-top__name")
        if not name_div:
            continue

        title = name_div.get("title") or name_div.get_text(strip=True)

        a_tag = card.find("a", class_="model-top__img")
        item_url = a_tag.get("href", "") if a_tag else ""

        scene_count_tag = card.find("div", class_="model-top__scene")
        # Store scene count in 'hits' field for models
        hits = scene_count_tag.get_text(strip=True) if scene_count_tag else ""

        # For models, the 'performers' is just the name
        performers = [title]

        if title:
            results.append(
                {
                    "item_url": item_url,
                    "title": f"Model: {title}",
                    "performers": title,
                    "item_date": "",
                    "hits": hits,
                    "last_updated": datetime.today().strftime("%Y-%m-%d"),
                    "crawls": "1",
                    "source_file": str(html_file_path),
                }
            )

    return results


def process_html_files(html_dir, output_csv):
    """Process all HTML files in a directory and append results to CSV"""
    html_dir_path = Path(html_dir)
    existing_urls = set()

    if Path(output_csv).exists():
        with open(output_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("item_url"):
                    existing_urls.add(row["item_url"])

    all_results = []

    for html_file in html_dir_path.glob("**/*.html"):
        file_results = extract_from_file(html_file)
        for res in file_results:
            if res["item_url"] not in existing_urls:
                all_results.append(res)
                existing_urls.add(res["item_url"])

    if not all_results:
        return 0

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
    file_exists = Path(output_csv).exists()
    mode = "a" if file_exists else "w"

    with open(output_csv, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(all_results)

    return len(all_results)


if __name__ == "__main__":
    pass
