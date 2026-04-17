# Claude Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Bash script orchestrator that picks free-text task files from a queue, uses Claude Code to analyze and execute them against local repos, and produces reports with notifications.

**Architecture:** Single `claude-runner.sh` script orchestrates a three-phase Claude Code pipeline (review → execute → report). Config files define project registry and guardrails. Prompt templates drive each phase. Task files move through `pending/ → in-progress/ → completed/failed/` folders.

**Tech Stack:** Bash 3.2 (macOS default), jq 1.7, Claude Code CLI 2.x, standard Unix tools (date, mv, cat, mktemp, find)

---

## File Map

| File | Responsibility |
|---|---|
| `claude-runner.sh` | Main orchestrator — CLI parsing, locking, task lifecycle, three-phase pipeline, notifications |
| `config/runner.conf` | Global settings — paths, timeouts, log level, notification flags |
| `config/projects.conf` | Project registry — name, path, aliases, per-project guardrails |
| `config/guardrails.conf` | Global guardrails — applied to every task execution |
| `config/notify.sh` | Optional notification hook — called with (status, summary, report_path) |
| `prompts/review.md` | Phase 1 prompt — parse task, match project, classify, enrich, output JSON |
| `prompts/execute.md` | Phase 2 prompt template — placeholders replaced at runtime |
| `prompts/report.md` | Phase 3 prompt template — generate structured report from execution log |
| `tasks/pending/` | Input queue — drop `.txt` files here |
| `tasks/in-progress/` | Currently executing task |
| `tasks/completed/` | Successfully finished tasks with appended summary |
| `tasks/failed/` | Failed tasks with appended error info |
| `reports/` | Generated reports for all tasks |
| `logs/` | Per-run execution logs |

---

### Task 1: Directory Scaffolding and Config Files

**Files:**
- Create: `config/runner.conf`
- Create: `config/projects.conf`
- Create: `config/guardrails.conf`
- Create: `config/notify.sh`
- Create: `tasks/pending/.gitkeep`
- Create: `tasks/in-progress/.gitkeep`
- Create: `tasks/completed/.gitkeep`
- Create: `tasks/failed/.gitkeep`
- Create: `reports/.gitkeep`
- Create: `logs/.gitkeep`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p config tasks/pending tasks/in-progress tasks/completed tasks/failed reports logs prompts
```

- [ ] **Step 2: Create `config/runner.conf`**

```bash
# Claude Runner Configuration
# All paths are relative to the ClaudeRunner root directory

# Directories
TASKS_DIR="tasks"
REPORTS_DIR="reports"
LOGS_DIR="logs"
PROMPTS_DIR="prompts"

# Claude Code settings
CLAUDE_BIN="/opt/homebrew/bin/claude"
CLAUDE_OUTPUT_FORMAT="json"

# Task processing
LOCK_FILE="/tmp/claude-runner.lock"
LOCK_TIMEOUT=3600  # seconds — auto-release stale lock after 1 hour

# Logging
LOG_LEVEL="info"  # debug, info, warn, error

# Notifications
NOTIFY_ON_SUCCESS=true
NOTIFY_ON_FAILURE=true
NOTIFY_HOOK="config/notify.sh"
```

- [ ] **Step 3: Create `config/projects.conf`**

```bash
# Project Registry
# Format: name|path|aliases|guardrails
# - name: canonical project name
# - path: absolute or ~-relative path to the local repo
# - aliases: comma-separated alternative names for fuzzy matching
# - guardrails: per-project guardrails (optional)
#
# Example:
# payments-app|~/Development/payments-app|payments,billing|do not modify database migrations
```

- [ ] **Step 4: Create `config/guardrails.conf`**

```
# Global Guardrails — applied to every task execution
# One guardrail per line. Lines starting with # are ignored.
Do not force-push to any branch
Do not delete files unless the task explicitly requires it
Do not modify CI/CD pipelines or GitHub Actions workflows
Stay within the identified project directory only
Do not modify .env files or secrets
Create a new branch for all code changes, never commit directly to main
Do not install new dependencies unless the task requires it
```

- [ ] **Step 5: Create `config/notify.sh`**

```bash
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
```

- [ ] **Step 6: Make notify.sh executable and create .gitkeep files**

```bash
chmod +x config/notify.sh
touch tasks/pending/.gitkeep tasks/in-progress/.gitkeep tasks/completed/.gitkeep tasks/failed/.gitkeep reports/.gitkeep logs/.gitkeep
```

- [ ] **Step 7: Verify directory structure**

Run: `find . -not -path './.git/*' -not -name '.DS_Store' | sort`

Expected output should show all directories and config files created above.

- [ ] **Step 8: Commit**

```bash
git add config/ tasks/ reports/ logs/
git commit -m "feat: add directory scaffolding and config files

