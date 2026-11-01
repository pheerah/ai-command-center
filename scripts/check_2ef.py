import sqlite3, json
from pathlib import Path

con = sqlite3.connect('.ai-team/tasks.sqlite3')
con.row_factory = sqlite3.Row
cur = con.cursor()

t = cur.execute("SELECT * FROM tasks WHERE id = '2ef046aa30c3'").fetchone()
if t:
    for k in ('id', 'title', 'prompt', 'status', 'provider', 'error', 'attempt'):
        print(f"{k}: {t[k]}")

run_dir = Path('.ai-team/runs/2ef046aa30c3/64b7df183be44d8bb6d584f3e6807034')
if run_dir.exists():
    for f in run_dir.iterdir():
        print(f.name, f.stat().st_size)
    if (run_dir / 'response.json').exists():
        print('--- response.json ---')
        print((run_dir / 'response.json').read_text(encoding='utf-8', errors='replace')[:1000])
    if (run_dir / 'provider-final.json').exists():
        print('--- provider-final.json ---')
        print((run_dir / 'provider-final.json').read_text(encoding='utf-8', errors='replace')[:1000])
