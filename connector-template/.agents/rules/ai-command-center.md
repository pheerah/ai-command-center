---
trigger: always_on
description: Route implementation through the local Center and preserve independent review and human approval.
---

# AI Command Center — Project Rules for Antigravity

When working in this project within Google Antigravity IDE:
1. **Delegation to Central Center**:
   - For multi-step implementation, complex refactoring, test additions, or QA reviews: Dispatch tasks to the central AI Command Center using the `ai-command-center` skill rather than attempting full autonomous multi-file changes entirely within the single session.
2. **Project Isolation**:
   - Only pass task prompts and paths that belong to this repository. Do NOT read from or cross-reference other project repositories.
3. **Zero Automated Commits**:
   - Never run `git commit` or `git push` automatically. Always stop at `ready_for_human_approval` and require explicit human approval.
4. **Independent Review**:
   - Require passing gates and a reviewer from a provider absent from the full authorship history. Mock review never grants approval. If no reviewer is available, wait for independent review.
5. **Explicit Assignment**:
   - Use claim, worker-start, heartbeat and result through the connector. Work only in the returned task worktree. Center errors mean blocked, never silent IDE takeover. Worktrees are not OS security sandboxes.
6. **Provider State**:
   - Google is unavailable with usage_exhausted and reset unknown. Do not invoke it or harvest credentials. Roles are interchangeable and capacity is configured centrally.
