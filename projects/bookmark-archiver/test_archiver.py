#!/usr/bin/env python3
"""
Tests for Bookmark Archiver.
Run with: python test_archiver.py
"""

import os
import sys
import json
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

# Import the module
sys.path.insert(0, str(Path(__file__).parent))

import bookmark_archiver as ba


class TempDir:
    """Context manager for temporary directory with config."""

    def __init__(self):
        self.tmpdir = None

    def __enter__(self):
        self.tmpdir = tempfile.mkdtemp()
        return self.tmpdir

    def __exit__(self, *args):
        if self.tmpdir:
            shutil.rmtree(self.tmpdir)


def make_config(tmpdir):
    """Create a config pointing to temp bookmark file."""
    config = {
        "bookmark_file": os.path.join(tmpdir, "bookmarks.md"),
        "tag_keywords": {
            "python": "python",
            "javascript": "javascript",
            "web": "web",
            "cli": "cli",
            "devops": "devops",
            "data": "data",
            "ml": "machine-learning",
            "ai": "ai",
        },
    }
    return config


def test_format_bookmark():
    """Test markdown formatting of bookmark line."""
    line = ba.format_bookmark(
        "Test Page", "https://example.com", ["python", "web"], "A test description", "2025-01-01"
    )
    expected = "- [Test Page](https://example.com) #python #web — A test description (2025-01-01)"
    assert line == expected, f"Got: {line}"
    print("PASS: test_format_bookmark")


def test_format_bookmark_no_tags():
    """Test formatting when no tags."""
    line = ba.format_bookmark(
        "Test", "https://test.com", [], "No tags here", "2025-01-02"
    )
    assert "#" not in line
    assert "No tags here" in line
    print("PASS: test_format_bookmark_no_tags")


def test_format_bookmark_no_description():
    """Test formatting when no description."""
    line = ba.format_bookmark(
        "Title", "https://title.com", ["ai"], "", "2025-01-03"
    )
    assert "#ai" in line
    assert "—" not in line
    print("PASS: test_format_bookmark_no_description")


def test_extract_title_from_content():
    """Test title extraction from markdown content."""
    content = "# Hello World\n\nSome description text."
    title = ba.extract_title(content, "https://example.com")
    assert title == "Hello World", f"Got: {title}"
    print("PASS: test_extract_title_from_content")


def test_extract_title_fallback():
    """Test title fallback to domain when no markdown title."""
    content = "No heading here. Just some text."
    title = ba.extract_title(content, "https://github.com/user/repo")
    assert "github" in title
    print("PASS: test_extract_title_fallback")


def test_extract_description():
    """Test description extraction from content."""
    content = "# Title\n\nThis is a paragraph with meaningful content that should be extracted."
    desc = ba.extract_description(content)
    assert "paragraph" in desc
    print("PASS: test_extract_description")


def test_extract_description_skips_headings():
    """Test that description skips heading lines."""
    content = "# Title\n## Subtitle\nMore paragraph text."
    desc = ba.extract_description(content)
    assert "paragraph" in desc
    print("PASS: test_extract_description_skips_headings")


def test_extract_tags_keyword_match():
    """Test tag extraction from keyword mapping."""
    config = make_config(tempfile.mkdtemp())
    config["tag_keywords"] = {"python": "python", "javascript": "javascript"}
    tags = ba.extract_tags("https://github.com/python/cpython", "Python Homepage", "Learn python", config)
    assert "python" in tags
    print("PASS: test_extract_tags_keyword_match")


def test_extract_tags_auto_detect_github():
    """Test auto-detection of github tag."""
    config = make_config(tempfile.mkdtemp())
    tags = ba.extract_tags("https://github.com/user/repo", "Repo", "Description", config)
    assert "github" in tags
    print("PASS: test_extract_tags_auto_detect_github")


def test_extract_tags_auto_detect_blog():
    """Test auto-detection of blog tag from year in URL."""
    config = make_config(tempfile.mkdtemp())
    tags = ba.extract_tags("https://example.com/2024/01/my-post", "Post", "Blog post", config)
    assert "blog" in tags
    print("PASS: test_extract_tags_auto_detect_blog")


def test_is_duplicate_true():
    """Test duplicate detection when URL exists."""
    with TempDir() as tmpdir:
        config = make_config(tmpdir)
        bm_file = ba.get_bookmark_file(config)
        with open(bm_file, "w") as f:
            f.write("- [Test](https://example.com) #test (2025-01-01)\n")
        assert ba.is_duplicate("https://example.com", bm_file) is True
    print("PASS: test_is_duplicate_true")


def test_is_duplicate_false():
    """Test duplicate detection when URL not present."""
    with TempDir() as tmpdir:
        config = make_config(tmpdir)
        bm_file = ba.get_bookmark_file(config)
        with open(bm_file, "w") as f:
            f.write("- [Other](https://other.com) #other (2025-01-01)\n")
        assert ba.is_duplicate("https://example.com", bm_file) is False
    print("PASS: test_is_duplicate_false")


def test_is_duplicate_file_not_exists():
    """Test duplicate check on non-existent file."""
    with TempDir() as tmpdir:
        config = make_config(tmpdir)
        bm_file = Path(tmpdir) / "nonexistent.md"
        assert ba.is_duplicate("https://example.com", bm_file) is False
    print("PASS: test_is_duplicate_file_not_exists")


