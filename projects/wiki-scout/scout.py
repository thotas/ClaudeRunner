#!/usr/bin/env python3
"""
Wiki Scout - Structural analysis tool for wiki
Scans wiki for broken wikilinks, missing frontmatter, and orphaned entries.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
from pathlib import Path


def load_config(config_path="config.json"):
    """Load configuration from JSON file."""
    with open(config_path, 'r') as f:
        return json.load(f)


def parse_frontmatter(content):
    """Parse YAML frontmatter from markdown content.
    
    Returns tuple: (frontmatter_dict, body_content)
    Frontmatter is between --- markers at start of file.
    """
    lines = content.split('\n')
    
    # Check for opening ---
    if not lines or lines[0].strip() != '---':
        return {}, content
    
    # Find closing ---
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == '---':
            end_idx = i
            break
    
    if end_idx is None:
        return {}, content
    
    # Parse frontmatter lines
    frontmatter = {}
    for line in lines[1:end_idx]:
        if ':' in line:
            key, _, value = line.partition(':')
            frontmatter[key.strip()] = value.strip()
    
    body = '\n'.join(lines[end_idx + 1:])
    return frontmatter, body


def extract_wikilinks(content):
    """Extract all wikilinks from content. Returns list of slug strings."""
    pattern = r'\[\[([^\]]+)\]\]'
    return re.findall(pattern, content)


def find_markdown_files(wiki_path):
    """Recursively find all .md files in wiki directory."""
    wiki_path = Path(wiki_path).expanduser().resolve()
    return list(wiki_path.rglob("*.md"))


def check_frontmatter(file_path, required_fields=None):
    """Check if file has valid frontmatter with required fields."""
    if required_fields is None:
        required_fields = ['title', 'created', 'updated', 'type', 'tags']
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return [f"Cannot read file: {e}"]
    
    frontmatter, _ = parse_frontmatter(content)
    
    issues = []
    for field in required_fields:
        if field not in frontmatter or not frontmatter[field]:
            issues.append(f"Missing or empty frontmatter field: {field}")
    
    return issues


def check_broken_links(file_path, all_slugs):
    """Check for wikilinks pointing to non-existent pages."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return [f"Cannot read file: {e}"]
    
    wikilinks = extract_wikilinks(content)
    issues = []
    
    for link in wikilinks:
        slug = link.strip()
        if slug not in all_slugs:
            issues.append(f"Broken wikilink: [[{slug}]]")
    
    return issues


def get_index_entries(index_path):
    """Parse index.md to get list of entry slugs."""
    if not os.path.exists(index_path):
        return set()
    
    with open(index_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract wikilinks from index
    slugs = set()
    for link in extract_wikilinks(content):
        slugs.add(link.strip())
    
    return slugs


def check_orphans(file_path, index_entries):
    """Check if a file is missing from index (orphan)."""
    # Get slug from filename
    slug = file_path.stem
    
    if slug not in index_entries:
        return [f"Orphaned entry: {slug} not in index.md"]
    
    return []


def send_telegram_alert(token, user_id, message):
    """Send message via Telegram bot."""
    if not token or not user_id:
        return False
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        'chat_id': user_id,
        'text': message,
        'parse_mode': 'HTML'
    })
    
    try:
        req = urllib.request.Request(url, data=data.encode('utf-8'), method='POST')
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except Exception:
        return False


def run_scout(config_path="config.json"):
    """Main scout execution."""
    config = load_config(config_path)
    
    wiki_path = Path(config['wiki_path']).expanduser().resolve()
    do_check_frontmatter = config.get('check_frontmatter', True)
    do_check_broken_links = config.get('check_broken_links', True)
    do_check_orphans = config.get('check_orphans', True)
    telegram_alert = config.get('telegram_alert', False)
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    telegram_user = config.get('telegram_user_id', '')
    issues_threshold = config.get('issues_threshold', 1)
    
    # Find all markdown files
    md_files = find_markdown_files(wiki_path)
    
    # Build set of all valid slugs (filenames without extension)
    all_slugs = {f.stem for f in md_files}
    
    # Get index entries for orphan detection
    index_path = wiki_path / 'index.md'
    index_entries = get_index_entries(index_path) if index_path.exists() else set()
    
    # Collect all issues
    all_issues = []
    
    # Check each file
    for md_file in md_files:
        file_issues = []
        
        if do_check_frontmatter:
            file_issues.extend(check_frontmatter(md_file))
        
        if do_check_broken_links:
            file_issues.extend(check_broken_links(md_file, all_slugs))
        
        if do_check_orphans:
            file_issues.extend(check_orphans(md_file, index_entries))
        
        for issue in file_issues:
            all_issues.append({
                'file': str(md_file.relative_to(wiki_path)),
                'issue': issue
            })
    
    # Output structured report
    report = {
        'total_files': len(md_files),
        'total_issues': len(all_issues),
        'issues': all_issues
    }
    
    print(json.dumps(report, indent=2))
    
    # Send Telegram alert if enabled and threshold exceeded
    if telegram_alert and len(all_issues) >= issues_threshold:
        msg = f"Wiki Scout Report\n\nFiles scanned: {len(md_files)}\nIssues found: {len(all_issues)}\n\n"
        for item in all_issues[:10]:  # Limit to first 10 for Telegram
            msg += f"• {item['file']}: {item['issue']}\n"
        if len(all_issues) > 10:
            msg += f"\n...and {len(all_issues) - 10} more issues"
        
        send_telegram_alert(telegram_token, telegram_user, msg)
    
    return len(all_issues)


if __name__ == '__main__':
    config_path = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    issue_count = run_scout(config_path)
    sys.exit(issue_count)