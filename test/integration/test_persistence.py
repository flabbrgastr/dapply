"""
Integration tests for the URL Generator workflow.
"""

import pytest
import tempfile
import os
from url_generator import URLGenerator


def test_full_workflow_integration():
    """Test the full workflow: config -> generation -> status tracking -> persistence"""
    # Create temporary config file
    config_content = """
urls:
  - name: "test_workflow"
    url: "https://example.com/item=$id&category=$cat"
    type: "templated"
    template_vars:
      id:
        type: "increment"
        start: 1
        end: 2
        step: 1
      cat:
        type: "options"
        values: ["a", "b"]
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as config_f:
        config_f.write(config_content)
        config_path = config_f.name

    # Create a unique status file
    status_fd, status_path = tempfile.mkstemp(suffix='_status.txt')
    os.close(status_fd)

    try:
        # Initialize generator with the specific files
        generator = URLGenerator(config_file=config_path)
        generator.status_file = status_path
        generator.reset_status()  # Ensure clean state

        # Step 1: Generate URLs
        urls = generator.generate_all_urls()
        expected_count = 4  # 2 ids * 2 categories = 4 combinations
        assert len(urls) == expected_count

        expected_urls = {
            "https://example.com/item=1&category=a",
            "https://example.com/item=1&category=b",
            "https://example.com/item=2&category=a",
            "https://example.com/item=2&category=b"
        }
        assert set(urls) == expected_urls

        # Step 2: Process some URLs (mark as done/fail)
        url1 = "https://example.com/item=1&category=a"
        url2 = "https://example.com/item=1&category=b"

        generator.mark_url_done(url1)
        generator.mark_url_failed(url2)

        # Step 3: Verify status
        assert generator.is_url_done(url1)
        assert not generator.is_url_failed(url1)
        assert not generator.is_url_done(url2)
        assert generator.is_url_failed(url2)
        assert generator.get_failure_count(url2) == 1

        # Step 4: Verify persistence by creating new instance
        generator2 = URLGenerator(config_file=config_path)
        generator2.status_file = status_path
        # Load the existing status
        generator2.load_status()

        # Verify statuses persisted
        assert generator2.is_url_done(url1)
        assert generator2.is_url_failed(url2)
        assert generator2.get_failure_count(url2) == 1

    finally:
        # Cleanup
        os.unlink(config_path)
        os.unlink(status_path)


def test_multiple_failures_increment_count():
    """Test that multiple failures increment the failure count correctly across sessions."""
    # Create temporary config file
    config_content = """
urls:
  - name: "failure_test"
    url: "https://example.com/test=$id"
    type: "templated"
    template_vars:
      id:
        type: "increment"
        start: 1
        end: 1
        step: 1
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as config_f:
        config_f.write(config_content)
        config_path = config_f.name

    # Create a unique status file
    status_fd, status_path = tempfile.mkstemp(suffix='_status.txt')
    os.close(status_fd)

    try:
        # Initialize generator
        generator = URLGenerator(config_file=config_path)
        generator.status_file = status_path
        generator.reset_status()  # Ensure clean state

        test_url = "https://example.com/test=1"

        # Fail the same URL multiple times
        generator.mark_url_failed(test_url)
        assert generator.get_failure_count(test_url) == 1

        generator.mark_url_failed(test_url)
        assert generator.get_failure_count(test_url) == 2

        generator.mark_url_failed(test_url)
        assert generator.get_failure_count(test_url) == 3

        # Verify the status file reflects the count
        with open(status_path, 'r') as f:
            content = f.read()
            assert "[-3]" in content  # Should have [-3] for 3 failures
    finally:
        os.unlink(config_path)
        os.unlink(status_path)
