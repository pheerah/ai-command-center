import sqlite3, json
from pathlib import Path

con = sqlite3.connect('.ai-team/tasks.sqlite3')
con.row_factory = sqlite3.Row
cur = con.cursor()

r = cur.execute("SELECT * FROM tasks WHERE id = 'ea90d4340e37'").fetchone()
if r:
    for k in ('id', 'project_id', 'title', 'status', 'provider', 'error', 'attempt', 'max_attempts', 'scope_json', 'acceptance_json'):
        print(f"{k}: {r[k]}")
    cfg = json.loads(r['config_json'])
    print("Quality gates in config:", cfg.get('quality_gates'))

runs_dir = Path('.ai-team/runs/ea90d4340e37')
if runs_dir.exists():
    for f in runs_dir.rglob('gate-*.log'):
        print(f"Gate log: {f} ({f.stat().st_size} bytes)")
