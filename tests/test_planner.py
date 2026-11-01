"""Unit tests for the Autonomous AI Supervisor & Adaptive Planner (center_planner.py)."""
import tempfile
import unittest
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'backend'))
import center_planner


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.project_config = {
            "project_id": "test-project",
            "context_scope": ["src", "tests", "docs"],
            "quality_gates": [["python", "-m", "unittest"]],
            "allowed_providers": ["claude", "codex", "google"]
        }

    def test_classify_simple_task(self):
        inst = "Fix typo in docs/README.md and update button label"
        c = center_planner.classify_task(inst, self.root, self.project_config)
        self.assertEqual(c.mode, 'simple')
        self.assertIn(c.complexity, (1, 2))
        self.assertEqual(c.suggested_tier, 'light')
        self.assertIn('docs/README.md', c.target_files)

    def test_classify_complex_task(self):
        inst = "Design and implement OAuth authentication service with PostgreSQL database schema and JWT session management"
        c = center_planner.classify_task(inst, self.root, self.project_config)
        self.assertEqual(c.mode, 'complex')
        self.assertGreaterEqual(c.complexity, 3)
        self.assertIn(c.suggested_tier, ('standard', 'heavy'))

    def test_plan_fast_path_produces_single_task(self):
        inst = "Change primary button color in src/styles.css"
        res = center_planner.plan(inst, workspace_root=self.root, council_mode='never', project_config=self.project_config)
        self.assertFalse(res['is_dag'])
        self.assertEqual(len(res['tasks']), 1)
        task = res['tasks'][0]
        self.assertEqual(task['plan_id'], 'task_1')
        self.assertIn('src', task['scope'][0])
        self.assertIn('python -m unittest', task['acceptance'][0])
        self.assertEqual(task['dependencies'], [])

    def test_plan_council_path_produces_dag(self):
        inst = "Build multi-agent council debate module and fullstack API endpoint"
        res = center_planner.plan(inst, workspace_root=self.root, council_mode='force', project_config=self.project_config)
        self.assertTrue(res['is_dag'])
        self.assertEqual(len(res['tasks']), 2)
        task_core = res['tasks'][0]
        task_qa = res['tasks'][1]
        self.assertEqual(task_core['plan_id'], 'task_core')
        self.assertEqual(task_qa['plan_id'], 'task_qa')
        self.assertEqual(task_qa['dependencies'], ['task_core'])

    def test_plan_adaptive_auto_mode(self):
        simple_res = center_planner.plan("fix typo in comment", workspace_root=self.root, project_config=self.project_config)
        self.assertEqual(simple_res['classification']['mode'], 'simple')
        self.assertEqual(len(simple_res['tasks']), 1)

        complex_res = center_planner.plan("refactor database pipeline architecture", workspace_root=self.root, project_config=self.project_config)
        self.assertEqual(complex_res['classification']['mode'], 'complex')
        self.assertEqual(len(complex_res['tasks']), 2)

    def test_submit_plan_links_dependencies(self):
        plan_result = {
            "tasks": [
                {
                    "plan_id": "task_core",
                    "title": "Core Auth",
                    "prompt": "Implement core",
                    "scope": ["src"],
                    "acceptance": ["pytest"],
                    "complexity": 3,
                    "dependencies": [],
                    "provider": "auto"
                },
                {
                    "plan_id": "task_qa",
                    "title": "QA Auth",
                    "prompt": "Test core",
                    "scope": ["tests"],
                    "acceptance": ["pytest"],
                    "complexity": 2,
                    "dependencies": ["task_core"],
                    "provider": "auto"
                }
            ]
        }

        submitted_calls = []
        def mock_submit(title, prompt, scope, acceptance, complexity, dependencies, provider):
            new_id = f"center_id_{len(submitted_calls) + 1}"
            submitted_calls.append({
                "id": new_id,
                "title": title,
                "dependencies": dependencies
            })
            return {"id": new_id, "status": "queued"}

        submitted = center_planner.submit_plan(plan_result, mock_submit)
        self.assertEqual(len(submitted), 2)
        self.assertEqual(submitted_calls[0]["dependencies"], [])
        # The QA task should have received the real Center ID of task_core!
        self.assertEqual(submitted_calls[1]["dependencies"], [submitted_calls[0]["id"]])


if __name__ == '__main__':
    unittest.main()
