"""Create two isolated sample repositories using existing Git objects, no commits."""
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from center_runtime import Center
from center_workspace import git


def main():
    target = ROOT / "sandbox" / "runs" / f"{time.time_ns()}-{uuid.uuid4().hex[:6]}"
    target.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT / 'center.config.json').read_text())
    config['live_execution'] = False
    center_config_path = target / 'center.config.json'
    center_config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    center = Center(target / "state", center_config_path)
    examples = [
        ("sample-a", ["node", "-e", "const {multiply}=require('./src/calculator.js'); if(multiply(6,7)!==42)process.exit(1)"],
         {"file": "src/calculator.js", "content": "exports.multiply = (a, b) => a * b;\n"}),
        ("sample-b", ["python", "-c", "from src.formatter import format_percentage; assert format_percentage(0.125) == '12.5%'"],
         {"file": "src/formatter.py", "content": "def format_percentage(value):\n    return f'{value * 100:.1f}%'\n"}),
    ]
    tasks = []
    for project_id, gate, action in examples:
        root = target / project_id
        root.mkdir()
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
        shutil.copytree(ROOT / ".git/objects", root / ".git/objects", dirs_exist_ok=True)
        git(root, "checkout", "--quiet", "--detach", git(ROOT, "rev-parse", "HEAD"))
        # Config lives in ignored Git metadata so fixtures need no commits.
        cfg = {"project_id": project_id, "name": project_id, "allowed_providers": ["codex", "claude"],
               "context_scope": ["src", "tests"], "quality_gates": [gate], "auto_commit": False,
               "approval_policy": "human_required", "base_revision": "HEAD"}
        config_path = root / ".git/center-project.json"
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        center.register(project_id, root, config_path)
        task = center.submit(project_id, "Sample implementation", "Demonstrate scoped changes, gates and independent mock review", ["src"], ["Functional sample check passes"], mode="mock", mock=action)
        implementation = center.run_phase(task["id"], "implementation", "mock", "codex")
        if implementation.get("state") != "waiting_for_independent_review":
            raise ValueError(f"Sample implementation failed: {implementation}")
        review = center.run_phase(task["id"], "review", "mock", "claude")
        if not review.get("simulated"):
            raise ValueError(f"Sample mock review failed: {review}")
        tasks.append({"task_id": task["id"], "project_id": project_id, "implementation": implementation, "review": review,
                      "worktree": center.store.task(task["id"])["worktree"]})
    report = {"state_dir": str(center.store.state), 'config': str(center_config_path), "tasks": tasks, "real_ai_calls": 0, "approval": "waiting_for_independent_review"}
    report_path = target / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({**report, "report": str(report_path)}, indent=2))


if __name__ == "__main__":
    main()
