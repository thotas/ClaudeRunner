#!/usr/bin/env python3
"""
env-audit.py - .env file auditor CLI
Scans .env files for missing required vars, stale keys, and duplicate definitions.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple


def load_config(config_path: str = "config.json") -> dict:
    """Load configuration from JSON file."""
    with open(config_path, 'r') as f:
        return json.load(f)


def parse_env_file(filepath: Path) -> Dict[str, Tuple[str, int]]:
    """Parse an .env file and return a dict of key -> (value, line_number)."""
    env_vars = {}
    if not filepath.exists():
        return env_vars
    
    with open(filepath, 'r') as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            # Handle inline comments
            if '#' in line:
                # Only strip if # is after an = (it's a comment, not part of value)
                parts = line.split('=', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    # value contains the # comment
                    val_part = parts[1]
                    # Find the # that is a comment (not in quotes)
                    match = re.match(r'^([^#"]*|"[^"]*")(#.*)?$', val_part)
                    if match:
                        line = f"{key}={match.group(1) or ''}"
            
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    env_vars[key] = (value, line_no)
    
    return env_vars


def find_env_files(directory: str, patterns: List[str]) -> List[Path]:
    """Find all .env files in directory matching patterns."""
    env_files = []
    dir_path = Path(directory)
    
    for pattern in patterns:
        if pattern.startswith('**/'):
            # Glob pattern for recursive search
            for match in dir_path.rglob(pattern[3:]):
                if match.is_file():
                    env_files.append(match)
        else:
            # Simple filename or pattern
            for match in dir_path.glob(pattern):
                if match.is_file():
                    env_files.append(match)
    
    return list(set(env_files))  # Dedupe


def detect_secrets(value: str, patterns: List[str]) -> List[str]:
    """Detect potential secrets in a value."""
    detected = []
    for pattern in patterns:
        try:
            if re.search(pattern, value, re.IGNORECASE):
                detected.append(pattern)
        except re.error:
            continue
    return detected


def check_missing_vars(
    env_vars: Dict[str, Tuple[str, int]],
    required_vars: List[str],
    known_secrets: List[str]
) -> List[Dict]:
    """Check for missing required variables."""
    missing = []
    env_keys = set(env_vars.keys())
    known_secret_keys = set(known_secrets)
    
    for var in required_vars:
        if var not in env_keys:
            missing.append({
                'key': var,
                'type': 'missing',
                'severity': 'high',
                'message': f"Required variable '{var}' is not defined"
            })
    
    return missing


def check_stale_keys(
    env_vars: Dict[str, Tuple[str, int]],
    required_vars: List[str]
) -> List[Dict]:
    """Check for stale/unused keys that aren't in required_vars."""
    stale = []
    env_keys = set(env_vars.keys())
    required_set = set(required_vars)
    
    for key in env_keys:
        # Check if key appears to be stale (not required and no common pattern)
        if key not in required_set:
            # Common patterns that might legitimately exist
            common_patterns = [
                r'^NODE_ENV$',
                r'^ENV$',
                r'^DEBUG$',
                r'^LOG_LEVEL$',
                r'^PORT$',
                r'^HOST$',
                r'^.*_VERSION$',
                r'^.*_ENABLED$',
                r'^.*_DIR$',
                r'^PATH$',
            ]
            is_common = any(re.match(p, key) for p in common_patterns)
            if not is_common:
                stale.append({
                    'key': key,
                    'type': 'stale',
                    'severity': 'medium',
                    'message': f"Key '{key}' is not in required_vars list",
                    'line': env_vars[key][1]
                })
    
    return stale


def check_duplicates(all_env_vars: Dict[str, List[Tuple[str, Path]]]) -> List[Dict]:
    """Check for duplicate variable definitions across all files."""
    duplicates = []
    
    for key, occurrences in all_env_vars.items():
        if len(occurrences) > 1:
            files = [str(p) for p, _ in occurrences]
            duplicates.append({
                'key': key,
                'type': 'duplicate',
                'severity': 'high',
                'message': f"Variable '{key}' defined in multiple files: {', '.join(files)}",
                'files': files,
                'count': len(occurrences)
            })
    
    return duplicates


