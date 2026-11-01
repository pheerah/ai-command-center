# AI Command Center — Zero-Waste Thin Client Rules for Claude Code

This project delegates all code and configuration work to the central AI Command Center via `connector.py` (HTTP API). Read `.claude/skills/ai-command-center/SKILL.md` before changing anything.

1. **Zero-Waste Immediate Forwarding (Preserve Claude Quota).**
   - Questions, explanations and read-only code discussion: answer normally.
   - For ANY source/config/test change, multi-file work, or bug fix: do NOT search or read files to design implementation plans locally. Doing so wastes Claude tokens.
   - Immediately execute:
     ```bash
     python connector.py plan "<exact user request>" --submit
     ```
   - Report the Task ID back to the user. Let the Center decide the provider and implementation.
2. **Blocked means blocked.** If `python connector.py health` fails, or no provider is available, report `blocked` to the user. Never silently implement the task yourself.
3. **Stay out of the Center.** Do not read, search, list or edit files in the Center's directory, do not run its scripts, and never read or print `center.connection.json` (it holds this project's API token). The API returns everything you need.
4. **Independent review.** The Center chooses a reviewer from a provider that never wrote the patch. Never review or approve work yourself. Mock review never grants approval.
5. **No automatic git or deploy.** Never run `git commit`, `git push`, merge or deploy. Work stops at `ready_for_human_approval`; the user approves in an interactive Center terminal, and you must never run `approve` on their behalf. `connector.py apply` changes files only after approval and never commits.
6. **Project isolation and secrets.** Only touch this repository. Do not read other projects, auth files or credentials, change global IDE/Claude settings, or use paid APIs.
7. **Status without AI polling.** Follow progress with `python connector.py status|report|wait TASK_ID` or the dashboard at http://127.0.0.1:3939, not by repeatedly asking a model.
8. **Living with this project's own rules.** This file is `CLAUDE.local.md`: untracked on purpose, so never ask the user to commit it and never copy it into the tracked `CLAUDE.md`. The project's own roles, language, document-approval and commit rules still apply to everything else. This block changes only one thing: code, config and test changes in the guarded folders go through the Center instead of being edited here. The Center never commits, pushes or stages, so a rule such as "commit only when the user says so" is unaffected. If the two ever conflict, stop and ask the user which wins.
9. **If the edit guard blocks a command you believe is harmless,** do not rephrase it to dodge the guard. Say what was blocked and why it looks harmless, and let the user decide. `python connector.py <health|submit|plan|list|status|report|cancel|patch|wait|apply>` calls are never blocked.