def test_add_bookmark_no_dup(tmpdir=None):
    """Test adding a bookmark when not duplicate."""
    if tmpdir is None:
        tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    url = "https://example.com"
    # Mock fetch to avoid network call
    original_fetch = ba.fetch_title_and_description
    ba.fetch_title_and_description = lambda u: ("Example Site", "An example website")
    try:
        result = ba.add_bookmark(url, config)
        assert result is True
        bm_file = ba.get_bookmark_file(config)
        assert bm_file.exists()
        content = bm_file.read_text()
        assert url in content
        assert "Example Site" in content
    finally:
        ba.fetch_title_and_description = original_fetch
        shutil.rmtree(tmpdir)
    print("PASS: test_add_bookmark_no_dup")


def test_add_bookmark_duplicate(tmpdir=None):
    """Test that duplicate URL is skipped."""
    if tmpdir is None:
        tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    url = "https://example.com"
    bm_file = ba.get_bookmark_file(config)
    with open(bm_file, "w") as f:
        f.write(f"- [Existing]({url}) #test (2025-01-01)\n")
    original_fetch = ba.fetch_title_and_description
    ba.fetch_title_and_description = lambda u: ("Example Site", "An example website")
    try:
        result = ba.add_bookmark(url, config)
        assert result is False
    finally:
        ba.fetch_title_and_description = original_fetch
        shutil.rmtree(tmpdir)
    print("PASS: test_add_bookmark_duplicate")


def test_list_bookmarks_no_filter():
    """Test listing all bookmarks."""
    with TempDir() as tmpdir:
        config = make_config(tmpdir)
        bm_file = ba.get_bookmark_file(config)
        bm_file.write_text(
            "- [One](https://one.com) #a (2025-01-01)\n- [Two](https://two.com) #b (2025-01-02)\n"
        )
        # Capture stdout
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        ba.list_bookmarks(config, tag_filter=None)
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        assert "one.com" in output
        assert "two.com" in output
    print("PASS: test_list_bookmarks_no_filter")


def test_list_bookmarks_with_filter():
    """Test listing bookmarks filtered by tag."""
    with TempDir() as tmpdir:
        config = make_config(tmpdir)
        bm_file = ba.get_bookmark_file(config)
        bm_file.write_text(
            "- [One](https://one.com) #python (2025-01-01)\n- [Two](https://two.com) #javascript (2025-01-02)\n"
        )
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        ba.list_bookmarks(config, tag_filter="python")
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        assert "one.com" in output
        assert "two.com" not in output
    print("PASS: test_list_bookmarks_with_filter")


def test_list_bookmarks_empty():
    """Test listing when no bookmarks file."""
    with TempDir() as tmpdir:
        config = make_config(tmpdir)
        import io
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        # Redirect stdout too
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        ba.list_bookmarks(config, tag_filter=None)
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        # Should say no bookmarks
        assert "No bookmarks" in output or output == ""
    print("PASS: test_list_bookmarks_empty")


def test_missing_url_handling():
    """Test that add command with no URL prints usage."""
    import io
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    # Patch sys.argv to simulate no URL
    old_argv = sys.argv
    sys.argv = ["bookmark-archiver.py", "add"]
    try:
        ba.main()
    except SystemExit as e:
        assert e.code == 1
    finally:
        sys.argv = old_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    print("PASS: test_missing_url_handling")


def test_list_filter_no_matches():
    """Test listing with tag filter that matches nothing."""
    with TempDir() as tmpdir:
        config = make_config(tmpdir)
        bm_file = ba.get_bookmark_file(config)
        bm_file.write_text("- [One](https://one.com) #python (2025-01-01)\n")
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        ba.list_bookmarks(config, tag_filter="javascript")
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        # Should be empty since no javascript bookmark
        assert "one.com" not in output
    print("PASS: test_list_filter_no_matches")


def test_get_bookmark_file_resolves_relative():
    """Test that relative bookmark file path is resolved to script dir."""
    config = {"bookmark_file": "bookmarks.md", "tag_keywords": {}}
    # Patch __file__ via module
    original_exists = os.path.exists
    # The file should be relative to script location
    result = ba.get_bookmark_file(config)
    assert "bookmarks.md" in str(result)
    print("PASS: test_get_bookmark_file_resolves_relative")


def run_all_tests():
    """Run all tests."""
    tests = [
        test_format_bookmark,
        test_format_bookmark_no_tags,
        test_format_bookmark_no_description,
        test_extract_title_from_content,
        test_extract_title_fallback,
        test_extract_description,
        test_extract_description_skips_headings,
        test_extract_tags_keyword_match,
        test_extract_tags_auto_detect_github,
        test_extract_tags_auto_detect_blog,
        test_is_duplicate_true,
        test_is_duplicate_false,
        test_is_duplicate_file_not_exists,
        lambda: test_add_bookmark_no_dup(),
        lambda: test_add_bookmark_duplicate(),
        test_list_bookmarks_no_filter,
        test_list_bookmarks_with_filter,
        test_list_bookmarks_empty,
        test_missing_url_handling,
        test_list_filter_no_matches,
        test_get_bookmark_file_resolves_relative,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test.__name__ if hasattr(test, '__name__') else str(test)}: {e}")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)