# ClaudeRunner Field Observations — Phase 2

**Date:** 2026-05-13
**Context:** Running 8 test projects sequentially via ClaudeRunner. Observing ClaudeRunner behavior in real work.

---

## Observations

### ✅ What's Working
- `run_claude()` env pattern is solid
- 3-phase pipeline (Review → Execute → Report) is good architecture
- Branch-per-project pattern keeps main clean

### 🔴 Critical Issues Found

#### 1. Projects as embedded git repos (HIGH)
Every project added to `projects/` contains its own `.git/` directory. Git detects these as embedded repositories and refuses to commit:
```
fatal: embedded git repository: .git/modules/...
```
**Fix needed:** ClaudeRunner should `rm -rf .git` from any project directory before adding to index.

**Pattern:** Before `git add projects/X/`, run: `find projects/X/ -name ".git" -type d -exec rm -rf {} + 2>/dev/null; true`

#### 2. Claude Code invocation undocumented (MEDIUM)
ClaudeRunner's `run_claude()` uses a specific bash subshell pattern that doesn't appear in any README. Direct invocation of `claude -p "..."` fails silently without the full env block. The working pattern:
```bash
source config/runner.conf && \
export ANTHROPIC_BASE_URL="$MINIMAX_BASE_URL" && \
export ANTHROPIC_API_KEY="..." && \
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 && \
claude --dangerously-skip-permissions -p "..."
```
**Fix needed:** Document this in README and/or make `run_claude()` callable as a standalone function.

#### 3. Subagent timeout on real work (HIGH)
When Claude Code does real work (creates files, runs tests), the subagent context times out before Claude Code finishes. The work completes but the subagent never returns. This happened on Projects 1 and 2 — had to manually recover files.

**Fix needed:** Either (a) use `notify_on_complete` pattern instead of waiting, or (b) have subagent launch Claude Code in background and exit immediately.

#### 4. No retry-until-green (MEDIUM)
Failed tests require manual re-run. Claude Code might produce a broken build on first attempt. No auto-retry loop.

**Fix needed:** Phase 3 improvement: retry-until-green for builds.

---

## After Each Project - Fixes Applied

| Project | Issues Fixed |
|---------|-------------|
| P1: cron-watchdog | Removed embedded `.git/` from project dir |
| P2: wiki-scout | Same |
| P3: ta-batch-runner | ✓ Merged PR #1. 34 tests passing. Embedded .git/ stripping worked — no errors. |
| P4: skills-hub-cli | ✓ Merged PR #2. 46 tests passing. CLI with subcommands (list/search/view/categories/config). |
| P5: report-card-generator | ✓ Merged PR #3. 40 tests passing. JSON→dark HTML with anti-AI slop styling. |
| P6: bookmark-archiver | ✓ Merged PR #4. 21 tests passing. URL→markdown with auto-tagging and dedup. |
| P7: env-audit-cli | ✓ Merged PR #5. 23 tests passing. .env auditor with missing/stale/duplicate detection. |
| P8: voice-transcript-processor | ✓ Merged PR #6. 19 tests passing. VTT/SRT/text parsing with speaker splitting and action item extraction. |

## Phase 3 Improvements ✓

Implemented the top 3 improvements based on field observations:

### 1. Retry-until-green
- `run_claude()` now retries up to `RETRY_MAX` (default 3) times with exponential backoff
- Configurable via env vars or `config/runner.conf`
- Logs each attempt for observability

### 2. Project Pre-Flight (.git strip)
- `phase_execute()` now strips `.git/` directories from project_path before running
- `prompts/execute.md` instructs Claude Code to do the same before committing
- Prevents "fatal: embedded git repository" errors that hit every project in Phase 2

### 3. Self-Test Suite
- `tests/test_claude_runner.py` — 18 tests covering ClaudeRunner itself
- Tests: script existence, config loading, retry logic, pre-flight, git integration, end-to-end
- All 18 tests passing

---

## Phase 3 Complete ✓

All 8 projects built and merged to main:
1. cron-watchdog — 22 tests
2. wiki-scout — 18 tests
3. ta-batch-runner — 34 tests
4. skills-hub-cli — 46 tests
5. report-card-generator — 40 tests
6. bookmark-archiver — 21 tests
7. env-audit-cli — 23 tests
8. voice-transcript-processor — 19 tests
**Total: 223 tests**

ClaudeRunner improvements:
- retry-until-green with exponential backoff
- project pre-flight .git strip
- self-test suite (18 tests)

---

## Phase 3 Priorities (based on field observations)

1. **Retry-until-green** — auto-retry failed builds before declaring failure
2. **Project pre-flight check** — strip `.git/` directories from projects before git add
3. **Self-test suite** — test ClaudeRunner itself (catches the embedded repo issue)
4. **Structured metadata** — standardize project output format

---

*Last updated: 2026-05-13 07:20 AM Pacific*