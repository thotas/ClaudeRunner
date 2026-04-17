#!/bin/bash
# Notification hook — called by claude-runner.sh after each run
# Arguments: <status> <summary> <report_path>
#   status:      "success" | "failure" | "no-tasks"
#   summary:     one-line description
#   report_path: path to full report file (empty for no-tasks)
#
# Customize this script to send notifications via WhatsApp, Telegram, etc.

STATUS="$1"
SUMMARY="$2"
REPORT_PATH="$3"

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$STATUS] $SUMMARY" >> "$SCRIPT_DIR/logs/notifications.log"
