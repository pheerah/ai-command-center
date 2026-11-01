import sqlite3
import json

con = sqlite3.connect('.ai-team/tasks.sqlite3')
con.row_factory = sqlite3.Row
cur = con.cursor()

tasks = ['89188f6b9d22', '6124392f4dd3', '4d128cf678ae', '92dbbe7aefcf', 'a9a700881eb7']
for task_id in tasks:
    print('=' * 60)
    print(f'TASK {task_id}')
    t_row = cur.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if t_row:
        print(dict(t_row))
    print('--- EVENTS ---')
    rows = cur.execute('SELECT event, detail, created_at FROM events WHERE task_id = ? ORDER BY id DESC LIMIT 10', (task_id,)).fetchall()
    for r in reversed(rows):
        print(f"[{r['created_at']}] {r['event']}: {r['detail']}")
