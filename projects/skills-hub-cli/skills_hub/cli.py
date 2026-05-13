"""Command-line interface for Hermes Skills Hub."""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from .parser import discover_skills
from .formatter import skill_line, skill_detail, summary_line, bold, SUPPORTS_ANSI


DEFAULT_SKILLS_DIR = Path.home() / ".hermes" / "skills"
CONFIG_PATH = Path.home() / ".hermes" / "skills-hub-config.json"


def load_config() -> dict:
    """Load user configuration."""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"categories": {}, "output": {"color": "auto", "format": "list"}}


def save_config(config: dict) -> None:
    """Save user configuration."""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
    except OSError:
        pass


def configure_interactive() -> None:
    """Interactively configure the CLI."""
    config = load_config()
    print("Skills Hub CLI Configuration")
    print("=" * 40)

    color_setting = config.get("output", {}).get("color", "auto")
    print(f"Color mode: {bold(color_setting)} (auto/always/never)")
    new_color = input("Color mode (press Enter to keep): ").strip().lower()
    if new_color in ("auto", "always", "never"):
        config.setdefault("output", {})["color"] = new_color
        save_config(config)
        print("Configuration saved.")
    else:
        print("Keeping current setting.")


def list_skills(skills_dir: Path, category: Optional[str] = None,
                json_output: bool = False) -> None:
    """List all available skills."""
    skills = discover_skills(skills_dir)

    if category:
        skills = [s for s in skills if s.category.lower() == category.lower()]

    if json_output:
        output = [
            {"name": s.name, "description": s.description, "category": s.category,
             "tags": s.tags, "platforms": s.platforms}
            for s in skills
        ]
        print(json.dumps(output, indent=2))
        return

    if not skills:
        print("  No skills found.")
        return

    # Group by category
    by_category: dict[str, list] = {}
    for s in skills:
        by_category.setdefault(s.category, []).append(s)

    for cat in sorted(by_category.keys()):
        cat_skills = sorted(by_category[cat], key=lambda s: s.name)
        print(f"\n  {bold(cat.upper())}:")
        for s in cat_skills:
            print(skill_line(s))

    print(summary_line(len(discover_skills(skills_dir)), len(skills)))


def search_skills(skills_dir: Path, query: str, json_output: bool = False) -> None:
    """Search skills by query."""
    if not query:
        print("Error: search query required.", file=sys.stderr)
        sys.exit(1)

    all_skills = discover_skills(skills_dir)
    results = [s for s in all_skills if s.matches_query(query)]

    if json_output:
        output = [
            {"name": s.name, "description": s.description, "category": s.category,
             "tags": s.tags, "platforms": s.platforms, "score": 1.0}
            for s in results
        ]
        print(json.dumps(output, indent=2))
        return

    if not results:
        print(f"  No skills found matching {bold(query)!r}.")
        return

    print(f"  {bold('Search Results')} for {bold(query)!r}:\n")
    for s in results:
        print(skill_line(s))

    print(summary_line(len(all_skills), len(results), query))


def view_skill(skills_dir: Path, skill_name: str, json_output: bool = False) -> None:
    """View detailed information about a specific skill."""
    if not skill_name:
        print("Error: skill name required.", file=sys.stderr)
        sys.exit(1)

    all_skills = discover_skills(skills_dir)
    matches = [s for s in all_skills if s.name.lower() == skill_name.lower()]

    # Try fuzzy match if exact match fails
    if not matches:
        matches = [s for s in all_skills if skill_name.lower() in s.name.lower()]

    if not matches:
        print(f"Error: skill {bold(skill_name)!r} not found.", file=sys.stderr)
        suggestions = [s.name for s in all_skills if skill_name.lower() in s.name.lower()][:5]
        if suggestions:
            print(f"  Did you mean: {', '.join(bold(s) for s in suggestions)}", file=sys.stderr)
        sys.exit(1)

    if len(matches) > 1:
        print(f"  Multiple matches for {bold(skill_name)!r}:")
        for m in matches:
            print(f"    - {bold(m.name)} [{m.category}]")
        return

    skill = matches[0]

    if json_output:
        output = {
            "name": skill.name,
            "description": skill.description,
            "category": skill.category,
            "tags": skill.tags,
            "platforms": skill.platforms,
            "prerequisites": skill.prerequisites,
            "trigger_conditions": skill.trigger_conditions,
            "file_path": str(skill.file_path) if skill.file_path else None,
        }
        print(json.dumps(output, indent=2))
        return

    print(skill_detail(skill))


def get_categories(skills_dir: Path) -> list[str]:
    """Get list of all categories."""
    skills = discover_skills(skills_dir)
    return sorted(set(s.category for s in skills))


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="skills-hub",
        description="Hermes Skills Hub CLI — browse and search Hermes skills",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=DEFAULT_SKILLS_DIR,
        help="Path to skills directory",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable ANSI colors"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # list command
    list_parser = subparsers.add_parser("list", help="List all skills")
    list_parser.add_argument("--category", "-c", help="Filter by category")

    # search command
    search_parser = subparsers.add_parser("search", help="Search skills by query")
    search_parser.add_argument("query", help="Search query")

    # view command
    view_parser = subparsers.add_parser("view", help="View skill details")
    view_parser.add_argument("skill-name", help="Name of the skill to view")

    # categories command
    cat_parser = subparsers.add_parser("categories", help="List all categories")

    # config command
    config_parser = subparsers.add_parser("config", help="Configure settings")

    args = parser.parse_args()

    # Handle --no-color flag
    if args.no_color:
        os.environ["FORCE_ANSI"] = "0"

    skills_dir = args.skills_dir

    if args.command == "list":
        list_skills(skills_dir, category=args.category, json_output=args.json)
    elif args.command == "search":
        search_skills(skills_dir, args.query, json_output=args.json)
    elif args.command == "view":
        # argparse uses 'skill-name' internally but we want 'skill_name'
        skill_name = getattr(args, "skill-name", "") or ""
        view_skill(skills_dir, skill_name, json_output=args.json)
    elif args.command == "categories":
        cats = get_categories(skills_dir)
        print(f"  {len(cats)} categories:\n")
        for c in cats:
            print(f"    - {c}")
    elif args.command == "config":
        configure_interactive()


if __name__ == "__main__":
    main()
