#!/bin/bash
# Claude Runner — Automated task executor using Claude Code
# Usage: ./claude-runner.sh [options] [task-file]
# Options:
#   --dry-run    Run Phase 1 only, show review output
#   --list       List pending tasks
#   --status     Show status of last run
#   (no args)    Pick next pending task and execute

set -euo pipefail

# ── Resolve script directory ──────────────────────────────────────────
RUNNER_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Load configuration ────────────────────────────────────────────────
CONFIG_FILE="$RUNNER_DIR/config/runner.conf"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: Config file not found: $CONFIG_FILE" >&2
    exit 1
fi
# shellcheck source=config/runner.conf
source "$CONFIG_FILE"

# Resolve relative paths to absolute
TASKS_DIR="$RUNNER_DIR/$TASKS_DIR"
REPORTS_DIR="$RUNNER_DIR/$REPORTS_DIR"
LOGS_DIR="$RUNNER_DIR/$LOGS_DIR"
PROMPTS_DIR="$RUNNER_DIR/$PROMPTS_DIR"
NOTIFY_HOOK="$RUNNER_DIR/$NOTIFY_HOOK"

# ── Timestamp for this run ────────────────────────────────────────────
RUN_TIMESTAMP="$(date '+%Y-%m-%d-%H%M%S')"
RUN_DATE="$(date '+%Y-%m-%d %H:%M:%S')"
LOG_FILE="$LOGS_DIR/${RUN_TIMESTAMP}.log"
RUN_START_EPOCH="$(date '+%s')"

# ── Logging ───────────────────────────────────────────────────────────
_log_level_num() {
    case "$1" in
        debug) echo 0 ;;
        info)  echo 1 ;;
        warn)  echo 2 ;;
        error) echo 3 ;;
        *)     echo 1 ;;
    esac
}

CONFIGURED_LOG_LEVEL="$(_log_level_num "$LOG_LEVEL")"

log() {
    local level="$1"
    shift
    local level_num
    level_num="$(_log_level_num "$level")"

    if [ "$level_num" -ge "$CONFIGURED_LOG_LEVEL" ]; then
        local upper_level
        upper_level="$(echo "$level" | tr '[:lower:]' '[:upper:]')"
        local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [$upper_level] $*"
        echo "$msg" | tee -a "$LOG_FILE"
    fi
}

log_debug() { log debug "$@"; }
log_info()  { log info "$@"; }
log_warn()  { log warn "$@"; }
log_error() { log error "$@"; }

# ── Environment validation ────────────────────────────────────────────
validate_environment() {
    local missing=0

    if [ -z "${MINIMAX_BASE_URL:-}" ]; then
        log_error "MINIMAX_BASE_URL is not set"
        missing=1
    fi
    if [ -z "${MINIMAX_AUTH_TOKEN:-}" ]; then
        log_error "MINIMAX_AUTH_TOKEN is not set"
        missing=1
    fi
    if [ -z "${MINIMAX_MODEL:-}" ]; then
        log_error "MINIMAX_MODEL is not set"
        missing=1
    fi
    if [ ! -x "$CLAUDE_BIN" ]; then
        log_error "Claude CLI not found or not executable: $CLAUDE_BIN"
        missing=1
    fi
    if ! command -v jq >/dev/null 2>&1; then
        log_error "jq is not installed"
        missing=1
    fi

    if [ "$missing" -eq 1 ]; then
        log_error "Environment validation failed. Aborting."
        exit 1
    fi

    log_debug "Environment validated: MINIMAX_BASE_URL=$MINIMAX_BASE_URL, MODEL=$MINIMAX_MODEL, CLAUDE=$CLAUDE_BIN"
}

# ── Duration helper ───────────────────────────────────────────────────
format_duration() {
    local seconds="$1"
    local minutes=$((seconds / 60))
    local remaining_seconds=$((seconds % 60))
    if [ "$minutes" -gt 0 ]; then
        echo "${minutes}m ${remaining_seconds}s"
    else
        echo "${remaining_seconds}s"
    fi
}