def scan_directory(
    directory: str,
    config: dict
) -> dict:
    """Scan directory for .env file issues."""
    patterns = config.get('env_file_patterns', ['.env*', '*.env*'])
    required_vars = config.get('required_vars', [])
    secret_patterns = config.get('known_secret_patterns', [])
    
    env_files = find_env_files(directory, patterns)
    
    results = {
        'scan_time': datetime.now().isoformat(),
        'directory': directory,
        'files_scanned': len(env_files),
        'files': [],
        'issues': {
            'missing': [],
            'stale': [],
            'duplicates': [],
            'secrets': []
        },
        'summary': {
            'total_issues': 0,
            'high_severity': 0,
            'medium_severity': 0,
            'low_severity': 0
        }
    }
    
    all_env_vars = defaultdict(list)  # key -> [(value, filepath), ...]
    
    for env_file in env_files:
        file_data = {
            'path': str(env_file),
            'variables': {},
            'issues': []
        }
        
        env_vars = parse_env_file(env_file)
        file_data['variables'] = {k: v[0] for k, v in env_vars.items()}
        
        # Track for duplicate detection
        for key, (value, line_no) in env_vars.items():
            all_env_vars[key].append((value, env_file))
        
        # Check missing
        missing = check_missing_vars(env_vars, required_vars, [])
        file_data['issues'].extend(missing)
        results['issues']['missing'].extend(missing)
        
        # Check stale
        stale = check_stale_keys(env_vars, required_vars)
        file_data['issues'].extend(stale)
        results['issues']['stale'].extend(stale)
        
        # Check for secrets
        for key, (value, line_no) in env_vars.items():
            if detect_secrets(value, secret_patterns):
                results['issues']['secrets'].append({
                    'key': key,
                    'type': 'secret',
                    'severity': 'high',
                    'message': f"Potential secret detected in '{key}'",
                    'file': str(env_file),
                    'line': line_no
                })
        
        results['files'].append(file_data)
    
    # Check duplicates across files
    duplicates = check_duplicates(all_env_vars)
    results['issues']['duplicates'] = duplicates
    
    # Calculate summary
    for issue_type in ['missing', 'stale', 'duplicates', 'secrets']:
        for issue in results['issues'][issue_type]:
            results['summary']['total_issues'] += 1
            severity = issue.get('severity', 'low')
            if severity == 'high':
                results['summary']['high_severity'] += 1
            elif severity == 'medium':
                results['summary']['medium_severity'] += 1
            else:
                results['summary']['low_severity'] += 1
    
    return results


def generate_json_report(results: dict) -> str:
    """Generate JSON report."""
    return json.dumps(results, indent=2)


def generate_markdown_report(results: dict) -> str:
    """Generate Markdown report."""
    lines = [
        "# Environment Audit Report",
        "",
        f"**Scan Time:** {results['scan_time']}",
        f"**Directory:** {results['directory']}",
        f"**Files Scanned:** {results['files_scanned']}",
        "",
        "## Summary",
        "",
        f"- **Total Issues:** {results['summary']['total_issues']}",
        f"  - High: {results['summary']['high_severity']}",
        f"  - Medium: {results['summary']['medium_severity']}",
        f"  - Low: {results['summary']['low_severity']}",
        "",
    ]
    
    if results['issues']['missing']:
        lines.append("## Missing Required Variables")
        lines.append("")
        for issue in results['issues']['missing']:
            lines.append(f"- **{issue['key']}**: {issue['message']}")
        lines.append("")
    
    if results['issues']['stale']:
        lines.append("## Stale Keys")
        lines.append("")
        for issue in results['issues']['stale']:
            lines.append(f"- **{issue['key']}** (line {issue.get('line', '?')}): {issue['message']}")
        lines.append("")
    
    if results['issues']['duplicates']:
        lines.append("## Duplicate Definitions")
        lines.append("")
        for issue in results['issues']['duplicates']:
            lines.append(f"- **{issue['key']}**: {issue['message']}")
        lines.append("")
    
    if results['issues']['secrets']:
        lines.append("## Potential Secrets Detected")
        lines.append("")
        for issue in results['issues']['secrets']:
            lines.append(f"- **{issue['key']}** ({issue['file']}, line {issue.get('line', '?')}): {issue['message']}")
        lines.append("")
    
    return "\n".join(lines)


