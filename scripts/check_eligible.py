import sqlite3, time
con = sqlite3.connect('.ai-team/tasks.sqlite3')
rows = con.execute("SELECT id, status, project_id, mode, not_before FROM tasks WHERE mode='live' AND status IN ('queued', 'retry_wait', 'waiting_for_independent_review')").fetchall()
print('Eligible count:', len(rows))
for r in rows:
    print(r)
print('Current time:', time.time())