# ── Lock management ───────────────────────────────────────────────────
acquire_lock() {
    if [ -f "$LOCK_FILE" ]; then
        local lock_pid
        lock_pid="$(cat "$LOCK_FILE" 2>/dev/null || echo "")"
        local lock_age=0

        if [ -f "$LOCK_FILE" ]; then
            local lock_mtime
            lock_mtime="$(stat -f '%m' "$LOCK_FILE" 2>/dev/null || echo "0")"
            local now
            now="$(date '+%s')"
            lock_age=$((now - lock_mtime))
        fi

        if [ "$lock_age" -ge "$LOCK_TIMEOUT" ]; then
            log_warn "Stale lock found (age: $(format_duration $lock_age), pid: $lock_pid). Removing."
            rm -f "$LOCK_FILE"
        elif [ -n "$lock_pid" ] && ! kill -0 "$lock_pid" 2>/dev/null; then
            log_warn "Lock held by dead process (pid: $lock_pid). Removing."
            rm -f "$LOCK_FILE"
        else
            log_info "Another run is active (pid: $lock_pid, age: $(format_duration $lock_age)). Exiting."
            exit 0
        fi
    fi

    echo $$ > "$LOCK_FILE"
    log_debug "Lock acquired (pid: $$)"
}

release_lock() {
    rm -f "$LOCK_FILE"
    log_debug "Lock released"
}

# ── Task lifecycle ────────────────────────────────────────────────────
CURRENT_TASK_FILE=""
CURRENT_TASK_NAME=""
TASK_IS_QUEUED=false

pick_task() {
    local pending_dir="$TASKS_DIR/pending"
    local oldest
    oldest="$(find "$pending_dir" -maxdepth 1 -name '*.txt' -type f -print 2>/dev/null | head -1)"

    if [ -z "$oldest" ]; then
        oldest="$(find "$pending_dir" -maxdepth 1 -name '*.txt' -type f -print0 2>/dev/null \
            | xargs -0 ls -t 2>/dev/null | tail -1)"
    fi

    if [ -z "$oldest" ]; then
        return 1
    fi

    CURRENT_TASK_FILE="$oldest"
    CURRENT_TASK_NAME="$(basename "$oldest" .txt)"
    TASK_IS_QUEUED=true
    log_info "Picked task: $CURRENT_TASK_NAME ($CURRENT_TASK_FILE)"
}

move_task() {
    local destination="$1"
    local dest_dir="$TASKS_DIR/$destination"

    if [ "$TASK_IS_QUEUED" = true ] && [ -f "$CURRENT_TASK_FILE" ]; then
        local dest_file="$dest_dir/$(basename "$CURRENT_TASK_FILE")"
        mv "$CURRENT_TASK_FILE" "$dest_file"
        CURRENT_TASK_FILE="$dest_file"
        log_debug "Moved task to $destination: $dest_file"
    fi
}

append_to_task() {
    local content="$1"
    if [ -f "$CURRENT_TASK_FILE" ]; then
        printf "\n%s\n" "$content" >> "$CURRENT_TASK_FILE"
    fi
}

restore_task() {
    if [ "$TASK_IS_QUEUED" = true ] && [ -f "$CURRENT_TASK_FILE" ]; then
        local filename
        filename="$(basename "$CURRENT_TASK_FILE")"
        local pending_file="$TASKS_DIR/pending/$filename"

        case "$CURRENT_TASK_FILE" in
            *in-progress*)
                mv "$CURRENT_TASK_FILE" "$pending_file"
                log_warn "Task restored to pending: $filename"
                ;;
        esac
    fi
}

list_pending_tasks() {
    local pending_dir="$TASKS_DIR/pending"
    local count
    count="$(find "$pending_dir" -maxdepth 1 -name '*.txt' -type f 2>/dev/null | wc -l | tr -d ' ')"

    echo "Pending tasks: $count"
    echo "---"

    if [ "$count" -gt 0 ]; then
        find "$pending_dir" -maxdepth 1 -name '*.txt' -type f -print0 2>/dev/null \
            | xargs -0 ls -lt 2>/dev/null \
            | while read -r line; do
                echo "  $line"
            done
        echo ""
        echo "Next task to run:"
        local next
        next="$(find "$pending_dir" -maxdepth 1 -name '*.txt' -type f -print0 2>/dev/null \
            | xargs -0 ls -t 2>/dev/null | tail -1)"
        if [ -n "$next" ]; then
            echo "  $(basename "$next")"
            echo ""
            echo "Contents:"
            sed 's/^/  /' "$next"
        fi
    fi
}

show_status() {
    local latest_log
    latest_log="$(find "$LOGS_DIR" -maxdepth 1 -name '*.log' -type f -print0 2>/dev/null \
        | xargs -0 ls -t 2>/dev/null | head -1)"

    if [ -z "$latest_log" ]; then
        echo "No runs recorded yet."
        return
    fi

    echo "Last run: $(basename "$latest_log" .log)"
    echo "---"
    tail -20 "$latest_log"
}