def generate_html_report(results: dict) -> str:
    """Generate HTML report with dark-themed style."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Environment Audit Report</title>
    <style>
        :root {{
            --bg-primary: #0f0f0f;
            --bg-secondary: #1a1a1a;
            --bg-tertiary: #242424;
            --text-primary: #e0e0e0;
            --text-secondary: #a0a0a0;
            --accent-blue: #4a9eff;
            --accent-green: #4ade80;
            --accent-yellow: #facc15;
            --accent-red: #f87171;
            --border-color: #333;
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 2rem;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        
        header {{
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border-color);
        }}
        
        h1 {{
            font-size: 2rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }}
        
        .meta {{
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}
        
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        
        .summary-card {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1.25rem;
        }}
        
        .summary-card .label {{
            color: var(--text-secondary);
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.5rem;
        }}
        
        .summary-card .value {{
            font-size: 1.75rem;
            font-weight: 600;
        }}
        
        .severity-high {{ color: var(--accent-red); }}
        .severity-medium {{ color: var(--accent-yellow); }}
        .severity-low {{ color: var(--accent-green); }}
        
        .section {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            margin-bottom: 1.5rem;
            overflow: hidden;
        }}
        
        .section-header {{
            background: var(--bg-tertiary);
            padding: 1rem 1.25rem;
            font-weight: 600;
            font-size: 1.1rem;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .section-content {{
            padding: 1.25rem;
        }}
        
        .issue-item {{
            background: var(--bg-tertiary);
            border-radius: 6px;
            padding: 1rem;
            margin-bottom: 0.75rem;
        }}
        
        .issue-item:last-child {{
            margin-bottom: 0;
        }}
        
        .issue-key {{
            font-weight: 600;
            color: var(--accent-blue);
            margin-bottom: 0.25rem;
        }}
        
        .issue-message {{
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}
        
        .badge {{
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}
        
        .badge-high {{ background: rgba(248, 113, 113, 0.2); color: var(--accent-red); }}
        .badge-medium {{ background: rgba(250, 204, 21, 0.2); color: var(--accent-yellow); }}
        .badge-low {{ background: rgba(74, 222, 128, 0.2); color: var(--accent-green); }}
        
        .file-list {{
            margin-top: 1rem;
        }}
        
        .file-item {{
            background: var(--bg-primary);
            border-radius: 6px;
            padding: 1rem;
            margin-bottom: 0.75rem;
        }}
        
        .file-path {{
            font-family: 'Monaco', 'Menlo', monospace;
            color: var(--accent-blue);
            font-size: 0.9rem;
            margin-bottom: 0.5rem;
        }}
        
        .vars-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 0.5rem;
            margin-top: 0.5rem;
        }}
        
        .var-tag {{
            background: var(--bg-primary);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.8rem;
            font-family: 'Monaco', 'Menlo', monospace;
        }}
        
        .empty-state {{
            color: var(--text-secondary);
            font-style: italic;
            text-align: center;
            padding: 2rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Environment Audit Report</h1>
            <div class="meta">
                Scanned: {results['scan_time']} | Directory: {results['directory']} | Files: {results['files_scanned']}
            </div>
        </header>
        
        <div class="summary">
            <div class="summary-card">
                <div class="label">Total Issues</div>
                <div class="value">{results['summary']['total_issues']}</div>
            </div>
            <div class="summary-card">
                <div class="label">High Severity</div>
                <div class="value severity-high">{results['summary']['high_severity']}</div>
            </div>
            <div class="summary-card">
                <div class="label">Medium Severity</div>
                <div class="value severity-medium">{results['summary']['medium_severity']}</div>
            </div>
            <div class="summary-card">
                <div class="label">Low Severity</div>
                <div class="value severity-low">{results['summary']['low_severity']}</div>
            </div>
        </div>
"""
    
    if results['issues']['missing']:
        html += """
        <div class="section">
            <div class="section-header">Missing Required Variables</div>
            <div class="section-content">
"""
        for issue in results['issues']['missing']:
            html += f"""
                <div class="issue-item">
                    <div class="issue-key">{issue['key']}</div>
                    <div class="issue-message">{issue['message']}</div>
                </div>
"""
        html += """
            </div>
        </div>
"""
    
    if results['issues']['stale']:
        html += """
        <div class="section">
            <div class="section-header">Stale Keys</div>
            <div class="section-content">
"""
        for issue in results['issues']['stale']:
            html += f"""
                <div class="issue-item">
                    <div class="issue-key">{issue['key']}</div>
                    <div class="issue-message">{issue['message']}</div>
                </div>
"""
        html += """
            </div>
        </div>
"""
    
    if results['issues']['duplicates']:
        html += """
        <div class="section">
            <div class="section-header">Duplicate Definitions</div>
            <div class="section-content">
"""
        for issue in results['issues']['duplicates']:
            html += f"""
                <div class="issue-item">
                    <div class="issue-key">{issue['key']} <span class="badge badge-high">x{issue['count']}</span></div>
                    <div class="issue-message">{issue['message']}</div>
                </div>
"""
        html += """
            </div>
        </div>
"""
    
    if results['issues']['secrets']:
        html += """
        <div class="section">
            <div class="section-header">Potential Secrets Detected</div>
            <div class="section-content">
"""
        for issue in results['issues']['secrets']:
            html += f"""
                <div class="issue-item">
                    <div class="issue-key">{issue['key']}</div>
                    <div class="issue-message">{issue['message']} ({issue.get('file', 'unknown')}, line {issue.get('line', '?')})</div>
                </div>
"""
        html += """
            </div>
        </div>
"""
    
    html += """
        <div class="section">
            <div class="section-header">Files Scanned</div>
            <div class="section-content">
"""
    if results['files']:
        for file_data in results['files']:
            vars_html = ""
            if file_data.get('variables'):
                for var_name in sorted(file_data['variables'].keys()):
                    vars_html += f'<span class="var-tag">{var_name}</span>'
            html += f"""
                <div class="file-item">
                    <div class="file-path">{file_data['path']}</div>
                    <div class="vars-grid">{vars_html}</div>
                </div>
"""
    else:
        html += '<div class="empty-state">No .env files found in the specified directory.</div>'
    
    html += """
            </div>
        </div>
    </div>
</body>
</html>
"""
    
    return html


