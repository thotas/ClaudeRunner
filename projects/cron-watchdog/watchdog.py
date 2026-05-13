#!/usr/bin/env python3
"""
Cron Watchdog - Monitors Hermes cron job outputs and sends Telegram alerts on failures.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from glob import glob
from pathlib import Path

import requests

# Default configuration
DEFAULT_CONFIG = {
    "output_dir": "~/.hermes/cron/output/",
    "alert_cooldown_minutes": 60,
    "watch_patterns": ["*.json"]
}

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_USER_ID = "7192357563"


def load_env():
    """Load environment variables from ~/.hermes/.env"""
    env_path = Path.home() / ".hermes" / ".env"
    env_vars = {}
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key] = value.strip()
    return env_vars


def get_token():
    """Get Telegram bot token from environment."""
    env_vars = load_env()
    token = env_vars.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("Warning: TELEGRAM_BOT_TOKEN not found in ~/.hermes/.env", file=sys.stderr)
    return token


def expand_path(path_str):
    """Expand ~ and environment variables in path."""
    return os.path.expanduser(os.path.expandvars(path_str))


def load_config(config_path=None):
    """Load configuration from JSON file."""
    if config_path is None:
        config_path = Path(__file__).parent / "config.json"
    else:
        config_path = Path(config_path)

    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
    else:
        config = DEFAULT_CONFIG.copy()

    # Ensure output_dir is expanded
    config["output_dir"] = expand_path(config.get("output_dir", DEFAULT_CONFIG["output_dir"]))
    config["alert_cooldown_minutes"] = int(config.get("alert_cooldown_minutes", DEFAULT_CONFIG["alert_cooldown_minutes"]))
    config["watch_patterns"] = config.get("watch_patterns", DEFAULT_CONFIG["watch_patterns"])

    return config


def find_output_files(output_dir, patterns):
    """Find output files matching patterns in output directory."""
    files = []
    for pattern in patterns:
        search_path = os.path.join(output_dir, pattern)
        files.extend(glob(search_path))
    return sorted(files, key=os.path.getmtime, reverse=True)


def parse_output_file(filepath):
    """
    Parse a cron output JSON file.
    Returns dict with job_name, exit_code, error_summary, timestamp.
    """
    try:
        with open(filepath) as f:
            data = json.load(f)

        job_name = data.get("job_name", os.path.basename(filepath))
        exit_code = data.get("exit_code", data.get("exit_status", 0))
        error_msg = data.get("error", data.get("error_message", data.get("stderr", "")))
        timestamp = data.get("timestamp", data.get("completed_at", ""))

        # If no explicit error field, check for failed status
        if exit_code != 0 and not error_msg:
            error_summary = f"Job exited with code {exit_code}"
        elif error_msg:
            # Truncate long error messages
            error_summary = str(error_msg)[:200]
        else:
            error_summary = ""

        return {
            "job_name": job_name,
            "exit_code": int(exit_code),
            "error_summary": error_summary,
            "timestamp": timestamp,
            "filepath": str(filepath)
        }
    except (json.JSONDecodeError, IOError) as e:
        return {
            "job_name": os.path.basename(filepath),
            "exit_code": -1,
            "error_summary": f"Failed to parse output: {e}",
            "timestamp": "",
            "filepath": str(filepath)
        }


def should_alert(job_name, last_alerts, cooldown_minutes):
    """
    Check if we should send an alert for this job based on cooldown period.
    Returns True if no recent alert was sent for this job.
    """
    if job_name not in last_alerts:
        return True

    last_alert_time = datetime.fromisoformat(last_alerts[job_name])
    cooldown = timedelta(minutes=cooldown_minutes)
    return datetime.now() - last_alert_time > cooldown


def send_telegram_alert(token, user_id, job_name, error_summary, timestamp):
    """
    Send Telegram alert via Bot API using requests.
    Returns True if successful, False otherwise.
    """
    message = f"⚠️ Cron Failure: {job_name}\nError: {error_summary}\nTime: {timestamp}"

    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": user_id,
        "text": message
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except requests.RequestException as e:
        print(f"Failed to send Telegram alert: {e}", file=sys.stderr)
        return False


def load_last_alerts(state_file):
    """Load last alert timestamps from state file."""
    if os.path.exists(state_file):
        try:
            with open(state_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_last_alerts(state_file, last_alerts):
    """Save last alert timestamps to state file."""
    with open(state_file, "w") as f:
        json.dump(last_alerts, f)


def run_watchdog(config_path=None, dry_run=False):
    """
    Main watchdog routine.
    Scans output files, checks for failures, and sends alerts.
    """
    config = load_config(config_path)
    token = get_token()

    if not token and not dry_run:
        print("Error: No Telegram bot token available", file=sys.stderr)
        return 1

    # State file to track last alert times
    state_file = Path(__file__).parent / ".watchdog_state.json"
    last_alerts = load_last_alerts(state_file)

    # Find output files
    output_dir = config["output_dir"]
    patterns = config["watch_patterns"]

    if not os.path.isdir(output_dir):
        print(f"Warning: Output directory not found: {output_dir}", file=sys.stderr)
        return 0

    output_files = find_output_files(output_dir, patterns)

    if not output_files:
        print("No output files found to process.")
        return 0

    alerts_sent = 0
    current_time = datetime.now().isoformat()

    for filepath in output_files:
        result = parse_output_file(filepath)

        # Only process failed jobs (non-zero exit code)
        if result["exit_code"] == 0:
            continue

        # Check if we should alert based on cooldown
        if not should_alert(result["job_name"], last_alerts, config["alert_cooldown_minutes"]):
            print(f"Skipping alert for {result['job_name']} (within cooldown period)")
            continue

        # Send alert
        if dry_run:
            print(f"[DRY RUN] Would alert: {result['job_name']} - {result['error_summary']}")
            alerts_sent += 1
        else:
            success = send_telegram_alert(
                token,
                TELEGRAM_USER_ID,
                result["job_name"],
                result["error_summary"],
                result["timestamp"] or current_time
            )
            if success:
                print(f"Alert sent for {result['job_name']}")
                last_alerts[result["job_name"]] = current_time
                alerts_sent += 1
            else:
                print(f"Failed to send alert for {result['job_name']}", file=sys.stderr)

    # Save updated alert timestamps
    if not dry_run and last_alerts:
        save_last_alerts(state_file, last_alerts)

    print(f"Processed {len(output_files)} files, sent {alerts_sent} alerts.")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cron Watchdog - Alert on failed cron jobs")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--dry-run", action="store_true", help="Don't send actual alerts")
    args = parser.parse_args()

    sys.exit(run_watchdog(args.config, args.dry_run))
