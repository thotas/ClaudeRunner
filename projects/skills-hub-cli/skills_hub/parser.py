"""Parse SKILL.md YAML frontmatter and markdown content."""
import re
from pathlib import Path
from typing import Optional
import yaml


class Skill:
    """Represents a parsed Hermes skill."""

    def __init__(self, name: str, description: str, category: str = "uncategorized",
                 trigger_conditions: Optional[str] = None, file_path: Optional[Path] = None,
                 tags: Optional[list] = None, platforms: Optional[list] = None,
                 prerequisites: Optional[dict] = None):
        self.name = name
        self.description = description
        self.category = category
        self.trigger_conditions = trigger_conditions
        self.file_path = file_path
        self.tags = tags or []
        self.platforms = platforms or []
        self.prerequisites = prerequisites or {}

    def matches_query(self, query: str) -> bool:
        """Check if skill matches a search query."""
        q = query.lower()
        return (
            q in self.name.lower()
            or q in self.description.lower()
            or any(q in tag.lower() for tag in self.tags)
            or q in self.category.lower()
            or (bool(self.trigger_conditions) and q in self.trigger_conditions.lower())
        )

    def __repr__(self):
        return f"Skill(name={self.name!r}, category={self.category!r})"


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from SKILL.md content."""
    match = re.match(r'^---\n(.*?)\n---\n(.*)$', content, re.DOTALL)
    if match:
        try:
            data = yaml.safe_load(match.group(1)) or {}
            body = match.group(2)
            return data, body
        except yaml.YAMLError:
            pass
    return {}, content


def parse_skill_md(file_path: Path) -> Optional[Skill]:
    """Parse a SKILL.md file and return a Skill object."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None

    data, body = parse_frontmatter(content)

    name = (
        data.get("name")
        or (file_path.parent.name if file_path.parent.name != "skills" else "unknown")
    )
    description = data.get("description", "")

    # Extract category from metadata or directory
    metadata = data.get("metadata", {})
    hermes_meta = metadata.get("hermes", {}) if isinstance(metadata, dict) else {}
    category = hermes_meta.get("category") or data.get("category") or "uncategorized"
    tags = hermes_meta.get("tags", []) if isinstance(hermes_meta, dict) else data.get("tags", [])
    platforms = data.get("platforms", [])
    prerequisites = data.get("prerequisites", {})

    # Extract trigger conditions from body
    trigger_conditions = extract_trigger_conditions(body)

    return Skill(
        name=name,
        description=description,
        category=category,
        trigger_conditions=trigger_conditions,
        file_path=file_path,
        tags=tags,
        platforms=platforms,
        prerequisites=prerequisites,
    )


def extract_trigger_conditions(body: str) -> Optional[str]:
    """Extract when-to-use / trigger conditions from markdown body."""
    lines = body.split("\n")
    collecting = False
    conditions = []

    for line in lines:
        stripped = line.strip().lower()
        if any(kw in stripped for kw in ["when to use", "trigger", "conditions", "use when"]):
            collecting = True
            # Skip the header line itself
            if stripped.endswith(":"):
                continue
        elif collecting:
            if line.startswith("#") or (stripped and not line.startswith("-") and not stripped.startswith("*")):
                # Hit next section
                break
            if stripped:
                conditions.append(line.strip().lstrip("-* ").strip())

    return " | ".join(conditions[:3]) if conditions else None


def discover_skills(skills_dir: Path) -> list[Skill]:
    """Discover all skills under a directory."""
    skills = []
    if not skills_dir.exists():
        return skills

    for skill_md in skills_dir.rglob("SKILL.md"):
        skill = parse_skill_md(skill_md)
        if skill and skill.name:
            skills.append(skill)

    return skills
