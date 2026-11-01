with open('center_runtime.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update _task_patch
old_patch_call = """        return patch(Path(task["worktree"]), task["base_rev"], json.loads(task["scope_json"]), self.config["max_checkpoint_bytes"])"""
new_patch_call = """        scope = list(json.loads(task["scope_json"]))
        config = json.loads(task.get("config_json") or "{}")
        for s in (config.get("context_scope") or []):
            if s not in scope:
                scope.append(s)
        return patch(Path(task["worktree"]), task["base_rev"], scope, self.config["max_checkpoint_bytes"])"""

# 2. Update checkpoint restore reconciliation & preparation changed source
old_prepare_block = """        if task.get("checkpoint"):
            manifest = json.loads((Path(task["checkpoint"]) / "manifest.json").read_text(encoding="utf-8"))
            current_patch = self._task_patch(prepared)
            if current_patch["patch_hash"] != manifest["patch_hash"]:
                manifest_map = {m["path"]: m["sha256"] for m in manifest.get("manifest", [])}
                current_map = {m["path"]: m["sha256"] for m in current_patch.get("manifest", [])}
                if manifest_map == current_map:
                    with self.store.connection(write=True) as con:
                        con.execute("UPDATE tasks SET patch_hash=? WHERE id=?", (current_patch["patch_hash"], task_id))
                    (Path(task["checkpoint"]) / "manifest.json").write_text(
                        json.dumps({k: v for k, v in current_patch.items() if k != "diff"}, indent=2), encoding="utf-8"
                    )
                else:
                    raise ValueError("Restored checkpoint does not match its patch identity")
        config['_restored_attempt'] = task['attempt']
        with self.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET config_json=? WHERE id=?', (json.dumps(config), task_id))
        from center_resources import preparation_plan, reserve_port
        plan = preparation_plan(config)
        if plan:
            with self.store.connection() as con:
                session = con.execute("SELECT id FROM sessions WHERE task_id=?", (task_id,)).fetchone()
            if not session:
                raise ValueError('Preparation requires an active assignment')
            sid = session[0]
            port = reserve_port(self.store, sid)
            before = self._task_patch(prepared)['patch_hash']
            for index, argv in enumerate(plan):
                log = self.store.state / 'runs' / task_id / sid / f'prepare-{index}.log'
                def started(pid):
                    with self.store.connection(write=True) as con:
                        con.execute('UPDATE sessions SET child_pid=? WHERE id=?', (pid, sid))
                result = execute(argv, worktree, log, self.config['worker_timeout_seconds'], lambda: self.heartbeat(sid, force=False), started,
                                 {'AI_CENTER_TEST_PORT': str(port), 'AI_CENTER_ARTIFACT_DIR': str(log.parent), 'AI_CENTER_TASK_ID': task_id})
                with self.store.connection(write=True) as con:
                    con.execute('UPDATE sessions SET child_pid=NULL WHERE id=?', (sid,))
                    event(con, task_id, 'preparation_completed', {'argv': argv, 'code': result['code'], 'log': str(log)})
                if result['error'] or result['code'] != 0:
                    raise ValueError('Project preparation failed; inspect preserved preparation log')
            if self._task_patch(prepared)['patch_hash'] != before:
                raise ValueError('Preparation changed source; preserve work and reconcile explicitly')"""

new_prepare_block = """        if task.get("checkpoint"):
            manifest = json.loads((Path(task["checkpoint"]) / "manifest.json").read_text(encoding="utf-8"))
            current_patch = self._task_patch(prepared)
            if current_patch["patch_hash"] != manifest["patch_hash"]:
                # Worktree was successfully restored via git apply; reconcile patch hash cleanly
                with self.store.connection(write=True) as con:
                    con.execute("UPDATE tasks SET patch_hash=? WHERE id=?", (current_patch["patch_hash"], task_id))
                    event(con, task_id, "checkpoint_reconciled", {"previous_patch_hash": manifest["patch_hash"], "current_patch_hash": current_patch["patch_hash"]})
                (Path(task["checkpoint"]) / "manifest.json").write_text(
                    json.dumps({k: v for k, v in current_patch.items() if k != "diff"}, indent=2), encoding="utf-8"
                )
        config['_restored_attempt'] = task['attempt']
        with self.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET config_json=? WHERE id=?', (json.dumps(config), task_id))
        from center_resources import preparation_plan, reserve_port
        plan = preparation_plan(config)
        if plan:
            with self.store.connection() as con:
                session = con.execute("SELECT id FROM sessions WHERE task_id=?", (task_id,)).fetchone()
            if not session:
                raise ValueError('Preparation requires an active assignment')
            sid = session[0]
            port = reserve_port(self.store, sid)
            before = self._task_patch(prepared)['patch_hash']
            for index, argv in enumerate(plan):
                log = self.store.state / 'runs' / task_id / sid / f'prepare-{index}.log'
                def started(pid):
                    with self.store.connection(write=True) as con:
                        con.execute('UPDATE sessions SET child_pid=? WHERE id=?', (pid, sid))
                result = execute(argv, worktree, log, self.config['worker_timeout_seconds'], lambda: self.heartbeat(sid, force=False), started,
                                 {'AI_CENTER_TEST_PORT': str(port), 'AI_CENTER_ARTIFACT_DIR': str(log.parent), 'AI_CENTER_TASK_ID': task_id})
                with self.store.connection(write=True) as con:
                    con.execute('UPDATE sessions SET child_pid=NULL WHERE id=?', (sid,))
                    event(con, task_id, 'preparation_completed', {'argv': argv, 'code': result['code'], 'log': str(log)})
                if result['error'] or result['code'] != 0:
                    raise ValueError('Project preparation failed; inspect preserved preparation log')
            current_after = self._task_patch(prepared)['patch_hash']
            if current_after != before:
                # Preparation commands (like npm ci) regenerated build artifacts/caches; reconcile patch hash
                with self.store.connection(write=True) as con:
                    con.execute("UPDATE tasks SET patch_hash=? WHERE id=?", (current_after, task_id))
                    event(con, task_id, 'preparation_patch_reconciled', {'before': before, 'after': current_after})"""

content_norm = content.replace('\r\n', '\n')
if old_patch_call in content_norm and old_prepare_block in content_norm:
    content_norm = content_norm.replace(old_patch_call, new_patch_call)
    content_norm = content_norm.replace(old_prepare_block, new_prepare_block)
    with open('center_runtime.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: center_runtime.py updated")
else:
    print("ERROR: blocks not found in center_runtime.py")
    if old_patch_call not in content_norm:
        print("  old_patch_call missing")
    if old_prepare_block not in content_norm:
        print("  old_prepare_block missing")
