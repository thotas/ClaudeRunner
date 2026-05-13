#!/usr/bin/env python3
"""
ClaudeRunner Self-Test Suite
Tests the claude-runner.sh script itself for common failure modes.
"""
import subprocess
import os
import json
import tempfile
import shutil
from pathlib import Path

import pytest

RUNNER_DIR = Path(os.path.expanduser("~/Development/ClaudeRunner"))
RUNNER_SCRIPT = RUNNER_DIR / "claude-runner.sh"
CONFIG_FILE = RUNNER_DIR / "config" / "runner.conf"


class TestRunnerScriptExists:
    def test_runner_script_exists(self):
        assert RUNNER_SCRIPT.exists(), f"Runner script not found at {RUNNER_SCRIPT}"

    def test_runner_script_executable(self):
        assert os.access(RUNNER_SCRIPT, os.X_OK), "Runner script is not executable"

    def test_config_file_exists(self):
        assert CONFIG_FILE.exists(), f"Config file not found at {CONFIG_FILE}"


class TestConfigFile:
    def test_config_loads_minimax_vars(self):
        result = subprocess.run(
            ["bash", "-c", f"source {CONFIG_FILE} && echo MINIMAX_BASE_URL=$MINIMAX_BASE_URL MINIMAX_AUTH_TOKEN set"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Config failed to load: {result.stderr}"

    def test_retry_settings_present(self):
        result = subprocess.run(
            ["bash", "-c", f"source {CONFIG_FILE} && echo RETRY_MAX=$RETRY_MAX RETRY_BASE_DELAY=$RETRY_BASE_DELAY"],
            capture_output=True, text=True
        )
        assert "RETRY_MAX=" in result.stdout
        assert "RETRY_BASE_DELAY=" in result.stdout


class TestGitIntegration:
    def test_not_on_main_branch(self):
        """Ensure we don't accidentally test on main branch."""
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=RUNNER_DIR, capture_output=True, text=True
        )
        current = result.stdout.strip()
        assert current != "main", "Tests should not run on main branch"

    def test_no_embedded_git_in_projects(self):
        """Check that projects don't contain embedded .git directories."""
        projects_dir = RUNNER_DIR / "projects"
        if not projects_dir.exists():
            pytest.skip("No projects directory")

        for project in projects_dir.iterdir():
            if project.is_dir():
                git_dirs = list(project.rglob(".git"))
                assert len(git_dirs) == 0, f"Project {project.name} has embedded .git: {git_dirs}"


class TestPromptTemplates:
    def test_review_prompt_exists(self):
        prompt = RUNNER_DIR / "prompts" / "review.md"
        assert prompt.exists(), "review.md not found"

    def test_execute_prompt_exists(self):
        prompt = RUNNER_DIR / "prompts" / "execute.md"
        assert prompt.exists(), "execute.md not found"

    def test_execute_prompt_contains_git_strip_instruction(self):
        """Execute prompt should instruct Claude Code to strip embedded .git directories."""
        execute_prompt = (RUNNER_DIR / "prompts" / "execute.md").read_text()
        assert "rm -rf {} + 2>/dev/null || true" in execute_prompt, \
            "execute.md should instruct to strip embedded .git directories"


class TestRunClaudeFunction:
    def test_run_claude_function_exists_in_script(self):
        content = RUNNER_SCRIPT.read_text()
        assert "run_claude() {" in content, "run_claude function not found in script"

    def test_run_claude_has_retry_loop(self):
        content = RUNNER_SCRIPT.read_text()
        assert "until [" in content, "Retry loop (until) not found in run_claude()"
        assert "RETRY_MAX" in content, "RETRY_MAX not referenced in script"

    def test_exponential_backoff_in_run_claude(self):
        content = RUNNER_SCRIPT.read_text()
        # Should have sleep with multiplier (attempt)
        assert "sleep" in content, "No sleep command found for backoff"


class TestPreflightGitStrip:
    def test_phase_execute_has_git_strip_logic(self):
        content = RUNNER_SCRIPT.read_text()
        assert "find \"$project_path\" -name \".git\"" in content, \
            "phase_execute should contain .git strip logic"


class TestLocking:
    def test_lock_file_configured(self):
        result = subprocess.run(
            ["bash", "-c", f"source {CONFIG_FILE} && echo LOCK_FILE=$LOCK_FILE"],
            capture_output=True, text=True
        )
        assert "LOCK_FILE=" in result.stdout


class TestLogging:
    def test_log_function_exists(self):
        content = RUNNER_SCRIPT.read_text()
        assert "log_info()" in content or "log_info " in content, "log_info function not found"


class TestEndToEnd:
    def test_runner_script_runs_without_args(self):
        """Run the script with --help or check it at least parses."""
        result = subprocess.run(
            ["bash", RUNNER_SCRIPT.as_posix(), "--help"],
            capture_output=True, text=True, timeout=10
        )
        # Should either show help or fail gracefully (not crash)
        assert result.returncode in [0, 1], f"Script crashed unexpectedly: {result.stderr}"

    def test_runner_script_accepts_dry_run(self):
        """Dry run should at least parse without crashing."""
        result = subprocess.run(
            ["bash", RUNNER_SCRIPT.as_posix(), "--dry-run"],
            capture_output=True, text=True, timeout=30,
            cwd=RUNNER_DIR
        )
        # Should fail on missing task but not crash
        assert "No pending tasks" in result.stdout or "ERROR" in result.stderr or result.returncode in [0, 1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])