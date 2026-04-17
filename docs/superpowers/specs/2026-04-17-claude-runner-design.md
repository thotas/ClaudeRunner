# Claude Runner — Design Spec

**Date:** 2026-04-17
**Status:** Draft
**Author:** thotas + Claude

## Overview

Claude Runner is a single Bash script orchestrator that processes task files from a queue, uses Claude Code to analyze and execute them against local repositories, and produces reports and notifications. It runs unattended via cron or manually from the command line.

## Goals

- Process free-text task files with zero structured formatting required
- Automatically identify the target project, classify the task, and enrich it with actionable details
- Execute code tasks (bugfix, feature, refactor, testing) with commit+push
- Execute non-code tasks (code review, security review, research) with report output
- Enforce three-layer guardrails (global, per-project, per-task)
- Produce a polished report for every task run
- Notify on success and failure via a pluggable hook

## Non-Goals

- PR creation (single-person team — commit+push is sufficient)
- Parallel task execution (one task per run)
- Cloning repos (all projects are pre-cloned locally)
- Interactive mode (fully unattended)

---

## Directory Structure

```
~/ClaudeRunner/
├── claude-runner.sh              # Main orchestrator script (executable)
├── config/
│   ├── runner.conf               # Global settings
│   ├── projects.conf             # Project registry (name → path mapping)
│   ├── guardrails.conf           # Global guardrails (applied to every task)
│   └── notify.sh                 # Optional notification hook script
├── tasks/
│   ├── pending/                  # Drop .txt files here
│   ├── in-progress/              # Task currently being worked on
│   ├── completed/                # Successfully finished tasks
│   └── failed/                   # Failed tasks with error logs
├── reports/                      # Output from all tasks (code and non-code)
│   └── YYYY-MM-DD-HHMMSS-<project>-<type>.md
├── logs/
│   └── YYYY-MM-DD-HHMMSS.log    # Per-run execution logs
├── prompts/
│   ├── review.md                 # System prompt for Phase 1 (review & enrich)
│   ├── execute.md                # System prompt template for Phase 2 (execution)
│   └── report.md                 # System prompt for Phase 3 (report generation)
└── docs/
    └── superpowers/specs/        # Design documents
```

---

## Configuration

### `config/runner.conf`

```bash
# Directories (relative to ClaudeRunner/)
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

### `config/projects.conf`

Pipe-delimited registry mapping project names to local paths, with aliases and per-project guardrails.

```bash
# Format: name|path|aliases|guardrails
payments-app|~/Development/payments-app|payments,billing|do not modify database migrations
website|~/Development/company-site|site,frontend|do not delete public assets
backend-api|~/Development/backend-api|api,server|
mobile-app|~/Development/mobile-app|mobile,ios,android|do not modify signing configs
```

Fields:
- **name**: canonical project name
- **path**: absolute or `~`-relative path to the local repo
- **aliases**: comma-separated alternative names for fuzzy matching
- **guardrails**: per-project guardrails (pipe-separated from other fields)

### `config/guardrails.conf`

Plain text file, one guardrail per line. Applied to every task execution.

```
Do not force-push to any branch
Do not delete files unless the task explicitly requires it
Do not modify CI/CD pipelines or GitHub Actions workflows
Stay within the identified project directory only
Do not modify .env files or secrets
Create a new branch for all code changes, never commit directly to main
Do not install new dependencies unless the task requires it
```

---

## Three-Phase Pipeline

### Phase 1: Review & Enrich

**Purpose:** Parse free-text task, identify project, classify task type, extract guardrails, produce structured execution plan.

**Input:** Raw task file contents + project registry
**Output:** JSON object written to a temp file

```json
{
  "project_name": "payments-app",
  "project_path": "/Users/thotas/Development/payments-app",
  "task_type": "bugfix",
  "is_code_task": true,
  "branch_name": "fix/login-timeout-bug",
  "summary": "Fix login session timeout - sessions expire after 2 minutes instead of configured 30 minutes",
  "enriched_task": "The login timeout bug is likely in the session middleware. Check session configuration, cookie expiry settings, and any hardcoded timeout values. Look at auth/middleware.ts and config/session.ts. Verify the fix with existing test suite.",
  "task_guardrails": [],
  "estimated_complexity": "low"
}
```

**Invocation:**

```bash
ANTHROPIC_BASE_URL="$MINIMAX_BASE_URL" \
ANTHROPIC_AUTH_TOKEN="$MINIMAX_AUTH_TOKEN" \
ANTHROPIC_API_KEY="" \
ANTHROPIC_MODEL="$MINIMAX_MODEL" \
ANTHROPIC_DEFAULT_SONNET_MODEL="$MINIMAX_MODEL" \
ANTHROPIC_DEFAULT_OPUS_MODEL="$MINIMAX_MODEL" \
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
claude --dangerously-skip-permissions \
  -p "$review_prompt" \
  --output-format json
