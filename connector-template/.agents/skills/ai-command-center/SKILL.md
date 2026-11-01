---
name: ai-command-center
description: Use for any source/config/test change in this project. Sends the task to the central AI Command Center over its HTTP API (python connector.py submit/status/report/wait/patch/apply). Not needed for questions or read-only code discussion.
---

# Project connector (HTTP API only)

Use `python connector.py` at the project root. It talks to the Center over HTTP with a per-project token from `center.connection.json`. Never open, read, search or edit anything inside the Center's own directory, never run the Center's Python files, and never read `center.connection.json` or print the token. Everything you need comes back through the connector.

## Request classification
- Questions, explanations and read-only code discussion: answer normally; no task needed.
- Any source/config/test change, multi-file work or QA review: check `health`, then `submit` a scoped task with acceptance criteria.
- Center unreachable or no provider available: report `blocked` to the user. Never silently implement the task yourself.

## How a task runs
Run `python connector.py plan "<Requirement>" --submit`. The Adaptive Planner automatically classifies whether it is simple (Fast Path) or complex (Council Path), breaks down subtasks/DAG, chooses the model tier and effort, and queues it directly into the Center!

You can also submit manually if explicit scope and acceptance criteria are already known:
```powershell
python connector.py health
python connector.py plan "Natural language requirement here" --submit
python connector.py submit --title 'Describe task' --prompt 'Requirement' --scope src --scope tests --accept 'Required checks pass' --complexity 2
python connector.py status TASK_ID      # one-line state
python connector.py report TASK_ID      # events, evidence, which provider/model/effort/skills ran each step
python connector.py wait TASK_ID        # polls the API (no AI) until it reaches a final state
python connector.py patch TASK_ID       # the patch as data, once gates and review passed
python connector.py apply TASK_ID --dry-run   # check it applies here; no changes
python connector.py apply TASK_ID             # apply it; only after the user approved it in the Center
python connector.py cancel TASK_ID
```

`--provider claude|codex|google` is only a request; the Center may still decide otherwise within the project's allowed providers.

## Rules you must keep
- When configured with `approval_policy: auto_apply` (default), approved patches are applied directly into the project root automatically once Quality Gates and Review pass!
- For projects configured with `human_required`, human approval is done in the Center terminal before `apply`.
- `apply` never runs git commit/push. Review the diff and commit yourself when ready.
- Do not poll by repeatedly asking a model: use `status`, `report` or `wait`.
- Do not create credentials, change global IDE settings, invoke paid APIs, or push/merge/deploy.
- Review results never come from this session. If the Center says it is waiting for independent review, wait.