def main():
    parser = argparse.ArgumentParser(
        description='.env file auditor CLI - Scan for missing vars, stale keys, and duplicates'
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Scan command
    scan_parser = subparsers.add_parser('scan', help='Scan a directory for .env files')
    scan_parser.add_argument('directory', help='Directory to scan')
    scan_parser.add_argument(
        '--config',
        default='config.json',
        help='Path to config.json (default: config.json)'
    )
    scan_parser.add_argument(
        '--output',
        help='Output file for results (JSON)'
    )
    
    # Report command
    report_parser = subparsers.add_parser('report', help='Generate a report from scan results')
    report_parser.add_argument(
        '--format',
        choices=['json', 'html', 'markdown'],
        default='html',
        help='Report format (default: html)'
    )
    report_parser.add_argument(
        '--input',
        help='Input file with scan results (JSON)'
    )
    report_parser.add_argument(
        '--output',
        help='Output file for report'
    )
    
    args = parser.parse_args()
    
    if args.command == 'scan':
        # Load config
        config_path = args.config
        if Path(config_path).exists():
            config = load_config(config_path)
        else:
            print(f"Warning: Config file '{args.config}' not found. Using defaults.", file=sys.stderr)
            config = {
                'required_vars': [],
                'env_file_patterns': ['.env*', '*.env*', '**/.env*'],
                'known_secret_patterns': [
                    r'password',
                    r'secret',
                    r'token',
                    r'api[_-]?key',
                    r'private[_-]?key',
                ]
            }
        
        # Run scan
        results = scan_directory(args.directory, config)
        
        # Output
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"Scan results saved to: {args.output}")
        else:
            print(json.dumps(results, indent=2))
        
        # Exit with error code if issues found
        sys.exit(1 if results['summary']['total_issues'] > 0 else 0)
    
    elif args.command == 'report':
        if not args.input:
            print("Error: --input required for report command", file=sys.stderr)
            sys.exit(1)
        
        with open(args.input, 'r') as f:
            results = json.load(f)
        
        output = ""
        if args.format == 'json':
            output = generate_json_report(results)
        elif args.format == 'html':
            output = generate_html_report(results)
        elif args.format == 'markdown':
            output = generate_markdown_report(results)
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            print(f"Report saved to: {args.output}")
        else:
            print(output)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()