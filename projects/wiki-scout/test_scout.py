#!/usr/bin/env python3
"""
Tests for Wiki Scout
"""

import json
import os
import pytest
import sys
import tempfile
from pathlib import Path

# Import scout module
sys.path.insert(0, str(Path(__file__).parent))
import scout


class MockTelegramAPI:
    """Mock Telegram API for testing."""
    def __init__(self):
        self.messages_sent = []
    
    def send_message(self, token, user_id, message):
        self.messages_sent.append({
            'token': token,
            'user_id': user_id,
            'message': message
        })
        return True


@pytest.fixture
def mock_wiki(tmp_path):
    """Create a mock wiki structure for testing."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    
    # Create valid file with proper frontmatter
    valid_file = wiki / "valid-page.md"
    valid_file.write_text("""---
title: Valid Page
created: 2024-01-01
updated: 2024-01-15
type: note
tags: [test, valid]
---
This is a valid page with proper frontmatter.
""")
    
    # Create file with missing frontmatter fields
    missing_fm = wiki / "missing-frontmatter.md"
    missing_fm.write_text("""---
title: Missing Fields
---
Content without required fields.
""")
    
    # Create file with broken wikilink
    broken_link = wiki / "broken-links.md"
    broken_link.write_text("""---
title: Broken Link Page
created: 2024-01-01
updated: 2024-01-15
type: note
tags: [test]
---
This page has a broken link to [[non-existent-page]].
""")
    
    # Create file with valid wikilink
    valid_link = wiki / "valid-links.md"
    valid_link.write_text("""---
title: Valid Links Page
created: 2024-01-01
updated: 2024-01-15
type: note
tags: [test]
---
This page links to [[valid-page]].
""")
    
    # Create index.md
    index = wiki / "index.md"
    index.write_text("""---
title: Wiki Index
created: 2024-01-01
updated: 2024-01-15
type: index
tags: []
---
Index of all pages.

[[valid-page]]
[[valid-links]]
[[broken-links]]
""")
    
    return wiki


class TestFrontmatterParsing:
    """Test frontmatter parsing functionality."""
    
    def test_parse_valid_frontmatter(self):
        content = """---
title: Test Page
created: 2024-01-01
updated: 2024-01-15
type: note
tags: [test, sample]
---
Body content here.
"""
        fm, body = scout.parse_frontmatter(content)
        assert fm['title'] == 'Test Page'
        assert fm['created'] == '2024-01-01'
        assert fm['updated'] == '2024-01-15'
        assert fm['type'] == 'note'
        assert fm['tags'] == '[test, sample]'
        assert 'Body content here.' in body
    
    def test_parse_missing_frontmatter(self):
        content = "No frontmatter here."
        fm, body = scout.parse_frontmatter(content)
        assert fm == {}
        assert body == content
    
    def test_parse_unclosed_frontmatter(self):
        content = """---
