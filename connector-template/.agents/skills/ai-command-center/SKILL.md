---
name: ai-command-center
description: Submit implementation tasks to the local SQLite Center and acknowledge explicit IDE handoffs.
---

# Project connector

Use the project-local python connector.py commands. Do not read the Center source or other projects for routine tasks.

## Request classification
- Questions, explanations and read-only code discussion: answer normally; no implementation pipeline required.
- Any source/config changes, multi-file implementation or test work: check Center health and registration, then submit a scoped task with acceptance criteria.
- Center unavailable or provider unavailable: report blocked. Never silently implement the task yourself.

## Commands (run at project root)
```powershell
python connector.py health
python connector.py register
python connector.py submit --title 'Describe task' --prompt 'Requirement' --scope src --scope tests --accept 'Required checks pass' --mode live
python connector.py status TASK_ID
python connector.py report TASK_ID
python connector.py claim TASK_ID --provider codex --role implementation
python connector.py worker-start SESSION_ID --reference IDE_SESSION_REFERENCE
python connector.py heartbeat SESSION_ID
python connector.py watch SESSION_ID
python connector.py result SESSION_ID --file result.json
python connector.py worker-fail SESSION_ID --reason auth --worker-stopped
python connector.py worker-stopped SESSION_ID --reason 'IDE has stopped editing after cancellation'
```

Use your actual provider identity: codex, claude or google. Do not claim another provider's identity. Google is currently unavailable / usage_exhausted / reset unknown. Do not change that status or probe its quota.

After claim, work only in the returned task worktree, never the original checkout. Acknowledge actual start with the IDE session reference. Run `watch SESSION_ID` as a local background process to renew every 5 seconds without AI polling. Stop the watcher when finished and stop editing immediately if renewal fails. The lease defaults to 30 seconds. IDE automation remains pending_live_verification until a real supported IDE session proves this protocol.

Implementation result JSON must contain task_id, base_rev, simulated=false and a concise summary. Center computes the patch/checkpoint and executes gates. Review result additionally requires patch_hash and verdict=approved|rejected. A review must inspect the full scoped patch and new files, use a provider absent from all authorship history, and must not edit files.

Write result.json only inside the artifact_dir returned by claim; other paths are rejected before reading. On cancellation, stop the IDE worker and acknowledge worker-stopped to finalize cancellation and release its slot. Expiry alone cannot prove an external IDE stopped. Do not create credentials in source, read auth files, change global IDE settings, commit, push, merge or deploy. Do not invoke paid APIs or enable extra usage.

The local handoff protocol records reported provider/session identity; it does not cryptographically authenticate the IDE. Worktrees are not OS security sandboxes. Keep operational rules distinct from enforced Center state/capacity checks.

Use deterministic status requests or the dashboard to follow progress. Do not poll by repeatedly asking AI models. Human approval is performed by the user in an interactive Center terminal; never run approve on their behalf.
