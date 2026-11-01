"""Autonomous AI Supervisor & Adaptive Planner for the AI Dev Command Center.

Translates high-level natural language instructions into structured, executable
task DAGs with explicit scopes, acceptance criteria, model tiers, and dynamic routing.

Supports:
- Fast Path: 1 AI for simple/isolated tasks (low latency, minimal tokens).
- Council Path: Multi-perspective synthesis for complex/architectural tasks (parallel DAG).
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


COMPLEX_KEYWORDS = {
    'auth', 'authentication', 'oauth', 'jwt', 'login', 'signup', 'session',
    'database', 'migration', 'schema', 'sql', 'postgres', 'sqlite', 'model',
    'architecture', 'refactor', 'redesign', 'restructure', 'pipeline',
    'api', 'endpoint', 'rest', 'graphql', 'grpc', 'microservice',
    'council', 'multi-agent', 'parallel', 'distributed', 'security', 'encryption',
    'fullstack', 'integration test', 'end-to-end', 'e2e', 'concurrency'
}

SIMPLE_KEYWORDS = {
    'typo', 'fix typo', 'spelling', 'rename', 'comment', 'docstring',
    'button text', 'color', 'css', 'style', 'copy', 'label', 'string',
    'minor', 'small fix', 'one line', 'single line', 'lint', 'format'
}


@dataclass
class TaskClassification:
    mode: str  # 'simple' or 'complex'
    complexity: int  # 1 to 5
    reason: str
    suggested_tier: str  # 'light', 'standard', 'heavy'
    suggested_effort: str  # 'low', 'medium', 'high', 'xhigh'
    target_files: List[str] = field(default_factory=list)


@dataclass
class PlannedTask:
    plan_id: str
    title: str
    prompt: str
    scope: List[str]
    acceptance: List[str]
    complexity: int
    model_tier: str
    effort: str
    provider: str = "auto"
    dependencies: List[str] = field(default_factory=list)


def extract_mentioned_files(text: str, workspace_root: Optional[Path] = None) -> List[str]:
    """Finds referenced filenames or paths in the text."""
    # Match patterns like foo.py, src/bar.ts, path/to/file.ext
    pattern = r'[a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]{1,6}'
    matches = re.findall(pattern, text)
    cleaned = []
    for m in matches:
        m = m.replace('\\', '/').strip('.,;:()[]"\'')
        if not m or m.startswith('http') or '@' in m:
            continue
        if workspace_root:
            candidate = workspace_root / m
            if candidate.exists() or any(p in m for p in ('src', 'tests', 'lib', 'app', 'docs')):
                cleaned.append(m)
        else:
            cleaned.append(m)
    return sorted(set(cleaned))


def classify_task(instruction: str, workspace_root: Optional[Path] = None, project_config: Optional[dict] = None) -> TaskClassification:
    """Classifies an instruction as simple (Fast Path) or complex (Council Path)."""
    text_lower = instruction.lower()
    mentioned_files = extract_mentioned_files(instruction, workspace_root)
    
    # Check for strong simple indicators
    simple_hits = [w for w in SIMPLE_KEYWORDS if w in text_lower]
    complex_hits = [w for w in COMPLEX_KEYWORDS if w in text_lower]
    
    # Heuristics
    is_multi_file = len(mentioned_files) > 2
    is_long_instruction = len(instruction.split()) > 45
    
    if complex_hits or is_multi_file or is_long_instruction:
        # Complex / Council Path
        complexity = 3
        if len(complex_hits) >= 3 or ('architecture' in complex_hits or 'database' in complex_hits):
            complexity = 4
        if 'refactor' in complex_hits and 'system' in text_lower:
            complexity = 5
        
        tier = 'heavy' if complexity >= 4 else 'standard'
        effort = 'high' if complexity >= 4 else 'medium'
        reason = f"Complex scope detected (keywords: {', '.join(complex_hits) or 'multi-file/long spec'}, files: {len(mentioned_files)})"
        return TaskClassification(
            mode='complex',
            complexity=complexity,
            reason=reason,
            suggested_tier=tier,
            suggested_effort=effort,
            target_files=mentioned_files
        )
    
    # Default to simple / Fast Path
    complexity = 1 if simple_hits else 2
    tier = 'light' if complexity == 1 else 'standard'
    effort = 'low' if complexity == 1 else 'medium'
    reason = f"Single focused task detected (simple indicators: {', '.join(simple_hits) or 'concise prompt'})"
    return TaskClassification(
        mode='simple',
        complexity=complexity,
        reason=reason,
        suggested_tier=tier,
        suggested_effort=effort,
        target_files=mentioned_files
    )


def _resolve_scope(target_files: List[str], project_config: Optional[dict], workspace_root: Optional[Path]) -> List[str]:
    """Ensures scope covers allowed project context_scope so AI can implement and test freely."""
    allowed = (project_config or {}).get('context_scope') or []
    if allowed:
        return list(allowed)
    if target_files:
        return list(set(target_files))
    return ['src', 'tests']


def _resolve_acceptance(project_config: Optional[dict], custom_check: Optional[str] = None) -> List[str]:
    """Extracts quality gates from project config or standard test commands."""
    gates = (project_config or {}).get('quality_gates') or []
    flat_gates = []
    for g in gates:
        if isinstance(g, list):
            flat_gates.append(' '.join(g))
        elif isinstance(g, str):
            flat_gates.append(g)
    
    if custom_check:
        flat_gates.append(custom_check)
    
    if not flat_gates:
        # Fallback safe check
        flat_gates = ['python -m unittest discover -s tests']
    return flat_gates


def plan_fast_path(instruction: str, classification: TaskClassification, project_config: Optional[dict], workspace_root: Optional[Path]) -> List[PlannedTask]:
    """Generates a single, self-contained task for Fast Path execution."""
    title_line = instruction.strip().split('\n')[0][:80]
    scope = _resolve_scope(classification.target_files, project_config, workspace_root)
    acceptance = _resolve_acceptance(project_config)
    
    task = PlannedTask(
        plan_id="task_1",
        title=title_line,
        prompt=instruction.strip(),
        scope=scope,
        acceptance=acceptance,
        complexity=classification.complexity,
        model_tier=classification.suggested_tier,
        effort=classification.suggested_effort,
        provider="auto",
        dependencies=[]
    )
    return [task]


def plan_council_path(instruction: str, classification: TaskClassification, project_config: Optional[dict], workspace_root: Optional[Path]) -> List[PlannedTask]:
    """Simulates/executes multi-perspective AI council breakdown into parallel subtasks."""
    scope_pool = _resolve_scope(classification.target_files, project_config, workspace_root)
    acceptance = _resolve_acceptance(project_config)
    
    # Decompose into 2-3 logical subtasks (e.g. Core Implementation -> QA & Verification)
    title_line = instruction.strip().split('\n')[0][:60]
    
    # Separate core scope vs test scope if available
    core_scope = [s for s in scope_pool if not s.startswith('test')] or scope_pool
    test_scope = [s for s in scope_pool if s.startswith('test')] or ['tests']
    
    task_core = PlannedTask(
        plan_id="task_core",
        title=f"{title_line} - Core Implementation",
        prompt=f"{instruction}\n\n[Focus: Core architectural implementation, data structures, and business logic]",
        scope=core_scope,
        acceptance=acceptance,
        complexity=classification.complexity,
        model_tier=classification.suggested_tier,
        effort=classification.suggested_effort,
        provider="auto",
        dependencies=[]
    )
    
    task_qa = PlannedTask(
        plan_id="task_qa",
        title=f"{title_line} - QA & Integration Tests",
        prompt=f"Verify and write comprehensive unit and integration tests for:\n{instruction}\n\n[Focus: Edge cases, regression tests, and full quality gate compliance]",
        scope=test_scope,
        acceptance=acceptance,
        complexity=max(1, classification.complexity - 1),
        model_tier='standard',
        effort='medium',
        provider="auto",
        dependencies=["task_core"]
    )
    
    return [task_core, task_qa]


def plan(instruction: str, workspace_root: Optional[Path] = None, council_mode: str = 'auto', project_config: Optional[dict] = None) -> Dict[str, Any]:
    """Main planning function. Analyzes instruction and produces an actionable plan."""
    if workspace_root is None:
        workspace_root = Path.cwd()
    
    if project_config is None:
        cfg_path = workspace_root / 'project.config.json'
        if cfg_path.is_file():
            try:
                project_config = json.loads(cfg_path.read_text(encoding='utf-8'))
            except Exception:
                project_config = {}
        else:
            project_config = {}
    
    classification = classify_task(instruction, workspace_root, project_config)
    
    if council_mode == 'force':
        tasks = plan_council_path(instruction, classification, project_config, workspace_root)
    elif council_mode == 'never':
        tasks = plan_fast_path(instruction, classification, project_config, workspace_root)
    else:  # auto
        if classification.mode == 'complex':
            tasks = plan_council_path(instruction, classification, project_config, workspace_root)
        else:
            tasks = plan_fast_path(instruction, classification, project_config, workspace_root)
    
    summary_lines = [
        f"### Plan Overview: {tasks[0].title}",
        f"- **Mode**: {classification.mode.upper()} ({classification.reason})",
        f"- **Complexity**: {classification.complexity}/5",
        f"- **Model Tier**: {classification.suggested_tier} (Effort: {classification.suggested_effort})",
        f"- **Subtasks**: {len(tasks)} task(s)",
        ""
    ]
    for i, t in enumerate(tasks, 1):
        dep_str = f" (Depends on: {', '.join(t.dependencies)})" if t.dependencies else " (Parallel / Independent)"
        summary_lines.append(f"{i}. **[{t.plan_id}] {t.title}**{dep_str}")
        summary_lines.append(f"   - Scope: `{', '.join(t.scope)}`")
        summary_lines.append(f"   - Tier: `{t.model_tier}` | Effort: `{t.effort}`")
    
    return {
        "classification": asdict(classification),
        "tasks": [asdict(t) for t in tasks],
        "is_dag": len(tasks) > 1,
        "summary": "\n".join(summary_lines)
    }


def submit_plan(plan_result: Dict[str, Any], submit_fn) -> List[Dict[str, Any]]:
    """Submits planned tasks to Center, mapping local plan IDs to real task IDs."""
    id_map = {}
    submitted = []
    
    for t in plan_result["tasks"]:
        real_deps = [id_map[d] for d in t["dependencies"] if d in id_map]
        res = submit_fn(
            title=t["title"],
            prompt=t["prompt"],
            scope=t["scope"],
            acceptance=t["acceptance"],
            complexity=t["complexity"],
            dependencies=real_deps,
            provider=t.get("provider", "auto")
        )
        task_id = res.get("id") or res.get("task_id")
        if task_id:
            id_map[t["plan_id"]] = task_id
        submitted.append({"plan_id": t["plan_id"], "center_task_id": task_id, "result": res})
    
    return submitted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('instruction', help='High-level natural language instruction')
    parser.add_argument('--path', default='.', help='Project workspace path')
    parser.add_argument('--council', choices=['auto', 'force', 'never'], default='auto', help='Adaptive planning mode')
    parser.add_argument('--json', action='store_true', help='Output raw JSON plan')
    parser.add_argument('--submit', action='store_true', help='Automatically submit plan via connector.py')
    args = parser.parse_args()
    
    workspace = Path(args.path).resolve()
    result = plan(args.instruction, workspace_root=workspace, council_mode=args.council)
    
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result["summary"])
    
    if args.submit:
        # Call connector submit
        import connector
        def _do_submit(title, prompt, scope, acceptance, complexity, dependencies, provider):
            # Form connector submit payload or call API
            body = {
                "title": title,
                "prompt": prompt,
                "scope": scope,
                "acceptance": acceptance,
                "complexity": complexity,
                "dependencies": dependencies,
                "provider": provider
            }
            return connector.request('POST', '/api/v1/tasks', body)
        
        submitted = submit_plan(result, _do_submit)
        print("\nSuccessfully submitted tasks to Center:")
        for s in submitted:
            print(f"- {s['plan_id']} -> Task ID: {s['center_task_id']}")


if __name__ == '__main__':
    main()