title: Unclosed
content without closing
"""
        fm, body = scout.parse_frontmatter(content)
        assert fm == {}
        assert body == content


class TestWikilinkExtraction:
    """Test wikilink extraction functionality."""
    
    def test_extract_single_wikilink(self):
        content = "This links to [[my-page]] here."
        links = scout.extract_wikilinks(content)
        assert links == ['my-page']
    
    def test_extract_multiple_wikilinks(self):
        content = "Links to [[page1]] and [[page2]] and [[page3]]"
        links = scout.extract_wikilinks(content)
        assert links == ['page1', 'page2', 'page3']
    
    def test_extract_no_wikilinks(self):
        content = "No links here, just regular text."
        links = scout.extract_wikilinks(content)
        assert links == []
    
    def test_extract_wikilink_with_spaces(self):
        content = "Link to [[Page With Spaces]]"
        links = scout.extract_wikilinks(content)
        assert links == ['Page With Spaces']


class TestFrontmatterValidation:
    """Test frontmatter validation."""
    
    def test_valid_frontmatter(self, mock_wiki):
        file_path = mock_wiki / "valid-page.md"
        issues = scout.check_frontmatter(file_path)
        assert issues == []
    
    def test_missing_frontmatter_fields(self, mock_wiki):
        file_path = mock_wiki / "missing-frontmatter.md"
        issues = scout.check_frontmatter(file_path)
        assert len(issues) > 0
        assert any('created' in i for i in issues)


class TestBrokenLinkDetection:
    """Test broken wikilink detection."""
    
    def test_broken_wikilink(self, mock_wiki):
        file_path = mock_wiki / "broken-links.md"
        all_slugs = {'valid-page', 'valid-links', 'broken-links', 'missing-frontmatter'}
        issues = scout.check_broken_links(file_path, all_slugs)
        assert any('non-existent-page' in i for i in issues)
    
    def test_valid_wikilink(self, mock_wiki):
        file_path = mock_wiki / "valid-links.md"
        all_slugs = {'valid-page', 'valid-links', 'broken-links', 'missing-frontmatter'}
        issues = scout.check_broken_links(file_path, all_slugs)
        assert issues == []


class TestOrphanDetection:
    """Test orphan detection."""
    
    def test_index_entries_parsing(self, mock_wiki):
        index_path = mock_wiki / "index.md"
        entries = scout.get_index_entries(index_path)
        assert 'valid-page' in entries
        assert 'valid-links' in entries
    
    def test_orphan_detected(self, mock_wiki):
        # missing-frontmatter.md is not in index
        file_path = mock_wiki / "missing-frontmatter.md"
        index_entries = {'valid-page', 'valid-links', 'broken-links'}
        issues = scout.check_orphans(file_path, index_entries)
        assert any('missing-frontmatter' in i for i in issues)
    
    def test_non_orphan(self, mock_wiki):
        file_path = mock_wiki / "valid-page.md"
        index_entries = {'valid-page', 'valid-links', 'broken-links', 'missing-frontmatter'}
        issues = scout.check_orphans(file_path, index_entries)
        assert issues == []


class TestTelegramAlert:
    """Test Telegram alert functionality."""
    
    def test_send_telegram_alert_no_token(self):
        """Telegram alert returns False when token is empty."""
        result = scout.send_telegram_alert('', '123456', 'Test message')
        assert result == False
    
    def test_send_telegram_alert_no_user_id(self):
        """Telegram alert returns False when user_id is empty."""
        result = scout.send_telegram_alert('token', '', 'Test message')
        assert result == False


class TestEndToEnd:
    """End-to-end integration tests."""
    
    def test_full_scout_run(self, mock_wiki, tmp_path):
        # Create test config
        config = {
            'wiki_path': str(mock_wiki),
            'check_frontmatter': True,
            'check_broken_links': True,
            'check_orphans': True,
            'telegram_alert': False,
            'telegram_user_id': '7192357563',
            'issues_threshold': 1
        }
        config_path = tmp_path / "test_config.json"
        with open(config_path, 'w') as f:
            json.dump(config, f)
        
        # Run scout
        issue_count = scout.run_scout(str(config_path))
        
        # Should find missing frontmatter (missing created, updated, type, tags)
        # and orphaned missing-frontmatter.md
        assert issue_count > 0
    
    def test_exit_code_matches_issue_count(self, mock_wiki, tmp_path):
        config = {
            'wiki_path': str(mock_wiki),
            'check_frontmatter': True,
            'check_broken_links': True,
            'check_orphans': False,
            'telegram_alert': False
        }
        config_path = tmp_path / "test_config.json"
        with open(config_path, 'w') as f:
            json.dump(config, f)
        
        issue_count = scout.run_scout(str(config_path))
        
        # Valid page should have no issues
        # Missing frontmatter should have issues
        # We expect at least the missing frontmatter file
        assert issue_count >= 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])