Config files for runner settings, project registry, global guardrails,
and notification hook. Task lifecycle folders (pending, in-progress,
completed, failed) with .gitkeep files."
```

---

### Task 2: Prompt Templates

**Files:**
- Create: `prompts/review.md`
- Create: `prompts/execute.md`
- Create: `prompts/report.md`

- [ ] **Step 1: Create `prompts/review.md`**

```markdown
You are a task reviewer for an automated Claude Code runner.

Given a free-text task description and a project registry, your job is to:

1. Identify which project this task belongs to
2. Classify the task type
3. Determine if this is a code-changing task or a non-code task
4. Extract any guardrails mentioned in the task
5. Enrich the task with actionable details
6. Suggest a branch name for code tasks

## Project Registry
{{PROJECTS_REGISTRY}}

## Task Types
- bugfix: Fix a bug or defect
- feature: Add new functionality
- refactor: Restructure existing code without changing behavior
- code-review: Review code for quality, patterns, issues
- security-review: Audit for security vulnerabilities
- testing: Write or improve tests
- docs: Documentation changes
- research: Investigate a question, produce a report
- build: Build a new project or major component

## Code vs Non-Code Classification
- Code tasks (is_code_task: true): bugfix, feature, refactor, testing, build
- Non-code tasks (is_code_task: false): code-review, security-review, docs, research

## Rules
- You MUST pick a project from the registry above. If no project clearly matches, set project_name to "UNKNOWN".
- For branch names, use the pattern: type/short-description (e.g., fix/login-timeout, feat/user-export, refactor/auth-middleware)
- Keep enriched_task actionable and specific — mention likely files, modules, or areas to investigate
- Extract any restrictions or constraints from the task text into task_guardrails
- estimated_complexity: "low" (< 30 min), "medium" (30 min - 2 hours), "high" (> 2 hours)

## Output
Respond with ONLY a valid JSON object. No markdown fencing, no explanation, no other text.

{
  "project_name": "string — canonical name from registry, or UNKNOWN",
  "project_path": "string — full expanded path from registry",
  "task_type": "string — one of the task types above",
  "is_code_task": "boolean — true for code tasks, false for non-code",
  "branch_name": "string — suggested branch name for code tasks, empty for non-code",
  "summary": "string — one-line summary of the task",
  "enriched_task": "string — detailed actionable description with likely files and approach",
  "task_guardrails": ["array of strings — constraints extracted from the task text"],
  "estimated_complexity": "string — low, medium, or high"
}
```

- [ ] **Step 2: Create `prompts/execute.md`**

```markdown
You are an autonomous Claude Code agent executing a task in a codebase.

## Task
{{ENRICHED_TASK}}

## Task Type
{{TASK_TYPE}}

## Summary
{{SUMMARY}}

## Guardrails — YOU MUST FOLLOW THESE. VIOLATION IS NOT ACCEPTABLE.
{{MERGED_GUARDRAILS}}

## Instructions for Code Tasks
- You are working in: {{PROJECT_PATH}}
- Create and checkout a new branch named: {{BRANCH_NAME}}
- Make the necessary code changes to complete the task
- Run existing tests if a test suite exists (look for package.json scripts, pytest, go test, cargo test, etc.)
- If tests fail after your changes, fix them before committing
- Commit your changes with a clear, descriptive commit message
- Push the branch to origin: git push -u origin {{BRANCH_NAME}}
- If the push fails due to no remote, just commit locally and note it in your output

## Instructions for Non-Code Tasks
- Perform the analysis or review thoroughly
- Examine the codebase systematically
- Output your findings as a well-structured markdown report
- Include: summary, detailed findings, recommendations
- For security reviews: include severity ratings (Critical/High/Medium/Low)
- For code reviews: include specific file:line references

## General Rules
- Do NOT ask for clarification — make reasonable decisions and document assumptions
- Do NOT modify files outside this project directory
- Do NOT ignore the guardrails above under any circumstances
- If you encounter an obstacle you truly cannot resolve, describe it clearly in your output
- Be thorough but focused — do the task, nothing more
```

- [ ] **Step 3: Create `prompts/report.md`**

```markdown
You are a report generator for an automated Claude Code runner.

