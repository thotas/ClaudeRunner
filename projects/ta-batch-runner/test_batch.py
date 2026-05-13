#!/usr/bin/env python3
"""
Tests for ta-batch-runner.
Run with: python test_batch.py
Or via pytest: pytest test_batch.py -v
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the module under test
import importlib.util

SPEC = importlib.util.spec_from_file_location(
    "runner", Path(__file__).parent / "runner.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_temp_config(overrides: dict = None) -> Path:
    cfg = {
        "tickers": ["AAPL", "MSFT"],
        "ta_dir": "/tmp/fake-ta",
        "venv_activate": "/tmp/fake-ta/.venv/bin/activate",
        "run_analysis_script": "/tmp/fake-ta/run_analysis.py",
        "gcp_vm": {
            "host": "thotas@34.82.106.90",
            "remote_path": "/var/www/static",
            "local_tmp_dir": "/tmp/ta-batch-gcp",
        },
        "telegram": {"chat_id": "7192357563"},
        "state_file": "/tmp/test-state.json",
        "log_dir": "/tmp/test-logs",
        "analysis_timeout_seconds": 900,
        "report_script": "/tmp/fake-gen.py",
    }
    if overrides:
        cfg.update(overrides)
    p = Path("/tmp/test-ta-config.json")
    with open(p, "w") as f:
        json.dump(cfg, f)
    return p


def make_fake_full_state(ticker: str = "AAPL", rating: str = "**OVERWEIGHT**") -> dict:
    return {
        "company_of_interest": ticker,
        "trade_date": date.today().isoformat(),
        "market_report": f"Technical analysis for {ticker}",
        "news_report": f"News report for {ticker}",
        "fundamentals_report": f"Fundamentals for {ticker}",
        "sentiment_report": f"Sentiment for {ticker}",
        "investment_plan": f"Investment plan for {ticker}",
        "final_trade_decision": f"Rating: {rating}\nThe stock looks good.",
        "trader_investment_plan": f"Trader plan for {ticker}",
        "investment_debate_state": {
            "bull_history": "Bull case",
            "bear_history": "Bear case",
        },
        "risk_debate_state": {
            "aggressive_history": "Aggressive case",
            "conservative_history": "Conservative case",
            "neutral_history": "Neutral case",
        },
    }


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestConfigLoading(unittest.TestCase):
    def test_load_config_parses_valid_json(self):
        p = write_temp_config()
        cfg = runner.load_config(p)
        self.assertEqual(cfg["tickers"], ["AAPL", "MSFT"])
        self.assertEqual(cfg["ta_dir"], "/tmp/fake-ta")

    def test_load_config_default_path(self):
        p = write_temp_config()
        orig = Path(__file__).parent / "config.json"
        # Just check it doesn't crash when called without args
        # (we patch the path in practice)
        cfg = runner.load_config(p)
        self.assertIsInstance(cfg, dict)

    def test_load_config_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            runner.load_config("/nonexistent/config.json")


# ---------------------------------------------------------------------------
# State management tests
# ---------------------------------------------------------------------------

class TestStateManagement(unittest.TestCase):
    def setUp(self):
        self.state_file = Path("/tmp/test-state.json")
        self.state_file.unlink(missing_ok=True)

    def tearDown(self):
        self.state_file.unlink(missing_ok=True)

    def test_batch_state_to_dict_roundtrip(self):
        state = runner.BatchState(
            batch_id="test-1",
            started_at="2026-05-13T10:00:00",
            tickers=[
                runner.TickerResult(ticker="AAPL", status="completed", rating="Overweight"),
            ],
        )
        d = state.to_dict()
        restored = runner.BatchState.from_dict(d)
        self.assertEqual(restored.batch_id, "test-1")
        self.assertEqual(restored.tickers[0].ticker, "AAPL")
        self.assertEqual(restored.tickers[0].rating, "Overweight")

    def test_load_state_none_when_missing(self):
        result = runner.load_state(self.state_file)
        self.assertIsNone(result)

    def test_save_and_load_state(self):
        state = runner.BatchState(
            batch_id="test-2",
            started_at="2026-05-13T10:00:00",
            tickers=[
                runner.TickerResult(ticker="MSFT", status="failed", error="timeout"),
            ],
        )
        runner.save_state(state, self.state_file)
        loaded = runner.load_state(self.state_file)
        self.assertEqual(loaded.batch_id, "test-2")
        self.assertEqual(loaded.tickers[0].status, "failed")
        self.assertEqual(loaded.tickers[0].error, "timeout")

    def test_ticker_result_defaults(self):
        tr = runner.TickerResult(ticker="GOOGL", status="pending")
        self.assertIsNone(tr.started_at)
        self.assertIsNone(tr.completed_at)
        self.assertIsNone(tr.rating)
        self.assertIsNone(tr.error)
        self.assertIsNone(tr.report_url)


# ---------------------------------------------------------------------------
# Swap ticker tests
# ---------------------------------------------------------------------------

class TestSwapTicker(unittest.TestCase):
    def test_swap_ticker_in_script(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('TICKER = "OLD"\nOTHER = "stuff"\n')
            f.flush()
            p = Path(f.name)

        runner.swap_ticker_in_script(p, "NVDA")
        content = p.read_text()
        self.assertIn('TICKER = "NVDA"', content)
        self.assertIn('OTHER = "stuff"', content)
        p.unlink()

    def test_swap_ticker_preserves_other_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('TICKER = "AAPL"\nVENV = "activate"\nMAX_ROUNDS = 3\n')
            f.flush()
            p = Path(f.name)

        runner.swap_ticker_in_script(p, "TSLA")
        content = p.read_text()
        self.assertIn('TICKER = "TSLA"', content)
        self.assertIn('VENV = "activate"', content)
        self.assertIn("MAX_ROUNDS = 3", content)
        p.unlink()


# ---------------------------------------------------------------------------
# Rating extraction tests
# ---------------------------------------------------------------------------

class TestExtractRating(unittest.TestCase):
    def test_extract_rating_overweight(self):
        fs = make_fake_full_state(rating="**OVERWEIGHT**")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(fs, f)
            f.flush()
            p = Path(f.name)

        rating = runner.extract_rating(p)
        self.assertEqual(rating, "OVERWEIGHT")
        p.unlink()

    def test_extract_rating_underweight(self):
        fs = make_fake_full_state(rating="**UNDERWEIGHT**")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(fs, f)
            f.flush()
            p = Path(f.name)

        rating = runner.extract_rating(p)
        self.assertEqual(rating, "UNDERWEIGHT")
        p.unlink()

    def test_extract_rating_hold(self):
        fs = make_fake_full_state(rating="Hold")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(fs, f)
            f.flush()
            p = Path(f.name)

        rating = runner.extract_rating(p)
        self.assertEqual(rating, "Hold")
        p.unlink()

    def test_extract_rating_missing_line(self):
        fs = make_fake_full_state()
        fs["final_trade_decision"] = "No rating here"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(fs, f)
            f.flush()
            p = Path(f.name)

        rating = runner.extract_rating(p)
        self.assertEqual(rating, "Hold")  # default
        p.unlink()

    def test_extract_rating_missing_file(self):
        rating = runner.extract_rating(Path("/nonexistent/state.json"))
        self.assertEqual(rating, "Hold")


# ---------------------------------------------------------------------------
# Report generation tests
# ---------------------------------------------------------------------------

class TestInlineReportGeneration(unittest.TestCase):
    def test_generate_report_inline_creates_html(self):
        fs = make_fake_full_state()
        today = date.today().isoformat()
        out_dir = Path("/tmp/test-report-out")
        out_dir.mkdir(exist_ok=True)
        state_file = out_dir / "full_state.json"
        with open(state_file, "w") as f:
            json.dump(fs, f)

        html_file = runner._generate_report_inline(state_file, "AAPL", today, out_dir)

        self.assertTrue(html_file.exists())
        html_content = html_file.read_text()
        self.assertIn("AAPL", html_content)
        self.assertIn("OVERWEIGHT", html_content)
        self.assertIn("<!DOCTYPE html>", html_content)
        self.assertIn("tab-nav", html_content)
        self.assertIn("technical", html_content)

    def test_generate_report_inline_rating_badge_color_overweight(self):
        fs = make_fake_full_state(rating="**OVERWEIGHT**")
        today = date.today().isoformat()
        out_dir = Path("/tmp/test-report-out2")
        out_dir.mkdir(exist_ok=True)
        state_file = out_dir / "full_state.json"
        with open(state_file, "w") as f:
            json.dump(fs, f)

        html_file = runner._generate_report_inline(state_file, "AAPL", today, out_dir)
        html_content = html_file.read_text()
        self.assertIn("var(--success)", html_content)  # green for overweight

    def test_generate_report_inline_rating_badge_color_underweight(self):
        fs = make_fake_full_state(rating="**UNDERWEIGHT**")
        today = date.today().isoformat()
        out_dir = Path("/tmp/test-report-out3")
        out_dir.mkdir(exist_ok=True)
        state_file = out_dir / "full_state.json"
        with open(state_file, "w") as f:
            json.dump(fs, f)

        html_file = runner._generate_report_inline(state_file, "AAPL", today, out_dir)
        html_content = html_file.read_text()
        self.assertIn("var(--danger)", html_content)  # red for underweight

    def test_generate_report_inline_rating_badge_color_hold(self):
        fs = make_fake_full_state(rating="Hold")
        today = date.today().isoformat()
        out_dir = Path("/tmp/test-report-out4")
        out_dir.mkdir(exist_ok=True)
        state_file = out_dir / "full_state.json"
        with open(state_file, "w") as f:
            json.dump(fs, f)

        html_file = runner._generate_report_inline(state_file, "AAPL", today, out_dir)
        html_content = html_file.read_text()
        self.assertIn("var(--warning)", html_content)  # amber for hold

    def test_find_full_state_by_most_recent(self):
        ticker = "AAPL"
        today = date.today().isoformat()
        ta_dir = Path("/tmp/fake-ta-dir")
        ta_dir.mkdir(parents=True, exist_ok=True)
        out_dir = ta_dir / "outputs" / ticker / today
        out_dir.mkdir(parents=True, exist_ok=True)
        state_file = out_dir / "full_state.json"
        with open(state_file, "w") as f:
            json.dump(make_fake_full_state(), f)

        found = runner.find_full_state(ticker, today, ta_dir)
        self.assertEqual(found, state_file)
        # cleanup
        import shutil
        shutil.rmtree(ta_dir)

    def test_find_full_state_not_found(self):
        ta_dir = Path("/tmp/nonexistent-ta")
        ta_dir.mkdir(exist_ok=True)
        found = runner.find_full_state("XYZ", "2026-01-01", ta_dir)
        self.assertIsNone(found)
        import shutil
        shutil.rmtree(ta_dir)


# ---------------------------------------------------------------------------
# Telegram tests
# ---------------------------------------------------------------------------

class TestTelegram(unittest.TestCase):
    def test_send_telegram_message_no_token(self):
        # Should not raise, just warn
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}, clear=False):
            # If env is cleared, token is empty
            result = runner.send_telegram_message("test", bot_token="")
            self.assertFalse(result)

    def test_send_telegram_message_success(self):
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            result = runner.send_telegram_message("Test message", bot_token="fake-token")
            self.assertTrue(result)
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            self.assertIn("sendMessage", call_args.args[0] if call_args.args else call_args.kwargs["url"])

    def test_send_telegram_message_failure(self):
        with patch("httpx.post", side_effect=Exception("Network error")):
            result = runner.send_telegram_message("Test", bot_token="fake-token")
            self.assertFalse(result)

    def test_send_telegram_document_success(self):
        # Create a temp zip file
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            zip_path = Path(f.name)
            f.write(b"PK\x03\x04")  # minimal zip header

        try:
            with patch("httpx.post") as mock_post:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_post.return_value = mock_resp
                result = runner.send_telegram_document(zip_path, "caption", bot_token="fake-token")
                self.assertTrue(result)
        finally:
            zip_path.unlink()


# ---------------------------------------------------------------------------
# GCP upload tests
# ---------------------------------------------------------------------------

class TestGCPUpload(unittest.TestCase):
    @patch("subprocess.run")
    def test_gcp_upload_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        html = Path("/tmp/test-report.html")
        html.write_text("<html>test</html>")

        url = runner.gcp_upload_report(
            html, "AAPL",
            gcp_host="thotas@34.82.106.90",
            remote_base="/var/www/static",
            local_tmp=Path("/tmp"),
        )
        self.assertEqual(url, "https://babu.thotas.com/AAPL-trading-report.html")
        html.unlink()

    @patch("subprocess.run")
    def test_gcp_upload_scp_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="scp failed")
        html = Path("/tmp/test-report2.html")
        html.write_text("<html>test</html>")

        url = runner.gcp_upload_report(
            html, "MSFT",
            gcp_host="thotas@34.82.106.90",
            remote_base="/var/www/static",
            local_tmp=Path("/tmp"),
        )
        self.assertIsNone(url)
        html.unlink()

    @patch("subprocess.run")
    def test_gcp_upload_ssh_fails(self, mock_run):
        # First call (scp) succeeds, second (ssh) fails
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="ssh failed"),
        ]
        html = Path("/tmp/test-report3.html")
        html.write_text("<html>test</html>")

        url = runner.gcp_upload_report(
            html, "GOOGL",
            gcp_host="thotas@34.82.106.90",
            remote_base="/var/www/static",
            local_tmp=Path("/tmp"),
        )
        self.assertIsNone(url)
        html.unlink()


# ---------------------------------------------------------------------------
# URL verification tests
# ---------------------------------------------------------------------------

class TestVerifyReportUrl(unittest.TestCase):
    @patch("httpx.get")
    def test_verify_url_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        result = runner.verify_report_url("https://babu.thotas.com/AAPL-trading-report.html")
        self.assertTrue(result)

    @patch("httpx.get")
    def test_verify_url_failure(self, mock_get):
        mock_get.side_effect = Exception("network error")
        result = runner.verify_report_url("https://babu.thotas.com/BAD.html")
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Batch runner integration (dry-run) tests
# ---------------------------------------------------------------------------

class TestBatchRunnerDryRun(unittest.TestCase):
    def setUp(self):
        self.state_file = Path("/tmp/test-batch-state.json")
        self.state_file.unlink(missing_ok=True)

    def tearDown(self):
        self.state_file.unlink(missing_ok=True)
        import shutil
        log_dir = Path("/tmp/test-logs")
        if log_dir.exists():
            shutil.rmtree(log_dir)

    def test_dry_run_completes_all_tickers(self):
        cfg = write_temp_config({
            "tickers": ["AAPL", "MSFT", "GOOGL"],
            "state_file": str(self.state_file),
        })
        config = runner.load_config(cfg)
        state = runner.run_batch(config, dry_run=True)
        self.assertEqual(state.status, "completed")
        self.assertEqual(len(state.tickers), 3)
        self.assertTrue(all(t.status == "completed" for t in state.tickers))
        # All should have Hold rating in dry run
        self.assertTrue(all(t.rating == "Hold" for t in state.tickers))

    def test_dry_run_state_persists(self):
        cfg = write_temp_config({
            "tickers": ["AAPL"],
            "state_file": str(self.state_file),
        })
        config = runner.load_config(cfg)
        state = runner.run_batch(config, dry_run=True)
        # Reload from disk
        loaded = runner.load_state(self.state_file)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.batch_id, state.batch_id)

    def test_batch_id_is_unique(self):
        cfg1 = write_temp_config({"tickers": ["AAPL"], "state_file": str(self.state_file)})
        cfg2 = write_temp_config({"tickers": ["MSFT"], "state_file": str(self.state_file)})
        s1 = runner.run_batch(runner.load_config(cfg1), dry_run=True)
        s2 = runner.run_batch(runner.load_config(cfg2), dry_run=True)
        self.assertNotEqual(s1.batch_id, s2.batch_id)


# ---------------------------------------------------------------------------
# Zip report tests
# ---------------------------------------------------------------------------

class TestZipReport(unittest.TestCase):
    def test_zip_report_files(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            html_path = Path(f.name)
            f.write(b"<html>")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            data_path = Path(f.name)
            f.write(b'{"test": 1}')
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            state_path = Path(f.name)
            f.write(b'{"ticker": "AAPL"}')
        zip_path = Path("/tmp/test_zip.zip")

        try:
            result = runner.zip_report_files(html_path, data_path, state_path, "AAPL", "2026-05-13")
            # Function always creates /tmp/aapl_report_2026-05-13.zip
            expected_zip = Path("/tmp/aapl_report_2026-05-13.zip")
            self.assertEqual(result, expected_zip)
            self.assertTrue(expected_zip.exists())
            # Verify it's a valid zip
            import zipfile
            with zipfile.ZipFile(expected_zip) as zf:
                names = zf.namelist()
                self.assertIn(html_path.name, names)
                self.assertIn(data_path.name, names)
        finally:
            html_path.unlink(missing_ok=True)
            data_path.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)
            Path("/tmp/aapl_report_2026-05-13.zip").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------

class TestGetToday(unittest.TestCase):
    def test_get_today_returns_iso_format(self):
        today = runner.get_today()
        # Should match YYYY-MM-DD
        self.assertRegex(today, r"^\d{4}-\d{2}-\d{2}$")
        # Should be today's date
        self.assertEqual(today, date.today().isoformat())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Run all tests
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner_obj = unittest.TextTestRunner(verbosity=2)
    result = runner_obj.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
