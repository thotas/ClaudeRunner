# Hermes Skills Hub CLI

Browse and search Hermes Agent skills from the command line.

## Installation

```bash
pip install -e .
```

## Commands

### `skills-hub list`
List all available skills, grouped by category.

```bash
skills-hub list                      # List all skills
skills-hub list --category mlops     # Filter by category
skills-hub list --json              # JSON output
```

### `skills-hub search <query>`
Search skills by name, description, tags, or category.

```bash
skills-hub search github            # Search for github-related skills
skills-hub search "machine learning"
skills-hub search ml --json          # JSON output
```

### `skills-hub view <skill-name>`
View detailed information about a specific skill.

```bash
skills-hub view apple-notes          # View apple-notes skill details
skills-hub view github --json        # JSON output
```

### `skills-hub categories`
List all available categories.

```bash
skills-hub categories
```

### `skills-hub config`
Configure CLI preferences interactively.

```bash
skills-hub config
```

## Configuration

Configuration is stored at `~/.hermes/skills-hub-config.json`.

```json
{
  "categories": { ... },
  "output": {
    "color": "auto",
    "format": "list"
  }
}
```

## Architecture

```
skills_hub/
  __init__.py       # Package init
  parser.py         # SKILL.md parsing and Skill model
  formatter.py      # ANSI-colored output formatting
  cli.py            # CLI entry point
tests/
  test_skills_hub.py
config.json         # Default category config
pyproject.toml      # Package metadata
```
