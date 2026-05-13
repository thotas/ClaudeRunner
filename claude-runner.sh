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

# Resolve relative paths to absolute (guard against already-absolute paths)
_resolve_path() {
    case "$1" in
        /*) echo "$1" ;;
        *)  echo "$RUNNER_DIR/$1" ;;
    esac
}
TASKS_DIR="$(_resolve_path "$TASKS_DIR")"
REPORTS_DIR="$(_resolve_path "$REPORTS_DIR")"
LOGS_DIR="$(_resolve_path "$LOGS_DIR")"
PROMPTS_DIR="$(_resolve_path "$PROMPTS_DIR")"
NOTIFY_HOOK="$(_resolve_path "$NOTIFY_HOOK")"

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
    # Check for existing lock and handle stale/dead cases
    if [ -f "$LOCK_FILE" ]; then
        local lock_pid
        lock_pid="$(cat "$LOCK_FILE" 2>/dev/null || echo "")"

        local lock_mtime
        lock_mtime="$(stat -f '%m' "$LOCK_FILE" 2>/dev/null || echo "0")"
        local now
        now="$(date '+%s')"
        local lock_age=$((now - lock_mtime))

        if [ "$lock_age" -ge "$LOCK_TIMEOUT" ]; then
            log_warn "Stale lock found (age: $(format_duration "$lock_age"), pid: $lock_pid). Removing."
            rm -f "$LOCK_FILE"
        elif [ -n "$lock_pid" ] && ! kill -0 "$lock_pid" 2>/dev/null; then
            log_warn "Lock held by dead process (pid: $lock_pid). Removing."
            rm -f "$LOCK_FILE"
        else
            log_info "Another run is active (pid: $lock_pid, age: $(format_duration "$lock_age")). Exiting."
            exit 0
        fi
    fi

    # Atomic lock acquisition using mkdir (POSIX atomic on all filesystems)
    local lock_dir="${LOCK_FILE}.d"
    if ! mkdir "$lock_dir" 2>/dev/null; then
        log_info "Another run just started (lock race). Exiting."
        exit 0
    fi
    echo $$ > "$LOCK_FILE"
    rmdir "$lock_dir" 2>/dev/null || true
    log_debug "Lock acquired (pid: $$)"
}

release_lock() {
    rm -f "$LOCK_FILE"
    rmdir "${LOCK_FILE}.d" 2>/dev/null || true
    log_debug "Lock released"
}

# ── Task lifecycle ────────────────────────────────────────────────────
CURRENT_TASK_FILE=""
CURRENT_TASK_NAME=""
TASK_IS_QUEUED=false

pick_task() {
    local pending_dir="$TASKS_DIR/pending"
    # Pick the oldest .txt file by modification time (FIFO order)
    local oldest
    oldest="$(find "$pending_dir" -maxdepth 1 -name '*.txt' -type f -print0 2>/dev/null \
        | xargs -0 ls -t 2>/dev/null | tail -1)"

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
RETRY_MAX="${RETRY_MAX:-3}"
RETRY_BASE_DELAY="${RETRY_BASE_DELAY:-5}"

run_claude() {
    local prompt_text="$1"
    local working_dir="${2:-$RUNNER_DIR}"

    local output
    local exit_code=0
    local attempt=0

    log_debug "Invoking Claude Code in: $working_dir"
    log_debug "Prompt length: ${#prompt_text} chars"
    log_debug "Retry max: $RETRY_MAX"

    until [ "$attempt" -ge "$RETRY_MAX" ]; do
        attempt=$((attempt + 1))
        log_info "Claude Code attempt $attempt/$RETRY_MAX"

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
        )" && exit_code=$? || exit_code=$?

        if [ $exit_code -eq 0 ]; then
            log_info "Claude Code succeeded on attempt $attempt"
            echo "$output"
            return 0
        fi

        log_warn "Claude Code failed with exit code $exit_code (attempt $attempt/$RETRY_MAX)"

        if [ "$attempt" -lt "$RETRY_MAX" ]; then
            local delay=$((RETRY_BASE_DELAY * attempt))
            log_info "Retrying in ${delay}s (exponential backoff)..."
            sleep "$delay"
        fi
    done

    log_error "Claude Code failed after $RETRY_MAX attempts"
    echo "$output"
    return $exit_code
}

# ── Phase 1: Review & Enrich ─────────────────────────────────────────
REVIEW_JSON=""

phase_review() {
    local task_file="$1"
    local task_content
    task_content="$(cat "$task_file")"

    log_info "Phase 1: Reviewing task..."

    local review_prompt_template
    review_prompt_template="$(cat "$PROMPTS_DIR/review.md")"

    local registry
    registry="$(load_projects_registry)"

    local review_prompt="${review_prompt_template//\{\{PROJECTS_REGISTRY\}\}/$registry}"

    local full_prompt="$review_prompt

## Task to Review
$task_content"

    local raw_output
    raw_output="$(run_claude "$full_prompt")" || {
        log_error "Phase 1: Claude Code failed"
        log_error "Output: $raw_output"
        return 1
    }

    log_debug "Phase 1 raw output: $raw_output"

    local json_content
    json_content="$(echo "$raw_output" | jq -r '.result // .' 2>/dev/null || echo "$raw_output")"

    if echo "$json_content" | jq -e 'type == "string"' >/dev/null 2>&1; then
        json_content="$(echo "$json_content" | jq -r '.')"
    fi

    if ! echo "$json_content" | jq -e '.project_name' >/dev/null 2>&1; then
        log_error "Phase 1: Invalid JSON output from Claude"
        log_error "Content: $json_content"
        return 1
    fi

    REVIEW_JSON="$json_content"

    local project_name
    project_name="$(echo "$REVIEW_JSON" | jq -r '.project_name')"
    local project_path
    project_path="$(echo "$REVIEW_JSON" | jq -r '.project_path')"
    local task_type
    task_type="$(echo "$REVIEW_JSON" | jq -r '.task_type')"

    if [ "$project_name" = "UNKNOWN" ]; then
        log_error "Phase 1: Could not identify project from task description"
        return 1
    fi

    project_path="${project_path/#\~/$HOME}"
    REVIEW_JSON="$(echo "$REVIEW_JSON" | jq --arg p "$project_path" '.project_path = $p')"

    if [ ! -d "$project_path" ]; then
        log_error "Phase 1: Project path does not exist: $project_path"
        return 1
    fi

    case "$task_type" in
        bugfix|feature|refactor|code-review|security-review|testing|docs|research|build) ;;
        *)
            log_error "Phase 1: Unrecognized task type: $task_type"
            return 1
            ;;
    esac

    local summary
    summary="$(echo "$REVIEW_JSON" | jq -r '.summary')"
    local is_code_task
    is_code_task="$(echo "$REVIEW_JSON" | jq -r '.is_code_task')"

    log_info "Phase 1 complete: project=$project_name, type=$task_type, code_task=$is_code_task"
    log_info "Summary: $summary"
}

# ── Phase 2: Execute ──────────────────────────────────────────────────
EXECUTE_OUTPUT=""
EXECUTE_EXIT_CODE=0

phase_execute() {
    log_info "Phase 2: Executing task..."

    local project_name
    project_name="$(echo "$REVIEW_JSON" | jq -r '.project_name')"
    local project_path
    project_path="$(echo "$REVIEW_JSON" | jq -r '.project_path')"
    local task_type
    task_type="$(echo "$REVIEW_JSON" | jq -r '.task_type')"
    local is_code_task
    is_code_task="$(echo "$REVIEW_JSON" | jq -r '.is_code_task')"
    local branch_name
    branch_name="$(echo "$REVIEW_JSON" | jq -r '.branch_name')"
    local enriched_task
    enriched_task="$(echo "$REVIEW_JSON" | jq -r '.enriched_task')"
    local summary
    summary="$(echo "$REVIEW_JSON" | jq -r '.summary')"
    local task_guardrails_json
    task_guardrails_json="$(echo "$REVIEW_JSON" | jq -c '.task_guardrails')"

    local merged_guardrails
    merged_guardrails="$(merge_guardrails "$project_name" "$task_guardrails_json")"

    local execute_prompt
    execute_prompt="$(cat "$PROMPTS_DIR/execute.md")"

    execute_prompt="${execute_prompt//\{\{ENRICHED_TASK\}\}/$enriched_task}"
    execute_prompt="${execute_prompt//\{\{TASK_TYPE\}\}/$task_type}"
    execute_prompt="${execute_prompt//\{\{SUMMARY\}\}/$summary}"
    execute_prompt="${execute_prompt//\{\{MERGED_GUARDRAILS\}\}/$merged_guardrails}"
    execute_prompt="${execute_prompt//\{\{PROJECT_PATH\}\}/$project_path}"
    execute_prompt="${execute_prompt//\{\{BRANCH_NAME\}\}/$branch_name}"

    log_info "Executing in: $project_path"
    log_info "Task type: $task_type (code_task=$is_code_task)"

    if [ "$is_code_task" = "true" ]; then
        log_info "Branch: $branch_name"
    fi

    EXECUTE_EXIT_CODE=0
    EXECUTE_OUTPUT="$(run_claude "$execute_prompt" "$project_path")" \
        || EXECUTE_EXIT_CODE=$?

    if [ "$EXECUTE_EXIT_CODE" -ne 0 ]; then
        log_error "Phase 2: Claude Code failed with exit code $EXECUTE_EXIT_CODE"
    fi

    local output_lines
    output_lines="$(echo "$EXECUTE_OUTPUT" | wc -l | tr -d ' ')"
    log_info "Phase 2 complete: $output_lines lines of output (exit code: $EXECUTE_EXIT_CODE)"
}

# ── Phase 3: Report generation ────────────────────────────────────────
REPORT_PATH=""

phase_report() {
    log_info "Phase 3: Generating report..."

    local task_content
    task_content="$(cat "$CURRENT_TASK_FILE" 2>/dev/null || echo "(task file unavailable)")"

    local project_name
    project_name="$(echo "$REVIEW_JSON" | jq -r '.project_name')"
    local project_path
    project_path="$(echo "$REVIEW_JSON" | jq -r '.project_path')"
    local task_type
    task_type="$(echo "$REVIEW_JSON" | jq -r '.task_type')"
    local branch_name
    branch_name="$(echo "$REVIEW_JSON" | jq -r '.branch_name // "N/A"')"
    local summary
    summary="$(echo "$REVIEW_JSON" | jq -r '.summary')"

    local run_end_epoch
    run_end_epoch="$(date '+%s')"
    local duration_secs=$((run_end_epoch - RUN_START_EPOCH))
    local duration
    duration="$(format_duration $duration_secs)"

    local status="success"
    if [ "$EXECUTE_EXIT_CODE" -ne 0 ]; then
        status="failure"
    fi

    local report_prompt
    report_prompt="$(cat "$PROMPTS_DIR/report.md")"

    local execution_log
    execution_log="$(echo "$EXECUTE_OUTPUT" | jq -r '.result // .' 2>/dev/null || echo "$EXECUTE_OUTPUT")"
    if echo "$execution_log" | jq -e 'type == "string"' >/dev/null 2>&1; then
        execution_log="$(echo "$execution_log" | jq -r '.')"
    fi

    report_prompt="${report_prompt//\{\{ORIGINAL_TASK\}\}/$task_content}"
    report_prompt="${report_prompt//\{\{PROJECT_NAME\}\}/$project_name}"
    report_prompt="${report_prompt//\{\{PROJECT_PATH\}\}/$project_path}"
    report_prompt="${report_prompt//\{\{TASK_TYPE\}\}/$task_type}"
    report_prompt="${report_prompt//\{\{BRANCH_NAME\}\}/$branch_name}"
    report_prompt="${report_prompt//\{\{STATUS\}\}/$status}"
    report_prompt="${report_prompt//\{\{DURATION\}\}/$duration}"
    report_prompt="${report_prompt//\{\{EXECUTION_LOG\}\}/$execution_log}"

    local report_output
    report_output="$(run_claude "$report_prompt")" || {
        log_warn "Phase 3: Report generation failed"
        report_output="# Task Report (auto-generated — report phase failed)

## Raw Execution Output
$execution_log"
    }

    local report_text
    report_text="$(echo "$report_output" | jq -r '.result // .' 2>/dev/null || echo "$report_output")"
    if echo "$report_text" | jq -e 'type == "string"' >/dev/null 2>&1; then
        report_text="$(echo "$report_text" | jq -r '.')"
    fi

    REPORT_PATH="$REPORTS_DIR/${RUN_TIMESTAMP}-${project_name}-${task_type}.md"
    echo "$report_text" > "$REPORT_PATH"
    log_info "Report saved: $REPORT_PATH"

    append_to_task "--- RUNNER OUTPUT ($RUN_DATE) ---
Status: $status
Project: $project_name ($project_path)
Task type: $task_type
Branch: $branch_name
Duration: $duration
Report: $(basename "$REPORT_PATH")
Log: $(basename "$LOG_FILE")"

    log_info "Phase 3 complete"
}

# ── Signal trapping ───────────────────────────────────────────────────
cleanup() {
    log_warn "Interrupted — cleaning up..."
    restore_task
    release_lock
    exit 130
}

trap cleanup SIGINT SIGTERM

# ── CLI argument parsing ──────────────────────────────────────────────
DRY_RUN=false
SPECIFIC_TASK_FILE=""

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --list)
                list_pending_tasks
                exit 0
                ;;
            --status)
                show_status
                exit 0
                ;;
            --help|-h)
                echo "Usage: $0 [options] [task-file]"
                echo ""
                echo "Options:"
                echo "  --dry-run    Run Phase 1 only, show review output"
                echo "  --list       List pending tasks"
                echo "  --status     Show status of last run"
                echo "  --help       Show this help"
                echo ""
                echo "If task-file is provided, runs that file directly (skips queue)."
                echo "If no arguments, picks the next pending task from the queue."
                exit 0
                ;;
            -*)
                echo "Unknown option: $1" >&2
                echo "Run '$0 --help' for usage." >&2
                exit 1
                ;;
            *)
                SPECIFIC_TASK_FILE="$1"
                shift
                ;;
        esac
    done
}

# ── Main ──────────────────────────────────────────────────────────────
main() {
    # Ensure required directories exist
    mkdir -p "$LOGS_DIR" "$REPORTS_DIR" \
        "$TASKS_DIR/pending" "$TASKS_DIR/in-progress" \
        "$TASKS_DIR/completed" "$TASKS_DIR/failed"

    touch "$LOG_FILE"
    log_info "=== Claude Runner started ==="

    validate_environment

    acquire_lock

    if [ -n "$SPECIFIC_TASK_FILE" ]; then
        if [ ! -f "$SPECIFIC_TASK_FILE" ]; then
            log_error "Task file not found: $SPECIFIC_TASK_FILE"
            release_lock
            exit 1
        fi
        CURRENT_TASK_FILE="$SPECIFIC_TASK_FILE"
        CURRENT_TASK_NAME="$(basename "$SPECIFIC_TASK_FILE" .txt)"
        TASK_IS_QUEUED=false
        log_info "Running specific task: $CURRENT_TASK_NAME"
    else
        if ! pick_task; then
            log_info "No pending tasks."
            notify "no-tasks" "No pending tasks in queue" ""
            release_lock
            exit 0
        fi
        move_task "in-progress"
    fi

    local final_status="success"
    local final_summary=""

    if ! phase_review "$CURRENT_TASK_FILE"; then
        final_status="failure"
        final_summary="Phase 1 failed: could not review/enrich task '$CURRENT_TASK_NAME'"
        log_error "$final_summary"
        append_to_task "--- RUNNER OUTPUT ($RUN_DATE) ---
Status: failure
Error: Phase 1 (review) failed
Log: $(basename "$LOG_FILE")"
        move_task "failed"
        notify "$final_status" "$final_summary" ""
        release_lock
        exit 1
    fi

    local project_name
    project_name="$(echo "$REVIEW_JSON" | jq -r '.project_name')"
    local summary
    summary="$(echo "$REVIEW_JSON" | jq -r '.summary')"

    if [ "$DRY_RUN" = true ]; then
        log_info "Dry run — Phase 1 output:"
        echo ""
        echo "=== DRY RUN — Phase 1 Review Output ==="
        echo "$REVIEW_JSON" | jq .
        echo "========================================"
        echo ""
        echo "Guardrails that would be applied:"
        local task_guardrails_json
        task_guardrails_json="$(echo "$REVIEW_JSON" | jq -c '.task_guardrails')"
        merge_guardrails "$project_name" "$task_guardrails_json"
        echo ""

        if [ "$TASK_IS_QUEUED" = true ]; then
            restore_task
        fi

        release_lock
        exit 0
    fi

    phase_execute

    phase_report

    if [ "$EXECUTE_EXIT_CODE" -ne 0 ]; then
        final_status="failure"
        final_summary="Task '$CURRENT_TASK_NAME' failed on $project_name: $summary"
        move_task "failed"
    else
        final_status="success"
        final_summary="Task '$CURRENT_TASK_NAME' completed on $project_name: $summary"
        move_task "completed"
    fi

    local run_end_epoch
    run_end_epoch="$(date '+%s')"
    local duration_secs=$((run_end_epoch - RUN_START_EPOCH))
    local duration
    duration="$(format_duration $duration_secs)"

    log_info "=== Claude Runner finished: $final_status ($duration) ==="

    notify "$final_status" "$final_summary" "$REPORT_PATH"

    release_lock

    if [ "$final_status" = "failure" ]; then
        exit 1
    fi
    exit 0
}

# ── Entry point ───────────────────────────────────────────────────────
parse_args "$@"
main
