with open('center_runtime.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """            plan = {"version": 1, "name": f"{task_id}-{role}", "workspace_root": task["worktree"], "max_parallel": 1,
                    "tasks": [{"id": role, "command": [sys.executable, str(ROOT / "center_worker.py"), str(directory / "request.json")], "shell": False, "workdir": task["worktree"]}]}
            import yaml
            plan_path = directory / "plan.yaml"
            plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")"""

new_block = """            venv_py = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            py_exec = str(venv_py) if venv_py.is_file() else sys.executable
            plan = {"version": 1, "name": f"{task_id}-{role}", "workspace_root": task["worktree"], "max_parallel": 1,
                    "tasks": [{"id": role, "command": [py_exec, str(ROOT / "center_worker.py"), str(directory / "request.json")], "shell": False, "workdir": task["worktree"]}]}
            plan_path = directory / "plan.yaml"
            try:
                import yaml
                yaml_text = yaml.safe_dump(plan, sort_keys=False)
            except ImportError:
                yaml_text = json.dumps(plan, indent=2)
            plan_path.write_text(yaml_text, encoding="utf-8")"""

content_norm = content.replace('\r\n', '\n')
if old_block in content_norm:
    content_norm = content_norm.replace(old_block, new_block)
    with open('center_runtime.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: center_runtime.py plan.yaml fallback updated")
else:
    print("ERROR: old_block not found in center_runtime.py")
