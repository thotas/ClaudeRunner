#!/usr/bin/env python3
"""
Test suite for HTML Report Card Generator.
Run with: python test_report_card.py
"""

import json
import os
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

# Load module from filename (avoids hyphen/underscore mismatch)
_spec = importlib.util.spec_from_file_location(
    "report_card_generator",
    Path(__file__).parent / "report-card-generator.py"
)
rcg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rcg)

# Re-bind the module name so imports work
sys.modules["report_card_generator"] = rcg

from report_card_generator import (
    escape_html,
    generate_html,
    load_json,
    render_list_section,
    render_section,
    render_table_section,
    render_text_section,
    save_html,
)


class TestEscapeHtml(unittest.TestCase):
    """Tests for HTML escaping."""

    def test_escapes_ampersand(self):
        self.assertEqual(escape_html("A & B"), "A &amp; B")

    def test_escapes_less_than(self):
        self.assertEqual(escape_html("<tag>"), "&lt;tag&gt;")

    def test_escapes_greater_than(self):
        self.assertEqual(escape_html("a > b"), "a &gt; b")

    def test_escapes_double_quote(self):
        self.assertEqual(escape_html('say "hello"'), "say &quot;hello&quot;")

    def test_escapes_single_quote(self):
        self.assertEqual(escape_html("it's"), "it&#39;s")

    def test_handles_none(self):
        self.assertEqual(escape_html(None), "")

    def test_handles_integer(self):
        self.assertEqual(escape_html(42), "42")

    def test_preserves_plain_text(self):
        self.assertEqual(escape_html("Hello World"), "Hello World")


class TestRenderTextSection(unittest.TestCase):
    """Tests for text section rendering."""

    def test_empty_string(self):
        self.assertEqual(render_text_section(""), "")

    def test_single_paragraph(self):
        result = render_text_section("Hello world")
        self.assertIn("<p>Hello world</p>", result)

    def test_multiple_paragraphs(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = render_text_section(text)
        self.assertIn("<p>First paragraph.</p>", result)
        self.assertIn("<p>Second paragraph.</p>", result)

    def test_html_escaped(self):
        result = render_text_section("<script>alert('xss')</script>")
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)


class TestRenderListSection(unittest.TestCase):
    """Tests for list section rendering."""

    def test_empty_content(self):
        self.assertEqual(render_list_section(""), "")

    def test_single_item(self):
        result = render_list_section(["Item one"])
        self.assertIn("<li>Item one</li>", result)
        self.assertIn("section-list", result)

    def test_multiple_items(self):
        items = ["First", "Second", "Third"]
        result = render_list_section(items)
        for item in items:
            self.assertIn(f"<li>{item}</li>", result)

    def test_non_list_input(self):
        result = render_list_section("single item")
        self.assertIn("<li>single item</li>", result)


class TestRenderTableSection(unittest.TestCase):
    """Tests for table section rendering."""

    def test_empty_content(self):
        self.assertEqual(render_table_section(""), "")

    def test_dict_format(self):
        data = {
            "headers": ["Name", "Score"],
            "rows": [["Alice", "95"], ["Bob", "87"]]
        }
        result = render_table_section(data)
        self.assertIn("<th>Name</th>", result)
        self.assertIn("<th>Score</th>", result)
        self.assertIn("<td>Alice</td>", result)
        self.assertIn("<td>Bob</td>", result)
        self.assertIn("data-table", result)

    def test_list_of_dicts(self):
        data = [
            {"Name": "Alice", "Score": "95"},
            {"Name": "Bob", "Score": "87"}
        ]
        result = render_table_section(data)
        self.assertIn("<th>Name</th>", result)
        self.assertIn("<th>Score</th>", result)

    def test_list_of_lists(self):
        data = [
            ["Alice", "95"],
            ["Bob", "87"]
        ]
        result = render_table_section(data)
        # List of lists uses # as header; each row is one cell
        self.assertIn("<th>#</th>", result)
        self.assertIn("<td>[&#39;Alice&#39;, &#39;95&#39;]</td>", result)


