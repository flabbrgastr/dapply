"""
Unit tests for the Orchestator module.
"""

import pytest
import tempfile
import os
from orchestator import Orchestator


def test_orchestator_initialization():
    """Test basic orchestator initialization"""
    config_content = """
urls:
  - name: "simple_test"
    url: "https://httpbin.org/get?id=$id"
    type: "templated"
    template_vars:
      id:
        type: "increment"
        start: 1
        end: 2
        step: 1
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as config_f:
        config_f.write(config_content)
        config_path = config_f.name

    # Create a unique status file
    status_fd, status_path = tempfile.mkstemp(suffix='_status.txt')
    os.close(status_fd)

    try:
        # Initialize orchestator with specific files
        orchestator = Orchestator(
            config_file=config_path,
            status_file=status_path
        )

        # Test that it was initialized properly
        assert orchestator.config_file == config_path
        assert orchestator.status_file == status_path

        # Test URL generation
        urls = orchestator.generate_urls()
        assert len(urls) == 2  # 2 increments: id=1, id=2
        expected_urls = {
            "https://httpbin.org/get?id=1",
            "https://httpbin.org/get?id=2"
        }
        assert set(urls) == expected_urls

    finally:
        os.unlink(config_path)
        os.unlink(status_path)


def test_get_urls_to_process():
    """Test getting URLs that need processing"""
    config_content = """
urls:
  - name: "test_process"
    url: "https://httpbin.org/delay/1?item=$num"
    type: "templated"
    template_vars:
      num:
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

        # Initially, all URLs should need processing
        urls_to_process = orchestator.get_urls_to_process()
        assert len(urls_to_process) == 3  # 3 increments: num=1,2,3

        # Generate URLs to get specific URLs
        all_urls = orchestator.generate_urls()
        test_url = all_urls[0]

        # Mark one as done
        orchestator.url_generator.mark_url_done(test_url)

        # Should have one less URL to process
        urls_to_process_after = orchestator.get_urls_to_process()
        assert len(urls_to_process_after) == 2
        assert test_url not in urls_to_process_after

    finally:
        os.unlink(config_path)
        os.unlink(status_path)


def test_status_summary():
    """Test status summary functionality"""
    config_content = """
urls:
  - name: "summary_test"
    url: "https://example.com/test=$id"
    type: "templated"
    template_vars:
      id:
        type: "increment"
        start: 1
        end: 4
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

        # Generate URLs first
        urls = orchestator.generate_urls()

        # Initially all should be pending
        status = orchestator.get_status_summary()
        assert status['total'] == 4
        assert status['completed'] == 0
        assert status['failed'] == 0
        assert status['pending'] == 4
        assert status['progress_percent'] == 0.0

        # Mark 2 as done and 1 as failed
        orchestator.url_generator.mark_url_done(urls[0])
        orchestator.url_generator.mark_url_done(urls[1])
        orchestator.url_generator.mark_url_failed(urls[2])

        # Check updated status
        status = orchestator.get_status_summary()
        assert status['total'] == 4
        assert status['completed'] == 2
        assert status['failed'] == 1
        assert status['pending'] == 1
        assert status['progress_percent'] == 50.0  # 2/4 = 50%

    finally:
        os.unlink(config_path)
        os.unlink(status_path)
