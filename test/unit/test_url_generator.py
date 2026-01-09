"""
Unit tests for the URL Generator component.
"""

import pytest
import tempfile
import os
from url_generator import URLGenerator


@pytest.fixture
def sample_config_and_status_file():
    """Sample configuration and unique status file for testing"""
    config_content = """
urls:
  - name: "simple_increment"
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

    # Create a unique status file for this test
    status_fd, status_path = tempfile.mkstemp(suffix='_status.txt')
    os.close(status_fd)

    yield config_path, status_path

    os.unlink(config_path)
    os.unlink(status_path)


def create_generator_with_paths(config_path, status_path):
    """Helper to create a URLGenerator with specific config and status files"""
    generator = URLGenerator(config_file=config_path)
    generator.status_file = status_path
    # Reset to ensure clean state
    generator.reset_status()
    return generator


def test_url_generation_basic(sample_config_and_status_file):
    """Test basic URL generation from configuration"""
    config_path, status_path = sample_config_and_status_file
    generator = create_generator_with_paths(config_path, status_path)
    urls = generator.generate_all_urls()

    expected_urls = [
        "https://example.com/page=1",
        "https://example.com/page=2",
        "https://example.com/page=3"
    ]

    assert len(urls) == 3
    assert set(urls) == set(expected_urls)


def test_url_status_initial_state(sample_config_and_status_file):
    """Test initial status state for generated URLs"""
    config_path, status_path = sample_config_and_status_file
    generator = create_generator_with_paths(config_path, status_path)
    urls = generator.generate_all_urls()

    for url in urls:
        # Initially, no URLs should be marked as done
        assert not generator.is_url_done(url)
        # Initially, no URLs should be marked as failed
        assert not generator.is_url_failed(url)


def test_mark_url_done(sample_config_and_status_file):
    """Test marking a URL as done"""
    config_path, status_path = sample_config_and_status_file
    generator = create_generator_with_paths(config_path, status_path)
    urls = generator.generate_all_urls()
    test_url = urls[0]

    # Mark as done
    generator.mark_url_done(test_url)

    # Verify it's marked as done
    assert generator.is_url_done(test_url)
    # Verify it's no longer marked as failed
    assert not generator.is_url_failed(test_url)


def test_mark_url_failed(sample_config_and_status_file):
    """Test marking a URL as failed"""
    config_path, status_path = sample_config_and_status_file
    generator = create_generator_with_paths(config_path, status_path)
    urls = generator.generate_all_urls()
    test_url = urls[0]

    # Mark as failed
    generator.mark_url_failed(test_url)

    # Verify it's marked as failed
    assert generator.is_url_failed(test_url)
    # Verify it's no longer marked as done
    assert not generator.is_url_done(test_url)
    # Verify failure count is 1
    assert generator.get_failure_count(test_url) == 1


def test_failure_count_increment(sample_config_and_status_file):
    """Test that failure count increments correctly"""
    config_path, status_path = sample_config_and_status_file
    generator = create_generator_with_paths(config_path, status_path)
    urls = generator.generate_all_urls()
    test_url = urls[0]

    # Mark as failed multiple times
    generator.mark_url_failed(test_url)
    assert generator.get_failure_count(test_url) == 1
    generator.mark_url_failed(test_url)
    assert generator.get_failure_count(test_url) == 2
    generator.mark_url_failed(test_url)
    assert generator.get_failure_count(test_url) == 3

    # Verify failure count is 3
    assert generator.get_failure_count(test_url) == 3


def test_mark_done_clears_failure_state(sample_config_and_status_file):
    """Test that marking as done clears failure state"""
    config_path, status_path = sample_config_and_status_file
    generator = create_generator_with_paths(config_path, status_path)
    urls = generator.generate_all_urls()
    test_url = urls[0]

    # Mark as failed first
    generator.mark_url_failed(test_url)
    assert generator.is_url_failed(test_url)
    assert generator.get_failure_count(test_url) == 1

    # Mark as done - should clear failure state
    generator.mark_url_done(test_url)
    assert generator.is_url_done(test_url)
    assert not generator.is_url_failed(test_url)
    # Should not appear in failure counts anymore
    assert test_url not in generator.failed_urls


def test_get_todo_urls_includes_not_done(sample_config_and_status_file):
    """Test that get_todo_urls returns non-completed URLs"""
    config_path, status_path = sample_config_and_status_file
    generator = create_generator_with_paths(config_path, status_path)
    urls = generator.generate_all_urls()

    # Initially all URLs should be in todo list
    todo_urls = generator.get_todo_urls()
    assert len(todo_urls) == 3
    assert set(todo_urls) == set(urls)

    # Mark one as done
    generator.mark_url_done(urls[0])

    # Should now have 2 todo URLs
    todo_urls = generator.get_todo_urls()
    assert len(todo_urls) == 2
    assert urls[0] not in todo_urls
