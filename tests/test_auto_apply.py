"""Tests for the Auto-Apply feature: automatically applying approved patches to the project workspace."""
import json
from pathlib import Path
import unittest

import test_smart_router as fixtures


class AutoApplyTests(unittest.TestCase):
    setUp = fixtures.CenterTests.setUp
    cleanup = fixtures.CenterTests.cleanup
    task = fixtures.CenterTests.task
    claim_and_prepare = fixtures.CenterTests.claim_and_prepare
    implement_manually = fixtures.CenterTests.implement_manually

    def test_auto_apply_updates_project_workspace_when_review_passes(self):
        # Configure project with approval_policy: auto_apply
        cfg = json.loads(self.ca.read_text())
        cfg['approval_policy'] = 'auto_apply'
        self.ca.write_text(json.dumps(cfg))
        self.center.register('project-a', self.a, self.ca, confirm_config_change=True)

        # 1. Create task and implement in worktree
        task = self.task(mode="live")
        t = self.implement_manually(task, "handoff", "codex")
        self.assertEqual(t['status'], 'waiting_for_independent_review')

        # 2. Claim review by different provider and complete with verdict: approved
        s = self.center.claim(t["id"], "review", "handoff", "claude")
        self.center.started(s["id"], "synthetic-review-fixture")
        response = {
            "task_id": t["id"],
            "base_rev": t["base_rev"],
            "patch_hash": t["patch_hash"],
            "verdict": "approved",
            "summary": "Auto QA approved",
            "simulated": False
        }
        res = self.center.complete(s["id"], response)

        # 3. With auto_apply policy, state transitions immediately to 'approved'
        self.assertEqual(res['state'], 'approved')
        final_task = self.center.store.task(t["id"])
        self.assertEqual(final_task['status'], 'approved')
        self.assertEqual(final_task['approved_by'], 'auto_apply')

        # 4. Verify that the file was auto-applied directly into project A's root!
        applied_file = self.a / 'src' / 'center_mock.txt'
        self.assertTrue(applied_file.is_file(), "File must be auto-applied directly to project root")
        self.assertIn("Center mock implementation", applied_file.read_text(encoding='utf-8'))

        # 5. Verify the audit event
        events = [r['event'] for r in self.center.report(t["id"])['events']]
        self.assertIn('auto_applied_to_workspace', events)


if __name__ == '__main__':
    unittest.main()
