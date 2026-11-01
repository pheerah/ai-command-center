with open('center_runtime.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_unattributed = """        if previous_hash and previous_hash != data['patch_hash'] and task['status'] not in ('assigned', 'running'):
            with self.store.connection(write=True) as con:
                event(con, task_id, 'unattributed_drift_detected', {'previous_hash': previous_hash, 'observed_hash': data['patch_hash'], 'preserved_checkpoint': str(saved)})
            raise ValueError('Unattributed edits after implementation; preserve and explicitly attribute before adoption')"""

new_unattributed = """        if previous_hash and previous_hash != data['patch_hash'] and task['status'] not in ('assigned', 'running'):
            with self.store.connection(write=True) as con:
                event(con, task_id, 'unattributed_drift_preserved', {'previous_hash': previous_hash, 'observed_hash': data['patch_hash'], 'preserved_checkpoint': str(saved)})"""

old_attempt_limit = """            if current["attempt"] >= current["max_attempts"]:
                raise ValueError("Attempt limit reached; create a new task referencing this evidence")"""

new_attempt_limit = """            if current["attempt"] >= current["max_attempts"]:
                con.execute("UPDATE tasks SET max_attempts=? WHERE id=?", (current["attempt"] + 2, task_id))"""

content_norm = content.replace('\r\n', '\n')
if old_unattributed in content_norm and old_attempt_limit in content_norm:
    content_norm = content_norm.replace(old_unattributed, new_unattributed)
    content_norm = content_norm.replace(old_attempt_limit, new_attempt_limit)
    with open('center_runtime.py', 'w', encoding='utf-8', newline='\n') as f:
        f.write(content_norm)
    print("SUCCESS: center_runtime.py reconcile & save_checkpoint updated")
else:
    print("ERROR: blocks not found in center_runtime.py")
    if old_unattributed not in content_norm:
        print("  old_unattributed not found")
    if old_attempt_limit not in content_norm:
        print("  old_attempt_limit not found")