Given the execution log from a completed task, generate a clean, structured markdown report.

## Task Metadata
- Original Task: {{ORIGINAL_TASK}}
- Project: {{PROJECT_NAME}} ({{PROJECT_PATH}})
- Task Type: {{TASK_TYPE}}
- Branch: {{BRANCH_NAME}}
- Status: {{STATUS}}
- Duration: {{DURATION}}

## Execution Log
{{EXECUTION_LOG}}

## Report Structure for Code Tasks
Generate a report with these sections:

### Summary
What was done in 2-3 sentences.

### Changes Made
List of files modified, created, or deleted with brief description of each change.

### Approach
Brief explanation of the approach taken and why.

### Tests
Test results — what passed, what failed, or note if no tests were found.

### Risks
Any potential risks or side effects of the changes.

### Follow-up
Anything that should be done next but was out of scope for this task.

## Report Structure for Non-Code Tasks
Generate a report with these sections:

### Summary
Key findings in 2-3 sentences.

### Detailed Findings
Organized by category or severity. Include specific file:line references where applicable.

### Recommendations
Actionable next steps, prioritized by impact.

### Severity Ratings
For each finding, rate as: Critical / High / Medium / Low (where applicable).

## Rules
- Be concise but thorough
- Use markdown formatting with headers, lists, and code blocks
- Do NOT fabricate findings — only report what is evidenced in the execution log
- If the execution failed, document what went wrong and the likely root cause
- If the execution log is empty or minimal, note that the task produced no output

