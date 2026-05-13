#!/usr/bin/env python3
"""
Tests for cron watchdog.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the module
sys.path.insert(0, str(Path(__file__).parent))
import watchdog


class TestLoadConfig:
    """Tests for configuration loading."""

    def test_load_default_config(self):
        """Test loading default configuration."""
        # Create a fake path that doesn't exist
        fake_config_path = "/fake/nonexistent/path/config.json"

        with patch.object(watchdog, "Path") as mock_path_cls:
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = False
            mock_path_cls.return_value = mock_path_instance

            config = watchdog.load_config(fake_config_path)

            assert config["alert_cooldown_minutes"] == 60
            assert config["watch_patterns"] == ["*.json"]

    def test_load_custom_config(self):
        """Test loading custom configuration from file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "output_dir": "/custom/output/",
                "alert_cooldown_minutes": 30,
                "watch_patterns": ["*.json", "*.out"]
            }, f)
            f.flush()

            config = watchdog.load_config(f.name)
            os.unlink(f.name)

            assert config["output_dir"] == "/custom/output/"
            assert config["alert_cooldown_minutes"] == 30
            assert config["watch_patterns"] == ["*.json", "*.out"]


class TestParseOutputFile:
    """Tests for output file parsing."""

    def test_parse_successful_job(self):
        """Test parsing a successful job output."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "job_name": "test_job",
                "exit_code": 0,
                "timestamp": "2026-05-13T10:00:00"
            }, f)
            f.flush()

            result = watchdog.parse_output_file(f.name)
            os.unlink(f.name)

            assert result["job_name"] == "test_job"
            assert result["exit_code"] == 0
            assert result["error_summary"] == ""

    def test_parse_failed_job_with_error(self):
        """Test parsing a failed job with error message."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "job_name": "failing_job",
                "exit_code": 1,
                "error": "Command not found",
                "timestamp": "2026-05-13T10:00:00"
            }, f)
            f.flush()

            result = watchdog.parse_output_file(f.name)
            os.unlink(f.name)

            assert result["job_name"] == "failing_job"
            assert result["exit_code"] == 1
            assert result["error_summary"] == "Command not found"

    def test_parse_failed_job_with_exit_status(self):
        """Test parsing job using exit_status field."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "job_name": "status_job",
                "exit_status": 127,
                "timestamp": "2026-05-13T10:00:00"
            }, f)
            f.flush()

            result = watchdog.parse_output_file(f.name)
            os.unlink(f.name)

            assert result["job_name"] == "status_job"
            assert result["exit_code"] == 127

    def test_parse_failed_job_no_error_field(self):
        """Test parsing failed job without explicit error field."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "job_name": "silent_fail",
                "exit_code": 2
            }, f)
            f.flush()

            result = watchdog.parse_output_file(f.name)
            os.unlink(f.name)

            assert result["exit_code"] == 2
            assert "exited with code 2" in result["error_summary"]

    def test_parse_malformed_json(self):
        """Test parsing malformed JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            f.flush()

            result = watchdog.parse_output_file(f.name)
            os.unlink(f.name)

            assert result["exit_code"] == -1
            assert "Failed to parse" in result["error_summary"]

    def test_parse_long_error_message(self):
        """Test that long error messages are truncated."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "job_name": "long_error_job",
                "exit_code": 1,
                "error": "A" * 500  # Very long error
            }, f)
            f.flush()

            result = watchdog.parse_output_file(f.name)
            os.unlink(f.name)

            assert len(result["error_summary"]) == 200


class TestShouldAlert:
    """Tests for alert throttling."""

    def test_first_failure_should_alert(self):
        """Test that first failure for a job triggers alert."""
        last_alerts = {}
        assert watchdog.should_alert("new_job", last_alerts, 60) is True

    def test_recent_alert_blocked(self):
        """Test that recent alert is blocked by cooldown."""
        last_alerts = {"recent_job": datetime.now().isoformat()}
        assert watchdog.should_alert("recent_job", last_alerts, 60) is False

    def test_old_alert_allows_new(self):
        """Test that old alert allows new alert."""
        old_time = (datetime.now() - timedelta(minutes=120)).isoformat()
        last_alerts = {"old_job": old_time}
        assert watchdog.should_alert("old_job", last_alerts, 60) is True

    def test_exactly_cooldown_boundary(self):
        """Test exactly at cooldown boundary."""
        # 61 minutes ago should be allowed with 60 min cooldown
        boundary_time = (datetime.now() - timedelta(minutes=61)).isoformat()
        last_alerts = {"boundary_job": boundary_time}
        assert watchdog.should_alert("boundary_job", last_alerts, 60) is True


