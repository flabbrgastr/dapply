"""
Additional tests for the n=1 parameter in the Orchestator module.
"""

import pytest
import tempfile
import os
from orchestator import Orchestator


def test_n1_parameter_groups_urls_correctly():
    """Test that the n=1 parameter properly limits to 1 of each URL type"""
    config_content = """
urls:
  - name: "pagination_example"
    url: "https://example.com/page=$page"
    type: "templated"
    template_vars:
      page:
        type: "increment"
        start: 1
        end: 3
        step: 1
  - name: "item_example"
    url: "https://example.com/item/$id"
    type: "templated"
    template_vars:
      id:
        type: "increment"
        start: 100
        end: 102
        step: 1
  - name: "category_example"
    url: "https://api.example.com/data?cat=$category&limit=10"
    type: "templated"
    template_vars:
      category:
        type: "options"
        values: ["tech", "sports", "music"]
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as config_f:
        config_f.write(config_content)
        config_path = config_f.name

    # Create a unique status file
    status_fd, status_path = tempfile.mkstemp(suffix='_status.txt')
    os.close(status_fd)

    try:
        orchestator = Orchestator(
            config_file=config_path,
            status_file=status_path
        )

        # Generate all URLs
        all_urls = orchestator.generate_urls()
        assert len(all_urls) == 3 + 3 + 3  # 3 pagination pages + 3 item IDs + 3 categories = 9 total

        # Get URLs with limit 1 per type
        limited_urls = orchestator.get_urls_to_process(limit_per_type=1)

        # Should have 3 URLs - one from each type
        assert len(limited_urls) == 3

        # Verify we have URLs from different config sources
        urls_by_config = orchestator._group_urls_by_type(limited_urls)
        # Should have 3 different configs represented
        assert len(urls_by_config) == 3

    finally:
        os.unlink(config_path)
        os.unlink(status_path)


def test_n1_parameter_with_no_limit():
    """Test that when limit is None, all URLs are returned"""
    config_content = """
urls:
  - name: "pagination_example"
    url: "https://example.com/page=$page"
    type: "templated"
    template_vars:
      page:
        type: "increment"
        start: 1
        end: 3
        step: 1
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as config_f:
        config_f.write(config_content)
        config_path = config_f.name

    # Create a unique status file
    status_fd, status_path = tempfile.mkstemp(suffix='_status.txt')
    os.close(status_fd)

    try:
        orchestator = Orchestator(
            config_file=config_path,
            status_file=status_path
        )

        # Generate all URLs
        all_urls = orchestator.generate_urls()
        assert len(all_urls) == 3  # 3 pagination pages

        # Get URLs with no limit (should return all)
        all_urls_processed = orchestator.get_urls_to_process(limit_per_type=None)

        # Should have all 3 URLs
        assert len(all_urls_processed) == 3

    finally:
        os.unlink(config_path)
        os.unlink(status_path)