## Output
Respond with ONLY the markdown report content. No fencing, no preamble.
```

- [ ] **Step 4: Verify all three prompt files exist and are non-empty**

Run: `wc -l prompts/*.md`

Expected: Three files, each with 40+ lines.

- [ ] **Step 5: Commit**

```bash
git add prompts/
git commit -m "feat: add prompt templates for review, execute, and report phases

Three prompt files drive the Claude Code pipeline:
- review.md: task parsing, project matching, enrichment → JSON
- execute.md: task execution with guardrails (code or non-code)
- report.md: structured report generation from execution log"
```

---

### Task 3: Script Foundation — Shebang, Config Loading, Logging

**Files:**
- Create: `claude-runner.sh`

This task creates the script skeleton with configuration loading, logging functions, and environment validation.

- [ ] **Step 1: Create `claude-runner.sh` with foundation**

```bash
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
# Log levels: debug=0, info=1, warn=2, error=3
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
```

- [ ] **Step 2: Make script executable and verify it loads**

Run: `chmod +x claude-runner.sh && bash -n claude-runner.sh`

Expected: No output (syntax OK). The `-n` flag checks syntax without executing.

- [ ] **Step 3: Commit**

```bash
git add claude-runner.sh
git commit -m "feat: add script foundation — config loading, logging, env validation

Shebang, set -euo pipefail, config sourcing, log functions with
level filtering (debug/info/warn/error), environment validation
for MINIMAX_* vars, claude CLI, and jq."
```

---

### Task 4: Lock Management

**Files:**
- Modify: `claude-runner.sh`

- [ ] **Step 1: Add lock management functions after the duration helper**

Append to `claude-runner.sh`:

```bash
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
```

- [ ] **Step 2: Verify syntax**

Run: `bash -n claude-runner.sh`

Expected: No output (syntax OK).

- [ ] **Step 3: Commit**

```bash
git add claude-runner.sh
git commit -m "feat: add lock management — acquire, stale detection, release

Writes PID to lock file. Detects stale locks via LOCK_TIMEOUT and
dead processes via kill -0. Uses macOS stat -f '%m' for mtime."
```

---

### Task 5: Task Picking and Lifecycle Functions

**Files:**
- Modify: `claude-runner.sh`

- [ ] **Step 1: Add task lifecycle functions after lock management**

Append to `claude-runner.sh`:

```bash
# ── Task lifecycle ────────────────────────────────────────────────────
# Global state for current task (set by pick_task or parse_args)
CURRENT_TASK_FILE=""
CURRENT_TASK_NAME=""
TASK_IS_QUEUED=false  # true if picked from queue, false if specified on CLI

pick_task() {
    local pending_dir="$TASKS_DIR/pending"
    local oldest
    oldest="$(find "$pending_dir" -maxdepth 1 -name '*.txt' -type f -print 2>/dev/null | head -1)"

    if [ -z "$oldest" ]; then
        # Use find with sort by modification time if multiple files
        oldest="$(find "$pending_dir" -maxdepth 1 -name '*.txt' -type f -print0 2>/dev/null \
            | xargs -0 ls -t 2>/dev/null | tail -1)"
    fi

    if [ -z "$oldest" ]; then
        return 1  # No tasks
    fi

    CURRENT_TASK_FILE="$oldest"
    CURRENT_TASK_NAME="$(basename "$oldest" .txt)"
    TASK_IS_QUEUED=true
    log_info "Picked task: $CURRENT_TASK_NAME ($CURRENT_TASK_FILE)"
}

move_task() {
    local destination="$1"  # "in-progress", "completed", or "failed"
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
    # Called by trap handler — move task back to pending
    if [ "$TASK_IS_QUEUED" = true ] && [ -f "$CURRENT_TASK_FILE" ]; then
        local filename
        filename="$(basename "$CURRENT_TASK_FILE")"
        local pending_file="$TASKS_DIR/pending/$filename"

        # Only restore if currently in in-progress
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
    # Show last 20 lines of the most recent log
    tail -20 "$latest_log"
}
```

- [ ] **Step 2: Verify syntax**

Run: `bash -n claude-runner.sh`

Expected: No output (syntax OK).

- [ ] **Step 3: Commit**

```bash
git add claude-runner.sh
git commit -m "feat: add task lifecycle — pick, move, restore, list, status

Pick oldest .txt from pending/, move between lifecycle folders,
restore to pending on interrupt, list pending tasks with preview,
show last run status from logs."
```

---

### Task 6: Notification and Project Registry Functions

**Files:**
- Modify: `claude-runner.sh`

- [ ] **Step 1: Add notification and registry functions**

Append to `claude-runner.sh`:

```bash
# ── Notifications ─────────────────────────────────────────────────────
notify() {
    local status="$1"
    local summary="$2"
    local report_path="${3:-}"

    # Check notification config
    if [ "$status" = "success" ] && [ "$NOTIFY_ON_SUCCESS" != "true" ]; then
        return
    fi
    if [ "$status" = "failure" ] && [ "$NOTIFY_ON_FAILURE" != "true" ]; then
        return
    fi

    log_info "Notification: [$status] $summary"

    # Call notify hook if it exists and is executable
    if [ -x "$NOTIFY_HOOK" ]; then
        "$NOTIFY_HOOK" "$status" "$summary" "$report_path" 2>/dev/null || \
            log_warn "Notify hook returned non-zero exit code"
    fi
}

# ── Project registry ──────────────────────────────────────────────────
load_projects_registry() {
    # Returns the registry content as a formatted string for the review prompt
    local registry_file="$RUNNER_DIR/config/projects.conf"
    if [ ! -f "$registry_file" ]; then
        log_error "Projects registry not found: $registry_file"
        exit 1
    fi

    local registry=""
    while IFS='|' read -r name path aliases guardrails || [ -n "$name" ]; do
        # Skip comments and empty lines
        case "$name" in
            \#*|"") continue ;;
        esac
        # Expand ~ in path
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
    # Given a project name, return its per-project guardrails
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

    # Read file, skip comments and empty lines
    grep -v '^\s*#' "$guardrails_file" | grep -v '^\s*$' || true
}

merge_guardrails() {
    # Merge global + per-project + per-task guardrails
    local project_name="$1"
    local task_guardrails_json="$2"  # JSON array string

    local merged=""

    # Global guardrails
    local global
    global="$(load_global_guardrails)"
    if [ -n "$global" ]; then
        merged="## Global Guardrails
$global"
    fi

    # Per-project guardrails
    local project_gr
    project_gr="$(load_project_guardrails "$project_name")"
    if [ -n "$project_gr" ]; then
        merged="$merged

## Project-Specific Guardrails ($project_name)
$project_gr"
    fi

    # Per-task guardrails (from JSON array)
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
```

- [ ] **Step 2: Verify syntax**

Run: `bash -n claude-runner.sh`

Expected: No output (syntax OK).

- [ ] **Step 3: Commit**

```bash
git add claude-runner.sh
git commit -m "feat: add notification hook and project registry functions

Notify function with success/failure config. Registry loader formats
projects for the review prompt. Guardrail merger combines global,
per-project, and per-task guardrails into a single text block."
```

---

### Task 7: Claude Code Invocation Helper

**Files:**
- Modify: `claude-runner.sh`

- [ ] **Step 1: Add the Claude Code invocation wrapper**

Append to `claude-runner.sh`:

```bash
# ── Claude Code invocation ────────────────────────────────────────────
run_claude() {
    # Invoke Claude Code with MiniMax env vars
    # Args: prompt_text [working_dir]
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
```

- [ ] **Step 2: Verify syntax**

Run: `bash -n claude-runner.sh`

Expected: No output (syntax OK).

- [ ] **Step 3: Commit**

```bash
git add claude-runner.sh
git commit -m "feat: add Claude Code invocation wrapper

run_claude() sets all MINIMAX/ANTHROPIC env vars, invokes claude CLI
with --dangerously-skip-permissions -p --output-format, captures
output and exit code. Stderr goes to log file."
```

---

### Task 8: Phase 1 — Review & Enrich

**Files:**
- Modify: `claude-runner.sh`

- [ ] **Step 1: Add Phase 1 function**

Append to `claude-runner.sh`:

```bash
# ── Phase 1: Review & Enrich ─────────────────────────────────────────
REVIEW_JSON=""  # Global — set by phase_review, read by later phases

phase_review() {
    local task_file="$1"
    local task_content
    task_content="$(cat "$task_file")"

    log_info "Phase 1: Reviewing task..."

    # Load review prompt template
    local review_prompt_template
    review_prompt_template="$(cat "$PROMPTS_DIR/review.md")"

    # Load project registry
    local registry
    registry="$(load_projects_registry)"

    # Inject registry into prompt
    local review_prompt="${review_prompt_template//\{\{PROJECTS_REGISTRY\}\}/$registry}"

    # Combine prompt with task content
    local full_prompt="$review_prompt

## Task to Review
$task_content"

    # Run Claude Code
    local raw_output
    raw_output="$(run_claude "$full_prompt")" || {
        log_error "Phase 1: Claude Code failed"
        log_error "Output: $raw_output"
        return 1
    }

    log_debug "Phase 1 raw output: $raw_output"

    # Extract JSON — Claude may return it wrapped in the json output format
    # The --output-format json wraps the result, so extract the actual content
    local json_content
    json_content="$(echo "$raw_output" | jq -r '.result // .' 2>/dev/null || echo "$raw_output")"

    # Try to parse as JSON — if result is a string containing JSON, parse that
    if echo "$json_content" | jq -e 'type == "string"' >/dev/null 2>&1; then
        json_content="$(echo "$json_content" | jq -r '.')"
    fi

    # Validate JSON structure
    if ! echo "$json_content" | jq -e '.project_name' >/dev/null 2>&1; then
        log_error "Phase 1: Invalid JSON output from Claude"
        log_error "Content: $json_content"
        return 1
    fi

    REVIEW_JSON="$json_content"

    # Validate fields
    local project_name
    project_name="$(echo "$REVIEW_JSON" | jq -r '.project_name')"
    local project_path
    project_path="$(echo "$REVIEW_JSON" | jq -r '.project_path')"
    local task_type
    task_type="$(echo "$REVIEW_JSON" | jq -r '.task_type')"

    # Check for UNKNOWN project
    if [ "$project_name" = "UNKNOWN" ]; then
        log_error "Phase 1: Could not identify project from task description"
        return 1
    fi

    # Expand ~ in project_path
    project_path="${project_path/#\~/$HOME}"
    # Update the JSON with expanded path
    REVIEW_JSON="$(echo "$REVIEW_JSON" | jq --arg p "$project_path" '.project_path = $p')"

    # Verify project path exists
    if [ ! -d "$project_path" ]; then
        log_error "Phase 1: Project path does not exist: $project_path"
        return 1
    fi

    # Validate task type
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
```

- [ ] **Step 2: Verify syntax**

Run: `bash -n claude-runner.sh`

Expected: No output (syntax OK).

- [ ] **Step 3: Commit**

```bash
git add claude-runner.sh
git commit -m "feat: add Phase 1 — review and enrich task

Loads review prompt, injects project registry, sends to Claude Code,
parses JSON output, validates project_name (not UNKNOWN), project_path
(exists on disk), and task_type (recognized). Stores result in
REVIEW_JSON global."
```

---

### Task 9: Phase 2 — Execute

**Files:**
- Modify: `claude-runner.sh`

- [ ] **Step 1: Add Phase 2 function**

Append to `claude-runner.sh`:

```bash
# ── Phase 2: Execute ──────────────────────────────────────────────────
EXECUTE_OUTPUT=""  # Global — set by phase_execute, read by phase_report
EXECUTE_EXIT_CODE=0

phase_execute() {
    log_info "Phase 2: Executing task..."

    # Extract fields from REVIEW_JSON
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

    # Merge guardrails
    local merged_guardrails
    merged_guardrails="$(merge_guardrails "$project_name" "$task_guardrails_json")"

    # Load execute prompt template
    local execute_prompt
    execute_prompt="$(cat "$PROMPTS_DIR/execute.md")"

    # Replace placeholders
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

    # Run Claude Code in the project directory
    EXECUTE_OUTPUT="$(run_claude "$execute_prompt" "$project_path")" || {
        EXECUTE_EXIT_CODE=$?
        log_error "Phase 2: Claude Code failed with exit code $EXECUTE_EXIT_CODE"
        # Don't return — Phase 3 should still run on partial output
    }

    # Log output size
    local output_lines
    output_lines="$(echo "$EXECUTE_OUTPUT" | wc -l | tr -d ' ')"
    log_info "Phase 2 complete: $output_lines lines of output (exit code: $EXECUTE_EXIT_CODE)"
}
```

- [ ] **Step 2: Verify syntax**

Run: `bash -n claude-runner.sh`

Expected: No output (syntax OK).

- [ ] **Step 3: Commit**

```bash
git add claude-runner.sh
git commit -m "feat: add Phase 2 — execute task in project directory

Extracts fields from REVIEW_JSON, merges three-layer guardrails,
replaces placeholders in execute prompt template, runs Claude Code
in the project directory. Captures output even on failure so
Phase 3 can generate a diagnostic report."
```

---

### Task 10: Phase 3 — Report Generation

**Files:**
- Modify: `claude-runner.sh`

- [ ] **Step 1: Add Phase 3 function**

Append to `claude-runner.sh`:

```bash
# ── Phase 3: Report generation ────────────────────────────────────────
REPORT_PATH=""  # Global — set by phase_report

phase_report() {
    log_info "Phase 3: Generating report..."

    local task_content
    task_content="$(cat "$CURRENT_TASK_FILE" 2>/dev/null || echo "(task file unavailable)")"

    # Extract fields from REVIEW_JSON
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

    # Calculate duration
    local run_end_epoch
    run_end_epoch="$(date '+%s')"
    local duration_secs=$((run_end_epoch - RUN_START_EPOCH))
    local duration
    duration="$(format_duration $duration_secs)"

    # Determine status
    local status="success"
    if [ "$EXECUTE_EXIT_CODE" -ne 0 ]; then
        status="failure"
    fi

    # Load report prompt template
    local report_prompt
    report_prompt="$(cat "$PROMPTS_DIR/report.md")"

    # Extract execution log text from JSON output
    local execution_log
    execution_log="$(echo "$EXECUTE_OUTPUT" | jq -r '.result // .' 2>/dev/null || echo "$EXECUTE_OUTPUT")"
    if echo "$execution_log" | jq -e 'type == "string"' >/dev/null 2>&1; then
        execution_log="$(echo "$execution_log" | jq -r '.')"
    fi

    # Replace placeholders
    report_prompt="${report_prompt//\{\{ORIGINAL_TASK\}\}/$task_content}"
    report_prompt="${report_prompt//\{\{PROJECT_NAME\}\}/$project_name}"
    report_prompt="${report_prompt//\{\{PROJECT_PATH\}\}/$project_path}"
    report_prompt="${report_prompt//\{\{TASK_TYPE\}\}/$task_type}"
    report_prompt="${report_prompt//\{\{BRANCH_NAME\}\}/$branch_name}"
    report_prompt="${report_prompt//\{\{STATUS\}\}/$status}"
    report_prompt="${report_prompt//\{\{DURATION\}\}/$duration}"
    report_prompt="${report_prompt//\{\{EXECUTION_LOG\}\}/$execution_log}"

    # Run Claude Code for report generation
    local report_output
    report_output="$(run_claude "$report_prompt")" || {
        log_warn "Phase 3: Report generation failed"
        # Use raw execution output as fallback report
        report_output="# Task Report (auto-generated — report phase failed)

## Raw Execution Output
$execution_log"
    }

    # Extract report text from JSON
    local report_text
    report_text="$(echo "$report_output" | jq -r '.result // .' 2>/dev/null || echo "$report_output")"
    if echo "$report_text" | jq -e 'type == "string"' >/dev/null 2>&1; then
        report_text="$(echo "$report_text" | jq -r '.')"
    fi

    # Save report
    REPORT_PATH="$REPORTS_DIR/${RUN_TIMESTAMP}-${project_name}-${task_type}.md"
    echo "$report_text" > "$REPORT_PATH"
    log_info "Report saved: $REPORT_PATH"

    # Append summary to task file
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
```

- [ ] **Step 2: Verify syntax**

Run: `bash -n claude-runner.sh`

Expected: No output (syntax OK).

- [ ] **Step 3: Commit**

```bash
git add claude-runner.sh
git commit -m "feat: add Phase 3 — report generation from execution log

Assembles report prompt with task metadata and execution log, runs
Claude Code to generate structured report, saves to reports/ dir,
appends run summary to task file. Falls back to raw output if
report generation fails."
```

---

### Task 11: CLI Argument Parsing and Main Orchestration

**Files:**
- Modify: `claude-runner.sh`

- [ ] **Step 1: Add CLI parsing and main function**

Append to `claude-runner.sh`:

```bash
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
    # Initialize log file
    touch "$LOG_FILE"
    log_info "=== Claude Runner started ==="

    # Validate environment
    validate_environment

    # Acquire lock
    acquire_lock

    # Determine task source
    if [ -n "$SPECIFIC_TASK_FILE" ]; then
        # Specific file provided on CLI
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
        # Pick from queue
        if ! pick_task; then
            log_info "No pending tasks."
            notify "no-tasks" "No pending tasks in queue" ""
            release_lock
            exit 0
        fi
        # Move to in-progress
        move_task "in-progress"
    fi

    local final_status="success"
    local final_summary=""

    # ── Phase 1: Review ───────────────────────────────────────────────
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

    # ── Dry run exit ──────────────────────────────────────────────────
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

        # Restore task if it was from the queue
        if [ "$TASK_IS_QUEUED" = true ]; then
            restore_task
        fi

        release_lock
        exit 0
    fi

    # ── Phase 2: Execute ──────────────────────────────────────────────
    phase_execute

    # ── Phase 3: Report ───────────────────────────────────────────────
    phase_report

    # ── Post-processing ───────────────────────────────────────────────
    if [ "$EXECUTE_EXIT_CODE" -ne 0 ]; then
        final_status="failure"
        final_summary="Task '$CURRENT_TASK_NAME' failed on $project_name: $summary"
        move_task "failed"
    else
        final_status="success"
        final_summary="Task '$CURRENT_TASK_NAME' completed on $project_name: $summary"
        move_task "completed"
    fi

    # Calculate duration
    local run_end_epoch
    run_end_epoch="$(date '+%s')"
    local duration_secs=$((run_end_epoch - RUN_START_EPOCH))
    local duration
    duration="$(format_duration $duration_secs)"

    log_info "=== Claude Runner finished: $final_status ($duration) ==="

    # Notify
    notify "$final_status" "$final_summary" "$REPORT_PATH"

    # Release lock
    release_lock

    if [ "$final_status" = "failure" ]; then
        exit 1
    fi
    exit 0
}

# ── Entry point ───────────────────────────────────────────────────────
parse_args "$@"
main
```

- [ ] **Step 2: Verify complete script syntax**

Run: `bash -n claude-runner.sh`

Expected: No output (syntax OK).

- [ ] **Step 3: Test `--help` flag**

Run: `./claude-runner.sh --help`

Expected output showing usage, options, and description.

- [ ] **Step 4: Test `--list` flag with empty queue**

Run: `./claude-runner.sh --list`

Expected: `Pending tasks: 0`

- [ ] **Step 5: Test `--status` with no prior runs**

Run: `./claude-runner.sh --status`

Expected: `No runs recorded yet.`

- [ ] **Step 6: Commit**

```bash
git add claude-runner.sh
git commit -m "feat: add CLI parsing, signal traps, and main orchestration

CLI flags: --dry-run, --list, --status, --help, [task-file].
SIGINT/SIGTERM trap restores task to pending and releases lock.
Main function orchestrates: validate → lock → pick/assign →
Phase 1 → Phase 2 → Phase 3 → post-process → notify → unlock."
```

---

### Task 12: Create Sample Task and Dry-Run Verification

**Files:**
- Create: `tasks/pending/sample-task.txt`

- [ ] **Step 1: Add a sample project to the registry**

Pick a real local repo on the machine. First check what exists:

Run: `ls ~/Development/ 2>/dev/null || ls ~/Projects/ 2>/dev/null || echo "No standard dev directory found"`

If a real project is found, add it to `config/projects.conf`. Otherwise, create a dummy project for testing:

```bash
mkdir -p /tmp/claude-runner-test-project
cd /tmp/claude-runner-test-project
git init
echo '# Test Project' > README.md
git add README.md
git commit -m "initial commit"
```

Then add to `config/projects.conf`:

```
test-project|/tmp/claude-runner-test-project|test,dummy|do not delete README.md
```

- [ ] **Step 2: Create a sample task file**

Write to `tasks/pending/sample-task.txt`:

```
Add a .gitignore file to the test project with common entries for Node.js projects
```

- [ ] **Step 3: Run dry-run to verify Phase 1 works**

Run: `./claude-runner.sh --dry-run`

Expected: JSON output showing:
- `project_name`: `test-project`
- `project_path`: `/tmp/claude-runner-test-project`
- `task_type`: `feature` or `build`
- `is_code_task`: `true`
- `branch_name`: something like `feat/add-gitignore`
- Merged guardrails displayed

Verify the task file was NOT moved (still in `tasks/pending/`).

- [ ] **Step 4: Verify log was created**

Run: `ls logs/`

Expected: A log file named with today's timestamp.

- [ ] **Step 5: Commit**

```bash
git add config/projects.conf tasks/pending/sample-task.txt
git commit -m "test: add sample project and task for dry-run verification"
```

---

### Task 13: Full Integration Test

**Files:** None (test run only)

- [ ] **Step 1: Run the full pipeline on the sample task**

Run: `./claude-runner.sh`

Watch the output. It should:
1. Pick `sample-task.txt` from pending
2. Move it to in-progress
3. Phase 1: identify test-project, classify as feature/build
4. Phase 2: create branch, add .gitignore, commit, push (push may fail — that's OK for a local-only repo)
5. Phase 3: generate report
6. Move task to completed (or failed if push fails — adjust guardrails if needed)

- [ ] **Step 2: Verify task moved to completed or failed**

Run: `ls tasks/completed/ tasks/failed/`

Expected: `sample-task.txt` in one of these directories.

- [ ] **Step 3: Verify report was generated**

Run: `ls reports/`

Expected: A report file like `2026-04-17-HHMMSS-test-project-feature.md`.

- [ ] **Step 4: Read the generated report**

Run: `cat reports/*.md`

Verify it has the expected sections (Summary, Changes Made, etc.)

- [ ] **Step 5: Verify the completed task file has appended summary**

Run: `cat tasks/completed/sample-task.txt` or `cat tasks/failed/sample-task.txt`

Expected: Original task text followed by `--- RUNNER OUTPUT ... ---` block.

- [ ] **Step 6: Check notification log**

Run: `cat logs/notifications.log`

Expected: A line with the run status and summary.

---

### Task 14: Cron Setup

**Files:** None (system configuration)

- [ ] **Step 1: Create cron entry**

Add a cron job to run every 30 minutes:

```bash
crontab -l 2>/dev/null > /tmp/crontab_backup || true
(crontab -l 2>/dev/null; echo "*/30 * * * * /Users/thotas/ClaudeRunner/claude-runner.sh >> /Users/thotas/ClaudeRunner/logs/cron.log 2>&1") | crontab -
```

- [ ] **Step 2: Verify cron entry**

Run: `crontab -l | grep claude-runner`

Expected: The cron entry created above.

- [ ] **Step 3: Verify cron runs (optional)**

Drop a task in `tasks/pending/` and wait for the next cron trigger, or manually test with:

Run: `./claude-runner.sh --list`

Confirm pending count, then wait for cron to process it.

---

### Task 15: Final Cleanup and Documentation Commit

**Files:**
- Modify: `docs/superpowers/specs/2026-04-17-claude-runner-design.md` (update status to Final)

- [ ] **Step 1: Update spec status**

Change `**Status:** Draft` to `**Status:** Implemented` in the design spec.

- [ ] **Step 2: Final commit**

```bash
git add -A
git commit -m "docs: mark design spec as implemented

All components built and verified: three-phase pipeline, config files,
prompt templates, CLI with --dry-run/--list/--status, lock management,
signal trapping, notification hooks, cron setup."
```
