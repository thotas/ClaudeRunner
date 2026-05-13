"""Tests for skills-hub CLI."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from skills_hub.parser import (
    Skill, parse_frontmatter, parse_skill_md,
    extract_trigger_conditions, discover_skills
)
from skills_hub.formatter import (
    C, ansi, bold, category_color, skill_line, skill_detail,
    summary_line, SUPPORTS_ANSI
)
from skills_hub.cli import load_config, save_config, DEFAULT_SKILLS_DIR


# ─────────────────────────────────────────────────────────────────────────────
# Parser Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestParseFrontmatter:
    """Tests for YAML frontmatter parsing."""

    def test_valid_frontmatter(self):
        content = """---
name: test-skill
description: "A test skill"
---
# Test Skill
"""
        data, body = parse_frontmatter(content)
        assert data["name"] == "test-skill"
        assert data["description"] == "A test skill"
        assert "# Test Skill" in body

    def test_frontmatter_with_metadata(self):
        content = """---
name: meta-skill
description: "Skill with metadata"
metadata:
  hermes:
    tags: [tag1, tag2]
    category: testing
---
"""
        data, body = parse_frontmatter(content)
        assert data["name"] == "meta-skill"
        assert data["metadata"]["hermes"]["category"] == "testing"
        assert data["metadata"]["hermes"]["tags"] == ["tag1", "tag2"]

    def test_no_frontmatter(self):
        content = "# Just a title\nSome content"
        data, body = parse_frontmatter(content)
        assert data == {}
        assert body == content

    def test_malformed_frontmatter(self):
        content = """---
name: broken
  invalid: yaml
---
"""
        data, body = parse_frontmatter(content)
        # Should return empty dict and full content on parse failure
        assert body == content


class TestExtractTriggerConditions:
    """Tests for trigger condition extraction."""

    def test_when_to_use_section(self):
        body = """
# My Skill

## When to Use

- User asks about X
- User wants Y
- Doing Z

## Other Section
"""
        result = extract_trigger_conditions(body)
        assert result is not None
        assert "User asks" in result or "|" in result  # conditions joined with |

    def test_trigger_keyword(self):
        body = """
# Trigger

## Trigger Conditions

