#!/usr/bin/env python3
"""
Bookmark Archiver CLI — add URLs with auto-tagging, list/search bookmarks.
Usage:
  python bookmark-archiver.py add <url>
  python bookmark-archiver.py list [--tag <tag>]
"""

import sys
import json
import re
import os
import subprocess
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def get_bookmark_file(config):
    path = config.get("bookmark_file", "bookmarks.md")
    if not os.path.isabs(path):
        return Path(__file__).parent / path
    return Path(path)


def fetch_title_and_description(url):
    """Fetch page title and description using web_extract."""
    try:
        result = subprocess.run(
            ["web_extract", url],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            content = result.stdout
            title = extract_title(content, url)
            description = extract_description(content)
            return title, description
    except Exception:
        pass
    return None, None


def extract_title(content, url):
    """Extract title from web content."""
    lines = content.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("# ") and len(line) > 2:
            return line[2:].strip()
    domain = url.split("/")[2] if "://" in url else url
    return domain


def extract_description(content):
    """Extract a short description from page content."""
    lines = content.split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!["):
            continue
        if len(line) >= 20:
            line = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)
            line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
            line = re.sub(r'\*([^*]+)\*', r'\1', line)
            if len(line) > 200:
                line = line[:197] + "..."
            return line
    return ""


def extract_tags(url, title, description, config):
    """Extract tags based on keywords and URL/content analysis."""
    tag_keywords = config.get("tag_keywords", {})
    text = f"{url} {title or ''} {description or ''}".lower()
    tags = set()
    for keyword, tag in tag_keywords.items():
        if keyword.lower() in text:
            tags.add(tag)
    if "github" in url:
        tags.add("github")
    if re.search(r'/\d{4}/', url):
        tags.add("blog")
    return sorted(tags)


def is_duplicate(url, bookmark_file):
    """Check if URL already exists in bookmark file."""
    if not bookmark_file.exists():
        return False
    with open(bookmark_file, "r") as f:
        content = f.read()
    return url in content


def format_bookmark(title, url, tags, description, date_str):
    """Format a bookmark line in markdown."""
    tag_str = " ".join(f"#{tag}" for tag in tags)
    desc_str = f" — {description}" if description else ""
    return f"- [{title}]({url}) {tag_str}{desc_str} ({date_str})"


def add_bookmark(url, config):
    """Add a bookmark from URL."""
    bookmark_file = get_bookmark_file(config)

    if is_duplicate(url, bookmark_file):
        print(f"Duplicate: {url} already in bookmarks.", file=sys.stderr)
        return False

    title, description = fetch_title_and_description(url)
    if not title:
        title = url

    tags = extract_tags(url, title, description, config)

    date_str = datetime.now().strftime("%Y-%m-%d")
    line = format_bookmark(title, url, tags, description, date_str)

    with open(bookmark_file, "a") as f:
        if bookmark_file.exists() and os.path.getsize(bookmark_file) > 0:
            f.write("\n")
        f.write(line + "\n")

    print(f"Added: {title}")
    return True


def list_bookmarks(config, tag_filter=None):
    """List bookmarks, optionally filtered by tag."""
    bookmark_file = get_bookmark_file(config)
    if not bookmark_file.exists():
        print("No bookmarks found.")
        return

    with open(bookmark_file, "r") as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line or not line.startswith("- "):
            continue
        if tag_filter and f"#{tag_filter}" not in line:
            continue
        print(line)


def main():
    if len(sys.argv) < 2:
        print("Usage: bookmark-archiver.py add <url>")
        print("       bookmark-archiver.py list [--tag <tag>]")
        sys.exit(1)

    config = load_config()
    command = sys.argv[1]

    if command == "add":
        if len(sys.argv) < 3:
            print("Usage: bookmark-archiver.py add <url>", file=sys.stderr)
            sys.exit(1)
        url = sys.argv[2]
        success = add_bookmark(url, config)
        sys.exit(0 if success else 1)

    elif command == "list":
        tag_filter = None
        if "--tag" in sys.argv:
            idx = sys.argv.index("--tag")
            if idx + 1 < len(sys.argv):
                tag_filter = sys.argv[idx + 1]
        list_bookmarks(config, tag_filter)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()