# ── Notifications ─────────────────────────────────────────────────────
notify() {
    local status="$1"
    local summary="$2"
    local report_path="${3:-}"

    if [ "$status" = "success" ] && [ "$NOTIFY_ON_SUCCESS" != "true" ]; then
        return
    fi
    if [ "$status" = "failure" ] && [ "$NOTIFY_ON_FAILURE" != "true" ]; then
        return
    fi

    log_info "Notification: [$status] $summary"

    if [ -x "$NOTIFY_HOOK" ]; then
        "$NOTIFY_HOOK" "$status" "$summary" "$report_path" 2>/dev/null || \
            log_warn "Notify hook returned non-zero exit code"
    fi
}

# ── Project registry ──────────────────────────────────────────────────
load_projects_registry() {
    local registry_file="$RUNNER_DIR/config/projects.conf"
    if [ ! -f "$registry_file" ]; then
        log_error "Projects registry not found: $registry_file"
        exit 1
    fi

    local registry=""
    while IFS='|' read -r name path aliases guardrails || [ -n "$name" ]; do
        case "$name" in
            \#*|"") continue ;;
        esac
        local expanded_path="${path/#\~/$HOME}"
        registry="${registry}
- Name: ${name}
  Path: ${expanded_path}
  Aliases: ${aliases}
  Guardrails: ${guardrails:-none}"
    done < "$registry_file"

    echo "$registry"
}

load_project_guardrails() {
    local target_name="$1"
    local registry_file="$RUNNER_DIR/config/projects.conf"

    while IFS='|' read -r name path aliases guardrails || [ -n "$name" ]; do
        case "$name" in
            \#*|"") continue ;;
        esac
        if [ "$name" = "$target_name" ]; then
            echo "${guardrails:-}"
            return
        fi
    done < "$registry_file"
}

load_global_guardrails() {
    local guardrails_file="$RUNNER_DIR/config/guardrails.conf"
    if [ ! -f "$guardrails_file" ]; then
        log_warn "Global guardrails file not found: $guardrails_file"
        echo ""
        return
    fi

    grep -v '^\s*#' "$guardrails_file" | grep -v '^\s*$' || true
}

merge_guardrails() {
    local project_name="$1"
    local task_guardrails_json="$2"

    local merged=""

    local global
    global="$(load_global_guardrails)"
    if [ -n "$global" ]; then
        merged="## Global Guardrails
$global"
    fi

    local project_gr
    project_gr="$(load_project_guardrails "$project_name")"
    if [ -n "$project_gr" ]; then
        merged="$merged

## Project-Specific Guardrails ($project_name)
$project_gr"
    fi

    if [ -n "$task_guardrails_json" ] && [ "$task_guardrails_json" != "[]" ]; then
        local task_gr
        task_gr="$(echo "$task_guardrails_json" | jq -r '.[]' 2>/dev/null || true)"
        if [ -n "$task_gr" ]; then
            merged="$merged

## Task-Specific Guardrails
$task_gr"
        fi
    fi

    echo "$merged"
}

# ── Claude Code invocation ────────────────────────────────────────────
run_claude() {
    local prompt_text="$1"
    local working_dir="${2:-$RUNNER_DIR}"

    local output
    local exit_code=0

    log_debug "Invoking Claude Code in: $working_dir"
    log_debug "Prompt length: ${#prompt_text} chars"

    output="$(
        cd "$working_dir" && \
        ANTHROPIC_BASE_URL="$MINIMAX_BASE_URL" \
        ANTHROPIC_AUTH_TOKEN="$MINIMAX_AUTH_TOKEN" \
        ANTHROPIC_API_KEY="" \
        ANTHROPIC_MODEL="$MINIMAX_MODEL" \
        ANTHROPIC_DEFAULT_SONNET_MODEL="$MINIMAX_MODEL" \
        ANTHROPIC_DEFAULT_OPUS_MODEL="$MINIMAX_MODEL" \
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
        "$CLAUDE_BIN" --dangerously-skip-permissions \
            -p "$prompt_text" \
            --output-format "$CLAUDE_OUTPUT_FORMAT" \
            2>>"$LOG_FILE"
    )" || exit_code=$?

    if [ $exit_code -ne 0 ]; then
        log_error "Claude Code exited with code $exit_code"
        echo "$output"
        return $exit_code
    fi

    echo "$output"
}
