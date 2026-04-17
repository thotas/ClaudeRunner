# Claude Runner

Automated task executor powered by Claude Code. Drop a plain-text task file into a folder, and Claude Runner picks it up, figures out which project it belongs to, executes it, and generates a report.

## How It Works

```
tasks/pending/fix-login-bug.txt
        │
        ▼
┌──────────────────────┐
│  Phase 1: Review     │  Identify project, classify task, enrich with details
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  Phase 2: Execute    │  Run Claude Code in the project directory
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  Phase 3: Report     │  Generate structured report from execution log
└──────────┬───────────┘
           ▼
tasks/completed/fix-login-bug.txt  +  reports/2026-04-17-payments-app-bugfix.md
```

**Three-phase pipeline:**
1. **Review** — Claude Code analyzes the free-text task, matches it to a project in your registry, classifies the task type, and enriches it with actionable details
2. **Execute** — Claude Code runs in the project directory with three-layer guardrails (global + per-project + per-task). Code tasks get a branch, commit, and push. Non-code tasks produce analysis output.
3. **Report** — Claude Code generates a polished markdown report from the execution log

## Quick Start

```bash
# 1. Add your projects to the registry
vim config/projects.conf

# 2. Drop a task
echo "Fix the login timeout bug in the payments app" > tasks/pending/fix-login.txt

# 3. Dry run (Phase 1 only — see what Claude would do)
./claude-runner.sh --dry-run

# 4. Run for real
./claude-runner.sh
```

## Project Registry

Edit `config/projects.conf` to register your local repos:

```
# Format: name|path|aliases|guardrails
payments-app|~/Development/payments-app|payments,billing|do not modify database migrations
website|~/Development/company-site|site,frontend|do not delete public assets
backend-api|~/Development/backend-api|api,server|
```

Claude matches free-text task descriptions against project names and aliases. No structured format needed in task files.

## Task Types

| Type | Code Task | What Happens |
|------|-----------|-------------|
| `bugfix` | Yes | Branch, fix, test, commit, push |
| `feature` | Yes | Branch, implement, test, commit, push |
| `refactor` | Yes | Branch, restructure, test, commit, push |
| `testing` | Yes | Branch, write tests, commit, push |
| `build` | Yes | Branch, build component, commit, push |
| `code-review` | No | Analyze code, produce report |
| `security-review` | No | Audit for vulnerabilities, produce report |
| `research` | No | Investigate, produce report |
| `docs` | No | Documentation analysis/report |

## Guardrails

Three layers of protection, merged at execution time:

1. **Global** (`config/guardrails.conf`) — applied to every task
2. **Per-project** (`config/projects.conf` guardrails field) — project-specific rules
3. **Per-task** — extracted from the task description by Claude during review

Default global guardrails:
- No force-push
- No deleting files unless explicitly required
- No modifying CI/CD pipelines
- Stay within the project directory
- No modifying `.env` files or secrets
- Always create a new branch (never commit to main)
- No installing dependencies unless required

## CLI Usage

```bash
./claude-runner.sh                     # Pick next pending task
./claude-runner.sh task.txt            # Run a specific file (skips queue)
./claude-runner.sh --dry-run           # Phase 1 only — preview without executing
./claude-runner.sh --dry-run task.txt  # Dry run a specific file
./claude-runner.sh --list              # List pending tasks
./claude-runner.sh --status            # Show last run status
./claude-runner.sh --help              # Show help
```

## Cron Setup

```bash
# Run every 30 minutes
*/30 * * * * /path/to/ClaudeRunner/claude-runner.sh >> /path/to/ClaudeRunner/logs/cron.log 2>&1
```

## Directory Structure

```
ClaudeRunner/
├── claude-runner.sh          # Main script
├── config/
│   ├── runner.conf           # Settings (paths, timeouts, logging)
│   ├── projects.conf         # Project registry
│   ├── guardrails.conf       # Global guardrails
│   └── notify.sh             # Notification hook (customize this)
├── tasks/
│   ├── pending/              # Drop .txt files here
│   ├── in-progress/          # Currently executing
│   ├── completed/            # Done (with appended summary)
│   └── failed/               # Failed (with error info)
├── reports/                  # Generated reports
├── logs/                     # Per-run logs
└── prompts/
    ├── review.md             # Phase 1 prompt
    ├── execute.md            # Phase 2 prompt template
    └── report.md             # Phase 3 prompt template
```

## Configuration

The runner uses Claude Code pointed at a configurable API endpoint. Set these environment variables:

```bash
export MINIMAX_BASE_URL="https://api.your-provider.com/anthropic"
export MINIMAX_AUTH_TOKEN="your-token"
export MINIMAX_MODEL="your-model"
```

Edit `config/runner.conf` to customize paths, lock timeout, log level, and notification settings.

## Notifications

The runner calls `config/notify.sh` after each run with:

```bash
./config/notify.sh <status> <summary> <report_path>
# status: "success" | "failure" | "no-tasks"
```

Customize this script to send notifications via WhatsApp, Telegram, Slack, or anything else.

## Requirements

- Bash 3.2+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 2.x
- `jq` for JSON parsing
- `gh` (optional, for GitHub integration)

## License

MIT