```

**Validation after Phase 1:**
- `project_name` must not be `"UNKNOWN"`
- `project_path` must exist on disk
- `project_path` must match a registry entry
- `task_type` must be a recognized type

If validation fails, the task moves to `failed/` with the reason logged.

### Phase 2: Execute

**Purpose:** Perform the actual work in the project directory.

**Input:** Enriched task + merged guardrails (global + per-project + per-task)
**Working directory:** The project path from Phase 1

**For code tasks:**
1. Create and checkout a new branch (`branch_name` from Phase 1)
2. Perform the work
3. Run existing tests if a test suite is present
4. Commit changes with a descriptive message
5. Push the branch to origin

**For non-code tasks:**
1. Perform the analysis/review
2. Output findings as structured markdown

**Invocation:** Same env vars as Phase 1, but `cd`'d into the project directory. The prompt is assembled by replacing placeholders in `prompts/execute.md` with values from Phase 1.

### Phase 3: Report Generation

**Purpose:** Generate a polished, structured report from the execution log.

**Input:** Execution log from Phase 2 + task metadata from Phase 1
**Output:** Markdown report

**For code tasks, the report includes:**
- Summary of changes
- Files modified/created/deleted
- Approach taken
- Test results
- Risks and side effects
- Follow-up items

**For non-code tasks, the report includes:**
- Key findings summary
- Detailed findings organized by category/severity
- Actionable recommendations (prioritized)
- Severity ratings (Critical/High/Medium/Low)

The report is saved to `reports/` and a summary is appended to the completed/failed task file.

Phase 3 always runs, even if Phase 2 failed — a failed execution still produces a useful diagnostic report.

---

## Task Lifecycle

```
pending/ ──→ in-progress/ ──→ completed/
                           └──→ failed/
```

### Flow

1. **Lock check** — exit if another run is active (stale locks auto-released after `LOCK_TIMEOUT`)
2. **Pick task** — select oldest `.txt` from `tasks/pending/` (by filesystem modification time)
3. **Move to in-progress** — `mv tasks/pending/task.txt tasks/in-progress/`
4. **Start log** — create `logs/YYYY-MM-DD-HHMMSS.log`
5. **Phase 1: Review** — analyze task, validate output
6. **Phase 2: Execute** — do the work
7. **Phase 3: Report** — generate report from execution log
8. **Post-processing:**
   - Save report to `reports/`
   - Append run summary to task file
   - Move task to `completed/` or `failed/`
   - Call notification hook
9. **Release lock** — remove lock file, exit

### Task File After Completion

The original task text is preserved, with a runner summary appended:

```
Fix the login timeout bug in the payments app

--- RUNNER OUTPUT (2026-04-17 14:30:22) ---
Status: completed
Project: payments-app (~/Development/payments-app)
Task type: bugfix
Branch: fix/login-timeout-bug
Duration: 3m 42s
Report: reports/2026-04-17-143022-payments-app-bugfix.md
Log: logs/2026-04-17-143022.log
```

---

## Manual Run Modes

```bash
# Pick next pending task from queue
./claude-runner.sh

# Run a specific task file (skips queue, doesn't move the file between folders)
./claude-runner.sh path/to/task.txt

# Dry run — Phase 1 only, shows review output without executing
./claude-runner.sh --dry-run

