#!/usr/bin/env python3
"""
URL Generator and Scraper Status Tracker

This script generates URLs from the configuration file and tracks which URLs
have been processed by a scraper using a simple status tracking system.
"""

import yaml
import os
from datetime import datetime, timedelta
from itertools import product


class URLGenerator:
    def __init__(self, config_file='urls.yaml'):
        self.config_file = config_file
        self.status_file = 'url_status_tracking.txt'
        self.load_config()
        self.load_status()

    def load_config(self):
        """Load the URL configuration from YAML file"""
        with open(self.config_file, 'r') as file:
            self.config = yaml.safe_load(file)

    def load_status(self):
        """Load the status tracking from file"""
        self.completed_urls = {}  # Map URL -> status tag (e.g., 'X', 'X30', 'AUTOEXIT')
        self.failed_urls = set()
        self.failure_counts = {}  # Track how many times each URL has failed

        if os.path.exists(self.status_file):
            with open(self.status_file, 'r') as file:
                for line in file:
                    line = line.strip()
                    if line.startswith('[X'):
                        close_bracket_pos = line.find(']')
                        if close_bracket_pos != -1:
                            status_tag = line[1:close_bracket_pos]
                            url = line[close_bracket_pos + 1:].strip()
                            self.completed_urls[url] = status_tag
                    elif line.startswith('[AUTOEXIT]'):
                        url = line[10:].strip()
                        self.completed_urls[url] = 'AUTOEXIT'
                    elif line.startswith('[ ]'):
                        # TODO state, nothing to track
                        pass
                    elif line.startswith('[-'):
                        # Failed state with failure count
                        close_bracket_pos = line.find(']')
                        if close_bracket_pos != -1:
                            try:
                                failure_count_str = line[2:close_bracket_pos]
                                failure_count = int(failure_count_str)
                                url = line[close_bracket_pos + 2:].strip()  # Remove '[-{num}] ' prefix
                                self.failed_urls.add(url)
                                self.failure_counts[url] = failure_count
                            except ValueError:
                                # Malformed line, treat as TODO
                                pass

    def save_status(self):
        """Save the status tracking to file"""
        # Read all URLs from config to maintain complete list
        all_urls = self.generate_all_urls()
        with open(self.status_file, 'w') as file:
            for url in all_urls:
                if url in self.completed_urls:
                    status_tag = self.completed_urls[url]
                    file.write(f"[{status_tag}] {url}\n")
                elif url in self.failed_urls:
                    file.write(f"[-{self.failure_counts.get(url, 1)}] {url}\n")
                else:
                    file.write(f"[ ] {url}\n")

    def mark_url_done(self, url, tag='X'):
        """Mark a URL as completed with an optional tag"""
        self.completed_urls[url] = tag
        # Remove from failed if it was there
        if url in self.failed_urls:
            self.failed_urls.remove(url)
            if url in self.failure_counts:
                del self.failure_counts[url]
        self.save_status()

    def mark_url_failed(self, url):
        """Mark a URL as failed, incrementing the failure count"""
        self.failed_urls.add(url)
        # Remove from completed if it was there
        if url in self.completed_urls:
            self.completed_urls.remove(url)

        # Increment failure count
        if url in self.failure_counts:
            self.failure_counts[url] += 1
        else:
            self.failure_counts[url] = 1
        self.save_status()

    def is_url_done(self, url):
        """Check if a URL has been completed"""
        return url in self.completed_urls

    def is_url_failed(self, url):
        """Check if a URL has failed"""
        return url in self.failed_urls

    def get_failure_count(self, url):
        """Get the failure count for a URL"""
        return self.failure_counts.get(url, 0)

    def reset_status(self):
        """Reset the status tracking to clean state"""
        # Create new sets and dictionaries
        self.completed_urls = {}
        self.failed_urls = set()
        self.failure_counts = {}
        # Wipe the status file
        if os.path.exists(self.status_file):
            os.remove(self.status_file)
        # Initialize with empty state
        all_urls = self.generate_all_urls()
        with open(self.status_file, 'w') as file:
            for url in all_urls:
                file.write(f"[ ] {url}\n")

    def generate_urls_for_config(self, url_config):
        """Generate URLs for a single configuration entry"""
        urls = []

        if url_config['type'] == 'templated':
            base_url = url_config['url']
            template_vars = url_config['template_vars']

            # Get all combinations of template variables
            var_names = list(template_vars.keys())
            var_values = []

            for var_name in var_names:
                var_config = template_vars[var_name]
                var_type = var_config.get('type', 'options')

                if var_type == 'options':
                    # For options type, use the values directly
                    if 'values' in var_config:
                        var_values.append(var_config['values'])
                elif var_type == 'increment':
                    # For increment type, generate the range
                    start = var_config['start']
                    end = var_config['end']
                    step = var_config.get('step', 1)
                    inc_values = list(range(start, end + 1, step))
                    var_values.append(inc_values)
                elif var_type == 'date':
                    # For date type, generate the date range
                    start_date = datetime.strptime(var_config['start'], "%Y-%m-%d")
                    end_date = datetime.strptime(var_config['end'], "%Y-%m-%d")
                    date_list = []
                    current_date = start_date
                    while current_date <= end_date:
                        formatted_date = current_date.strftime(var_config['format'].replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d"))
                        date_list.append(formatted_date)
                        current_date += timedelta(days=1)
                    var_values.append(date_list)

            # Generate combinations
            for combo in product(*var_values):
                url = base_url
                for i, var_name in enumerate(var_names):
                    # Replace $var_name with the actual value
                    url = url.replace(f"${var_name}", str(combo[i]))

                urls.append(url)

        return urls

    def generate_all_urls(self):
        """Generate all URLs from the configuration"""
        all_urls = []
        for url_config in self.config['urls']:
            urls = self.generate_urls_for_config(url_config)
            all_urls.extend(urls)
        return all_urls

    def get_todo_urls(self):
        """Get only URLs that haven't been successfully completed yet (including failed ones that should be retried)"""
        all_urls = self.generate_all_urls()
        todo_urls = [url for url in all_urls if not self.is_url_done(url)]
        return todo_urls

    def get_pending_urls(self):
        """Get only URLs that have never been successfully completed (not including failed ones)"""
        all_urls = self.generate_all_urls()
        pending_urls = [url for url in all_urls if not self.is_url_done(url) and not self.is_url_failed(url)]
        return pending_urls

    def print_status_summary(self):
        """Print a summary of completion status"""
        all_urls = self.generate_all_urls()
        total_count = len(all_urls)
        completed_count = len([url for url in all_urls if self.is_url_done(url)])
        failed_count = len([url for url in all_urls if self.is_url_failed(url)])
        pending_count = len([url for url in all_urls if not self.is_url_done(url) and not self.is_url_failed(url)])

        print(f"URL Processing Status:")
        print(f"  Total URLs:         {total_count}")
        print(f"  Completed [X]:      {completed_count}")
        print(f"  Pending [ ]:        {pending_count}")
        print(f"  Failed [-N]:        {failed_count}")
        print(f"  Remaining to Process: {failed_count + pending_count}")
        print(f"  Progress:           {completed_count/total_count*100:.1f}%") if total_count > 0 else print("  Progress:           0%")
        print()

    def print_todo_urls(self, limit=None):
        """Print URLs that still need to be processed"""
        todo_urls = self.get_todo_urls()
        if limit:
            todo_urls = todo_urls[:limit]

        print(f"URLs to process ({len(todo_urls)} remaining):")
        print("-" * 60)
        for i, url in enumerate(todo_urls, 1):
            status = "X" if self.is_url_done(url) else \
                     f"-{self.get_failure_count(url)}" if self.is_url_failed(url) else \
                     " "
            print(f"{i:3d}. [{status}] {url}")
