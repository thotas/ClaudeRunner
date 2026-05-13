#!/usr/bin/env python3
"""
HTML Report Card Generator
Reads JSON input and produces a beautiful dark-themed standalone HTML report.
"""

import argparse
import json
import sys
from pathlib import Path


DARK_THEME_CSS = """
    :root {
        --bg-primary: #0D1117;
        --bg-secondary: #161B22;
        --bg-card: #1C2128;
        --text-primary: #E6EDF3;
        --text-secondary: #8B949E;
        --accent: #C9A96E;
        --accent-subtle: rgba(201, 169, 110, 0.15);
        --border: #30363D;
        --font-display: 'Georgia', 'Times New Roman', serif;
        --font-body: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    }

    *, *::before, *::after {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }

    body {
        background-color: var(--bg-primary);
        color: var(--text-primary);
        font-family: var(--font-body);
        font-size: 16px;
        line-height: 1.6;
        min-height: 100vh;
    }

    .report-container {
        max-width: 800px;
        margin: 0 auto;
        padding: 60px 24px 100px;
    }

    .report-header {
        border-bottom: 1px solid var(--border);
        padding-bottom: 40px;
        margin-bottom: 56px;
    }

    .report-title {
        font-family: var(--font-display);
        font-size: 2.4rem;
        font-weight: normal;
        color: var(--text-primary);
        letter-spacing: -0.02em;
        line-height: 1.2;
    }

    .report-meta {
        margin-top: 16px;
        font-size: 0.875rem;
        color: var(--text-secondary);
    }

    .report-meta span {
        margin-right: 24px;
    }

    .report-section {
        margin-bottom: 48px;
    }

    .section-heading {
        font-family: var(--font-display);
        font-size: 1.35rem;
        font-weight: normal;
        color: var(--accent);
        border-left: 3px solid var(--accent);
        padding-left: 16px;
        margin-bottom: 20px;
        letter-spacing: 0.01em;
    }

    .section-content {
        color: var(--text-primary);
        font-size: 1rem;
        line-height: 1.75;
    }

    .section-content p {
        margin-bottom: 16px;
    }

    .section-content p:last-child {
        margin-bottom: 0;
    }

    .section-list {
        list-style: none;
        padding: 0;
    }

    .section-list li {
        padding: 10px 0;
        border-bottom: 1px solid var(--border);
        color: var(--text-primary);
    }

    .section-list li:last-child {
        border-bottom: none;
    }

    .section-list li::before {
        content: '—';
        color: var(--accent);
        margin-right: 12px;
    }

    .data-table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 8px;
        font-size: 0.9375rem;
    }

    .data-table th {
        text-align: left;
        padding: 12px 16px;
        background: var(--bg-secondary);
        color: var(--accent);
        font-weight: 600;
        border-bottom: 2px solid var(--border);
        font-family: var(--font-display);
        letter-spacing: 0.02em;
    }

    .data-table td {
        padding: 12px 16px;
        border-bottom: 1px solid var(--border);
        color: var(--text-primary);
    }

    .data-table tr:last-child td {
        border-bottom: none;
    }

    .data-table tr:hover td {
        background: var(--accent-subtle);
    }
"""


def escape_html(text):
    """Escape HTML special characters."""
    if text is None:
        return ""
    return (str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;"))


def render_text_section(content):
    """Render a text type section."""
    if not content:
        return ""
    paragraphs = content.split("\n\n")
    html_parts = []
    for p in paragraphs:
        p = p.strip()
        if p:
            html_parts.append(f"<p>{escape_html(p)}</p>")
    return "\n".join(html_parts)


def render_list_section(content):
    """Render a list type section (content is JSON array)."""
    if not content:
        return ""
    items = content if isinstance(content, list) else [content]
    li_items = []
    for item in items:
        if item:
            li_items.append(f"<li>{escape_html(str(item))}</li>")
    return f"<ul class='section-list'>\n" + "\n".join(li_items) + "\n</ul>"


def render_table_section(content):
    """Render a table type section (content has headers and rows)."""
    if not content:
        return ""
    if isinstance(content, dict):
        headers = content.get("headers", [])
        rows = content.get("rows", [])
    elif isinstance(content, list) and len(content) > 0:
        if isinstance(content[0], dict):
            headers = list(content[0].keys())
            rows = [[row.get(h, "") for h in headers] for row in content]
        else:
            headers = ["#"]
            rows = [[item] for item in content]
    else:
        return ""

    if not headers:
        return ""

    th_parts = [f"<th>{escape_html(h)}</th>" for h in headers]
    tr_parts = []
    for row in rows:
        td_parts = [f"<td>{escape_html(str(cell))}</td>" for cell in row]
        tr_parts.append("<tr>" + "".join(td_parts) + "</tr>")

    return (
        f"<table class='data-table'>\n"
        f"<thead>\n<tr>{''.join(th_parts)}</tr>\n</thead>\n"
        f"<tbody>\n{''.join(tr_parts)}\n</tbody>\n"
        f"</table>"
    )


def render_section(section):
    """Render a single section based on its type."""
    heading = escape_html(section.get("heading", ""))
    content = section.get("content", "")
    section_type = section.get("type", "text").lower()

    if section_type == "list":
        content_html = render_list_section(content)
    elif section_type == "table":
        content_html = render_table_section(content)
    else:
        content_html = render_text_section(content)

    return (
        f"<section class='report-section'>\n"
        f"<h2 class='section-heading'>{heading}</h2>\n"
        f"<div class='section-content'>{content_html}</div>\n"
        f"</section>"
    )


def generate_html(data):
    """Generate complete HTML from JSON data."""
    title = escape_html(data.get("title", "Report"))
    meta = data.get("meta", {})
    author = escape_html(meta.get("author", ""))
    date = escape_html(meta.get("date", ""))
    sections = data.get("sections", [])

    meta_html = ""
    if author:
        meta_html += f"<span>By {author}</span>"
    if date:
        meta_html += f"<span>{date}</span>"

    sections_html = "\n".join(render_section(s) for s in sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
{DARK_THEME_CSS}
    </style>
</head>
<body>
    <div class="report-container">
        <header class="report-header">
            <h1 class="report-title">{title}</h1>
            <div class="report-meta">{meta_html}</div>
        </header>
        <main>
{sections_html}
        </main>
    </div>
</body>
</html>
"""


def load_json(input_path):
    """Load and parse JSON from file."""
    with open(input_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_html(output_path, html_content):
    """Save HTML content to file."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def main():
    parser = argparse.ArgumentParser(
        description="Generate dark-themed HTML report from JSON"
    )
    parser.add_argument("input", help="Input JSON file path")
    parser.add_argument("output", help="Output HTML file path")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        sys.exit(f"Error: Input file not found: {input_path}")

    data = load_json(input_path)
    html = generate_html(data)
    save_html(output_path, html)

    print(f"Report generated: {output_path}")


if __name__ == "__main__":
    main()