# Dry run a specific file
./claude-runner.sh --dry-run path/to/task.txt

# List pending tasks
./claude-runner.sh --list

# Show status of last run
./claude-runner.sh --status
```

The `--dry-run` flag runs Phase 1 only and displays the parsed JSON — useful for verifying project matching and task classification before committing to execution.

---

## Notification Hook

### Interface

The runner calls `config/notify.sh` (if it exists and is executable) with three arguments:

```bash
./config/notify.sh <status> <summary> <report_path>
```

| Argument | Values | Description |
|---|---|---|
| `status` | `success`, `failure`, `no-tasks` | Outcome of the run |
| `summary` | string | One-line description of what happened |
| `report_path` | file path or empty | Path to the full report (empty for `no-tasks`) |

The runner does not care what the hook does — WhatsApp, Telegram, email, Slack, just a log file, whatever.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| No pending tasks | Log, notify with `no-tasks`, exit 0 |
| Lock file exists (fresh) | Log "another run active", exit 0 |
| Lock file exists (stale > LOCK_TIMEOUT) | Remove stale lock, proceed |
| Phase 1 fails (Claude error) | Move to `failed/`, log, notify, exit 1 |
| Phase 1 returns UNKNOWN project | Move to `failed/`, log "unresolved project", notify, exit 1 |
| Project path doesn't exist on disk | Move to `failed/`, log "project path missing", notify, exit 1 |
| Phase 2 fails (Claude error) | Move to `failed/`, still run Phase 3 on partial output, notify, exit 1 |
| Phase 2 succeeds but push fails | Move to `failed/`, log "push failed", notify, exit 1 |
| Phase 3 fails (report generation) | Task status based on Phase 2, log warning, raw log preserved, notify |
| Script interrupted (SIGTERM/SIGINT) | Trap handler: move task back to `pending/`, release lock, exit |

---

## Claude Code Invocation

All three phases use the same environment variable pattern:

```bash
ANTHROPIC_BASE_URL="$MINIMAX_BASE_URL" \
ANTHROPIC_AUTH_TOKEN="$MINIMAX_AUTH_TOKEN" \
ANTHROPIC_API_KEY="" \
ANTHROPIC_MODEL="$MINIMAX_MODEL" \
ANTHROPIC_DEFAULT_SONNET_MODEL="$MINIMAX_MODEL" \
ANTHROPIC_DEFAULT_OPUS_MODEL="$MINIMAX_MODEL" \
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
claude --dangerously-skip-permissions \
  -p "$prompt" \
  --output-format json
```

This routes all API calls through the MiniMax endpoint using the MiniMax model, with permissions bypassed for unattended execution.

---

## Prompt Templates

Three prompt files in `prompts/`:

### `review.md` — Phase 1

Instructs Claude to parse free-text, match against project registry, classify task type, extract guardrails, enrich with actionable detail, and output structured JSON. The project registry is injected as context.

### `execute.md` — Phase 2

Template with placeholders (`{{ENRICHED_TASK}}`, `{{TASK_TYPE}}`, `{{MERGED_GUARDRAILS}}`, `{{PROJECT_PATH}}`, `{{BRANCH_NAME}}`) replaced by the script at runtime. Contains task-type-specific instructions for code tasks (branch, work, test, commit, push) and non-code tasks (analyze, output markdown).

### `report.md` — Phase 3

Instructs Claude to generate a structured markdown report from the execution log. Includes task metadata as context. Different report structures for code vs non-code tasks.

---

## Dependencies

- `bash` (4.0+)
- `claude` CLI (2.x) at `/opt/homebrew/bin/claude`
- `jq` for JSON parsing
- `date`, `mv`, `cat`, `mktemp` — standard Unix tools
- Environment variables: `MINIMAX_BASE_URL`, `MINIMAX_AUTH_TOKEN`, `MINIMAX_MODEL`

---

## Future Considerations (Out of Scope)

- Batch sequential processing (process all pending tasks in one run)
- Parallel execution across different projects
- PR creation workflow
- Web dashboard for task status
- Task priority/ordering beyond filesystem time
- Webhook endpoint for remote task submission