class TestRenderSection(unittest.TestCase):
    """Tests for full section rendering."""

    def test_text_section(self):
        section = {
            "heading": "Overview",
            "type": "text",
            "content": "Some text content."
        }
        result = render_section(section)
        self.assertIn("section-heading", result)
        self.assertIn("Overview", result)
        self.assertIn("Some text content.", result)

    def test_list_section(self):
        section = {
            "heading": "Items",
            "type": "list",
            "content": ["Item A", "Item B"]
        }
        result = render_section(section)
        self.assertIn("Items", result)
        self.assertIn("<li>Item A</li>", result)

    def test_table_section(self):
        section = {
            "heading": "Data",
            "type": "table",
            "content": {"headers": ["A"], "rows": [["1"]]}
        }
        result = render_section(section)
        self.assertIn("Data", result)
        self.assertIn("data-table", result)

    def test_defaults_to_text_for_unknown_type(self):
        section = {
            "heading": "Unknown",
            "type": "unknown",
            "content": "Fallback content"
        }
        result = render_section(section)
        self.assertIn("Fallback content", result)


class TestGenerateHtml(unittest.TestCase):
    """Tests for full HTML generation."""

    def test_generates_doctype(self):
        data = {"title": "Test", "sections": [], "meta": {}}
        result = generate_html(data)
        self.assertIn("<!DOCTYPE html>", result)

    def test_contains_title(self):
        data = {"title": "My Report", "sections": [], "meta": {}}
        result = generate_html(data)
        self.assertIn("My Report", result)
        self.assertIn("<title>My Report</title>", result)

    def test_contains_author_and_date(self):
        data = {
            "title": "Test",
            "sections": [],
            "meta": {"author": "John Doe", "date": "2026-01-15"}
        }
        result = generate_html(data)
        self.assertIn("John Doe", result)
        self.assertIn("2026-01-15", result)

    def test_renders_sections(self):
        data = {
            "title": "Test",
            "sections": [
                {"heading": "Section One", "type": "text", "content": "Content here."}
            ],
            "meta": {}
        }
        result = generate_html(data)
        self.assertIn("Section One", result)
        self.assertIn("Content here.", result)

    def test_missing_title_defaults(self):
        data = {"sections": [], "meta": {}}
        result = generate_html(data)
        self.assertIn("<title>Report</title>", result)

    def test_empty_sections_handled(self):
        data = {"title": "Test", "sections": [], "meta": {}}
        result = generate_html(data)
        self.assertIn("<main>", result)
        self.assertIn("report-container", result)


class TestLoadJson(unittest.TestCase):
    """Tests for JSON loading."""

    def test_loads_valid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"title": "Test"}, f)
            f.flush()
            data = load_json(f.name)
        os.unlink(f.name)
        self.assertEqual(data["title"], "Test")

    def test_raises_on_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_json("/nonexistent/file.json")


class TestSaveHtml(unittest.TestCase):
    """Tests for HTML saving."""

    def test_saves_content(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        save_html(path, "<html>Test</html>")
        with open(path) as f:
            content = f.read()
        os.unlink(path)
        self.assertEqual(content, "<html>Test</html>")


class TestMissingFields(unittest.TestCase):
    """Tests for handling of missing/empty fields."""

    def test_missing_heading(self):
        section = {"type": "text", "content": "Content"}
        result = render_section(section)
        self.assertIn("section-heading", result)

    def test_missing_content(self):
        section = {"heading": "Title", "type": "text"}
        result = render_section(section)
        self.assertIn("Title", result)

    def test_missing_meta(self):
        data = {"title": "Test", "sections": []}
        result = generate_html(data)
        self.assertIn("Test", result)

    def test_empty_meta(self):
        data = {"title": "Test", "sections": [], "meta": {}}
        result = generate_html(data)
        self.assertIn("Test", result)


class TestEmptySections(unittest.TestCase):
    """Tests for empty section handling."""

    def test_empty_text_content(self):
        section = {"heading": "Empty", "type": "text", "content": ""}
        result = render_section(section)
        self.assertIn("Empty", result)

    def test_empty_list_content(self):
        section = {"heading": "Empty List", "type": "list", "content": []}
        result = render_section(section)
        self.assertIn("Empty List", result)

    def test_empty_table_content(self):
        section = {"heading": "Empty Table", "type": "table", "content": {}}
        result = render_section(section)
        self.assertIn("Empty Table", result)


if __name__ == "__main__":
    unittest.main()
