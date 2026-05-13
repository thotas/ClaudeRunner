"""ANSI-colored output formatter for skills-hub CLI."""
import os
from typing import Optional

# Detect terminal capabilities
FORCE_ANSI = os.environ.get("FORCE_ANSI", "").lower() in ("1", "true")
SUPPORTS_ANSI = FORCE_ANSI or (os.isatty(1) if hasattr(os, "isatty") else False)


# ANSI color codes
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background colors
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"

    # Category colors (deterministic based on category name)
    CATEGORY_COLORS = {
        "apple": BRIGHT_CYAN,
        "browser": BRIGHT_BLUE,
        "creative": BRIGHT_MAGENTA,
        "data-science": BRIGHT_GREEN,
        "devops": BRIGHT_YELLOW,
        "diagramming": BRIGHT_MAGENTA,
        "email": BRIGHT_CYAN,
        "gaming": RED,
        "github": WHITE,
        "homeassistant": BRIGHT_YELLOW,
        "media": BRIGHT_MAGENTA,
        "mlops": BRIGHT_GREEN,
        "note-taking": BRIGHT_CYAN,
        "productivity": BRIGHT_GREEN,
        "red-teaming": BRIGHT_RED,
        "research": BRIGHT_BLUE,
        "security": BRIGHT_RED,
        "smart-home": BRIGHT_YELLOW,
        "social-media": BRIGHT_CYAN,
        "software-development": BRIGHT_GREEN,
        "uncategorized": BRIGHT_BLACK,
    }

    # Fallback: hash category name to a color
    _FALLBACK_COLORS = [BRIGHT_CYAN, BRIGHT_BLUE, BRIGHT_MAGENTA, BRIGHT_GREEN, BRIGHT_YELLOW, BRIGHT_RED]

    @classmethod
    def for_category(cls, category: str) -> str:
        """Return ANSI color code for a category."""
        return cls.CATEGORY_COLORS.get(category.lower(), cls._hash_color(category))

    @classmethod
    def _hash_color(cls, category: str) -> str:
        """Hash category name to a color."""
        idx = sum(ord(c) for c in category) % len(cls._FALLBACK_COLORS)
        return cls._FALLBACK_COLORS[idx]


def ansi(text: str, *codes: str) -> str:
    """Apply ANSI codes to text."""
    if not SUPPORTS_ANSI:
        return text
    return "".join(codes) + text + C.RESET


def bold(text: str) -> str:
    return ansi(text, C.BOLD)


def dim(text: str) -> str:
    return ansi(text, C.DIM)


def category_color(text: str, category: str) -> str:
    """Colorize text by category."""
    color = C.for_category(category)
    return ansi(text, C.BOLD, color) if SUPPORTS_ANSI else text


def skill_line(skill) -> str:
    """Format a skill as a one-line listing."""
    cat_color = C.for_category(skill.category)
    if SUPPORTS_ANSI:
        name_str = ansi(skill.name, C.BOLD, C.WHITE)
        cat_str = ansi(f"[{skill.category}]", cat_color)
        desc_str = ansi(skill.description, C.DIM, C.BRIGHT_BLACK)
        return f"  {name_str}  {cat_str}  — {desc_str}"
    else:
        return f"  {skill.name}  [{skill.category}]  — {skill.description}"


def skill_detail(skill) -> str:
    """Format a skill as a detailed view."""
    lines = []

    # Header
    cat_color = C.for_category(skill.category)
    if SUPPORTS_ANSI:
        lines.append(ansi("─" * 60, C.DIM, C.BRIGHT_BLACK))
        lines.append(f"  {ansi(skill.name, C.BOLD, C.WHITE, C.UNDERLINE)}")
        lines.append(f"  {ansi(f'[{skill.category}]', cat_color)}")
        lines.append(ansi("─" * 60, C.DIM, C.BRIGHT_BLACK))
    else:
        lines.append("─" * 60)
        lines.append(f"  {skill.name}")
        lines.append(f"  [{skill.category}]")
        lines.append("─" * 60)

    # Description
    if skill.description:
        lines.append(f"\n  {skill.description}")

    # Tags
    if skill.tags:
        tags_str = ", ".join(f"[{t}]" for t in skill.tags)
        lines.append(f"\n  Tags: {dim(tags_str)}")

    # Platforms
    if skill.platforms:
        plat_str = ", ".join(skill.platforms)
        lines.append(f"  Platforms: {dim(plat_str)}")

    # Prerequisites
    if skill.prerequisites:
        preqs = skill.prerequisites
        parts = []
        if "commands" in preqs:
            parts.append(f"Commands: {', '.join(preqs['commands'])}")
        if "packages" in preqs:
            parts.append(f"Packages: {', '.join(preqs['packages'])}")
        if parts:
            lines.append(f"\n  Prerequisites: {dim(' | '.join(parts))}")

    # Trigger conditions
    if skill.trigger_conditions:
        lines.append(f"\n  Trigger: {dim(skill.trigger_conditions)}")

    # File path
    if skill.file_path:
        lines.append(f"\n  Path: {dim(str(skill.file_path))}")

    if SUPPORTS_ANSI:
        lines.append(ansi("─" * 60, C.DIM, C.BRIGHT_BLACK))

    return "\n".join(lines)


def summary_line(total: int, shown: int, query: Optional[str] = None) -> str:
    """Format a summary line."""
    suffix = f" matching {bold(query)!r}" if query else ""
    return f"\n  {shown}/{total} skills{suffix}"