class TestTelegramAlert:
    """Tests for Telegram alert sending."""

    @patch("watchdog.requests.post")
    def test_send_alert_success(self, mock_post):
        """Test successful alert sending."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = watchdog.send_telegram_alert(
            "test_token",
            "7192357563",
            "failing_job",
            "Command failed",
            "2026-05-13T10:00:00"
        )

        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args.kwargs["json"]["chat_id"] == "7192357563"
        assert "failing_job" in call_args.kwargs["json"]["text"]

    @patch("watchdog.requests.post")
    def test_send_alert_failure(self, mock_post):
        """Test failed alert sending."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = watchdog.send_telegram_alert(
            "test_token",
            "7192357563",
            "failing_job",
            "Command failed",
            "2026-05-13T10:00:00"
        )

        assert result is False

    @patch("watchdog.requests.post")
    def test_send_alert_network_error(self, mock_post):
        """Test alert sending with network error."""
        import requests
        mock_post.side_effect = requests.RequestException("Network error")

        result = watchdog.send_telegram_alert(
            "test_token",
            "7192357563",
            "failing_job",
            "Command failed",
            "2026-05-13T10:00:00"
        )

        assert result is False


class TestAlertThrottling:
    """Integration tests for alert throttling behavior."""

    def test_throttle_multiple_failures_same_job(self):
        """Test that multiple failures within cooldown only send one alert."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two output files for same job
            job_output_1 = os.path.join(tmpdir, "job1_1.json")
            job_output_2 = os.path.join(tmpdir, "job1_2.json")

            with open(job_output_1, "w") as f:
                json.dump({"job_name": "throttled_job", "exit_code": 1, "error": "Error 1"}, f)

            with open(job_output_2, "w") as f:
                json.dump({"job_name": "throttled_job", "exit_code": 1, "error": "Error 2"}, f)

            # Mock state file and Telegram
            state_file = os.path.join(tmpdir, "state.json")

            with patch.object(watchdog, "Path") as mock_path:
                mock_path.return_value = Path(state_file)

                # Load initial state (no previous alerts)
                last_alerts = {}

                # First failure should alert
                assert watchdog.should_alert("throttled_job", last_alerts, 60) is True

                # After alerting, update state
                last_alerts["throttled_job"] = datetime.now().isoformat()

                # Second failure should NOT alert (within cooldown)
                assert watchdog.should_alert("throttled_job", last_alerts, 60) is False

    def test_allow_alert_after_cooldown(self):
        """Test that alerts are allowed after cooldown expires."""
        old_time = (datetime.now() - timedelta(minutes=61)).isoformat()
        last_alerts = {"cooldown_job": old_time}

        # Should allow new alert after cooldown
        assert watchdog.should_alert("cooldown_job", last_alerts, 60) is True


class TestFindOutputFiles:
    """Tests for finding output files."""

    def test_find_json_files(self):
        """Test finding JSON files in directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some test files
            open(os.path.join(tmpdir, "job1.json"), "w").close()
            open(os.path.join(tmpdir, "job2.json"), "w").close()
            open(os.path.join(tmpdir, "other.txt"), "w").close()

            files = watchdog.find_output_files(tmpdir, ["*.json"])

            assert len(files) == 2
            assert all(f.endswith(".json") for f in files)

    def test_find_no_matching_files(self):
        """Test when no files match patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = watchdog.find_output_files(tmpdir, ["*.json"])
            assert len(files) == 0

    def test_find_multiple_patterns(self):
        """Test finding files with multiple patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "job1.json"), "w").close()
            open(os.path.join(tmpdir, "job2.out"), "w").close()

            files = watchdog.find_output_files(tmpdir, ["*.json", "*.out"])

            assert len(files) == 2


class TestStatePersistence:
    """Tests for state file persistence."""

    def test_save_and_load_last_alerts(self):
        """Test saving and loading last alert timestamps."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

        try:
            test_alerts = {
                "job1": "2026-05-13T10:00:00",
                "job2": "2026-05-13T11:00:00"
            }

            watchdog.save_last_alerts(temp_path, test_alerts)
            loaded = watchdog.load_last_alerts(temp_path)

            assert loaded == test_alerts
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_load_empty_state(self):
        """Test loading when state file doesn't exist."""
        loaded = watchdog.load_last_alerts("/nonexistent/path/state.json")
        assert loaded == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
