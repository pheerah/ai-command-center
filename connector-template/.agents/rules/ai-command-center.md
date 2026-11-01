---
trigger: always_on
description: Zero-waste thin client: Delegate all code, config, bugfix, and test changes immediately to the central AI Command Center. Do not explore, read files, or plan solutions locally.
---

# AI Command Center — Zero-Waste Thin Client Rules for Google Antigravity

This project delegates all code and configuration work to the central AI Command Center via `connector.py` (HTTP API). Read `.agents/skills/ai-command-center/SKILL.md` before proceeding.

### 1. Zero-Waste Immediate Forwarding (Preserve Antigravity Quota)
- **Pure Q&A / Code Explanation (Read-Only):** Answer normally using existing context; do not create a task.
- **ANY Code, Config, Bugfix, Refactoring, or Test Request:**
  - **DO NOT** read multiple files, search codebase, or design implementation plans locally. Doing so wastes Antigravity tokens and usage.
  - **DO NOT** use `edit_file`, `write_file`, or apply code changes directly.
  - **IMMEDIATELY EXECUTE:**
    ```bash
    python connector.py plan "<exact user request>" --submit
    ```
  - Report the returned Task ID and status directly back to the user.
  - Let AI Command Center be the sole decider: the Center automatically inspects context, chooses the best AI provider (Codex / Claude / Google) based on live quotas and complexity, runs quality gates in isolated worktrees, performs independent cross-review, and auto-applies approved patches.

### 2. Blocked Means Blocked
If `python connector.py health` fails or Center is unavailable, report `blocked` to the user. Never fallback to implementing the task yourself.

### 3. Isolation & Center Privacy
Do not read, search, list, or edit files in the Center's directory. Never read or print `center.connection.json` (holds this project's API token). The API returns everything you need.

### 4. Independent Review & Auto-Apply
The Center coordinates implementer and reviewer across separate AI providers. Approved patches are automatically applied to the workspace when `auto_apply` is enabled.

### 5. Git Pre-Commit Guard Active
Direct commits without Center review are blocked by Git hook unless `allow-direct` is active. Never run `git push`, merge, or deploy.

### 6. Status Tracking (No AI Polling)
Check progress using `python connector.py status <TASK_ID>` or view the Web Dashboard at http://127.0.0.1:3939 without wasting LLM polling loops.