- Condition A
- Condition B
"""
        result = extract_trigger_conditions(body)
        assert result is not None

    def test_no_conditions(self):
        body = "# Simple Skill\nJust some description."
        result = extract_trigger_conditions(body)
        assert result is None


class TestSkillModel:
    """Tests for Skill model."""

    def test_skill_creation(self):
        skill = Skill(
            name="test-skill",
            description="A test skill",
            category="testing",
            tags=["test", "unit"],
            platforms=["linux", "macos"],
        )
        assert skill.name == "test-skill"
        assert skill.category == "testing"
        assert "test" in skill.tags

    def test_matches_query_name(self):
        skill = Skill(name="github-pr-workflow", description="GitHub PR workflow")
        assert skill.matches_query("github")
        assert skill.matches_query("pr")
        assert not skill.matches_query("nothing")

    def test_matches_query_description(self):
        skill = Skill(name="apple-notes", description="Manage Apple Notes")
        assert skill.matches_query("Apple")
        assert skill.matches_query("notes")

    def test_matches_query_tags(self):
        skill = Skill(name="test", description="desc", tags=["ml", "ai", "learning"])
        assert skill.matches_query("ml")
        assert skill.matches_query("learning")

    def test_matches_query_category(self):
        skill = Skill(name="test", description="desc", category="data-science")
        assert skill.matches_query("data-science")
        assert skill.matches_query("DATA")

    def test_matches_query_case_insensitive(self):
        skill = Skill(name="GitHub", description="GitHub workflow")
        assert skill.matches_query("GITHUB")
        assert skill.matches_query("github")


class TestDiscoverSkills:
    """Tests for skill discovery."""

    def test_discover_skills_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skills = discover_skills(Path(tmpdir))
            assert skills == []

    def test_discover_skills_nonexistent_dir(self):
        skills = discover_skills(Path("/nonexistent/path"))
        assert skills == []

    def test_discover_skills_with_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "test-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: discovered-skill
description: "A discovered skill"
---
# Discovered Skill
""")
            skills = discover_skills(Path(tmpdir))
            assert len(skills) == 1
            assert skills[0].name == "discovered-skill"

    def test_discover_skills_multiple(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(5):
                skill_dir = Path(tmpdir) / f"skill-{i}"
                skill_dir.mkdir()
                (skill_dir / "SKILL.md").write_text(f"""---
name: skill-{i}
description: "Skill number {i}"
---
# Skill {i}
""")
            skills = discover_skills(Path(tmpdir))
            assert len(skills) == 5

    def test_discover_skills_nested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Top-level skill
            top_dir = Path(tmpdir) / "top-skill"
            top_dir.mkdir()
            (top_dir / "SKILL.md").write_text("""---
name: top-skill
description: "Top level"
---
""")
            # Nested skill
            nested_dir = Path(tmpdir) / "category" / "nested-skill"
            nested_dir.mkdir(parents=True)
            (nested_dir / "SKILL.md").write_text("""---
name: nested-skill
description: "Nested"
---
""")
            skills = discover_skills(Path(tmpdir))
            assert len(skills) == 2
            names = {s.name for s in skills}
            assert "top-skill" in names
            assert "nested-skill" in names


# ─────────────────────────────────────────────────────────────────────────────
# Formatter Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAnsiFormatting:
    """Tests for ANSI formatting."""

    def test_ansi_bold(self):
        result = bold("hello")
        if SUPPORTS_ANSI:
            assert "\033[1m" in result
            assert "hello" in result
            assert "\033[0m" in result
        else:
            assert result == "hello"

    def test_category_color_known(self):
        result = category_color("text", "github")
        # Should not raise

    def test_category_color_unknown(self):
        result = category_color("text", "unknown-category")
        # Should not raise (uses fallback)

    def test_ansi_reset(self):
        assert C.RESET == "\033[0m"

    def test_ansi_bold_code(self):
        assert C.BOLD == "\033[1m"


class TestSkillLine:
    """Tests for single-line skill formatting."""

    def test_skill_line_basic(self):
        skill = Skill(name="test-skill", description="A test skill", category="testing")
        line = skill_line(skill)
        assert "test-skill" in line
        assert "testing" in line

    def test_skill_line_with_tags(self):
        skill = Skill(name="github", description="GitHub workflow", category="github",
                      tags=["git", "workflow"])
        line = skill_line(skill)
        assert "github" in line


class TestSkillDetail:
    """Tests for detailed skill formatting."""

    def test_skill_detail_basic(self):
        skill = Skill(name="test-skill", description="A test skill", category="testing")
        detail = skill_detail(skill)
        assert "test-skill" in detail
        assert "testing" in detail
        assert "A test skill" in detail

    def test_skill_detail_with_tags(self):
        skill = Skill(name="ml-skill", description="ML skill", category="mlops",
                      tags=["ml", "ai"])
        detail = skill_detail(skill)
        assert "ml" in detail
        assert "ai" in detail

    def test_skill_detail_with_platforms(self):
        skill = Skill(name="cross-skill", description="Cross-platform", category="dev",
                      platforms=["linux", "macos", "windows"])
        detail = skill_detail(skill)
        assert "linux" in detail
        assert "macos" in detail

    def test_skill_detail_with_prerequisites(self):
        skill = Skill(name="req-skill", description="With prerequisites", category="test",
                      prerequisites={"commands": ["git", "python"]})
        detail = skill_detail(skill)
        assert "git" in detail
        assert "python" in detail

    def test_skill_detail_with_trigger(self):
        skill = Skill(name="trigger-skill", description="With triggers", category="test",
                      trigger_conditions="User asks about X | User wants Y")
        detail = skill_detail(skill)
        assert "Trigger" in detail


class TestSummaryLine:
    """Tests for summary line formatting."""

    def test_summary_without_query(self):
        result = summary_line(10, 10)
        assert "10/10" in result
        assert "skills" in result

    def test_summary_with_query(self):
        result = summary_line(100, 5, "github")
        assert "5/100" in result
        assert "github" in result


# ─────────────────────────────────────────────────────────────────────────────
# CLI / Config Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestConfig:
    """Tests for configuration management."""

    def test_load_config_nonexistent(self):
        # Should not raise, returns default
        config = load_config()
        assert "output" in config or config == {}

    def test_save_and_load_config(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            # Patch CONFIG_PATH temporarily
            import skills_hub.cli
            original = skills_hub.cli.CONFIG_PATH
            skills_hub.cli.CONFIG_PATH = tmp_path

            test_config = {"output": {"color": "always"}, "categories": {"test": {}}}
            save_config(test_config)
            loaded = load_config()

            assert loaded["output"]["color"] == "always"

            skills_hub.cli.CONFIG_PATH = original
        finally:
            tmp_path.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Integration-style Tests (no actual skills dir needed)
# ─────────────────────────────────────────────────────────────────────────────

class TestSkillEdgeCases:
    """Edge case tests for Skill model."""

    def test_skill_empty_description(self):
        skill = Skill(name="empty", description="", category="test")
        assert skill.description == ""
        assert skill.matches_query("empty")

    def test_skill_no_tags(self):
        skill = Skill(name="no-tags", description="desc")
        assert skill.tags == []
        assert not skill.matches_query("anything")

    def test_skill_no_platforms(self):
        skill = Skill(name="no-plat", description="desc")
        assert skill.platforms == []

    def test_skill_no_prerequisites(self):
        skill = Skill(name="no-prereq", description="desc")
        assert skill.prerequisites == {}

    def test_skill_no_trigger(self):
        skill = Skill(name="no-trigger", description="desc")
        assert skill.trigger_conditions is None

    def test_skill_repr(self):
        skill = Skill(name="repr-test", description="desc", category="test")
        r = repr(skill)
        assert "repr-test" in r
        assert "test" in r


class TestCategoryColorDeterminism:
    """Tests that category colors are deterministic."""

    def test_same_category_same_color(self):
        c1 = C.for_category("github")
        c2 = C.for_category("github")
        assert c1 == c2

    def test_different_categories_may_differ(self):
        # Not a guarantee, but should be deterministic
        colors = [C.for_category(f"cat{i}") for i in range(10)]
        # All should be valid ANSI codes
        for color in colors:
            assert color.startswith("\033[")


# ─────────────────────────────────────────────────────────────────────────────
# Test discover_skills on actual skills directory (if exists)
# ─────────────────────────────────────────────────────────────────────────────

class TestRealSkillsDirectory:
    """Tests against the real ~/.hermes/skills directory."""

    @pytest.fixture
    def real_skills_dir(self):
        return Path.home() / ".hermes" / "skills"

    def test_real_skills_dir_exists(self, real_skills_dir):
        assert real_skills_dir.exists(), "~/.hermes/skills should exist"

    def test_discover_real_skills_finds_some(self, real_skills_dir):
        skills = discover_skills(real_skills_dir)
        assert len(skills) > 0, "Should find at least some skills"

    def test_real_skills_have_names(self, real_skills_dir):
        skills = discover_skills(real_skills_dir)
        for skill in skills:
            assert skill.name, "Each skill should have a name"

    def test_real_skills_have_categories(self, real_skills_dir):
        skills = discover_skills(real_skills_dir)
        for skill in skills:
            assert skill.category, "Each skill should have a category"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
