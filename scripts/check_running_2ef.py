import sqlite3, time
con = sqlite3.connect('.ai-team/tasks.sqlite3')
cur = con.cursor()
r = cur.execute("SELECT id, status, provider, attempt, error FROM tasks WHERE id = '2ef046aa30c3'").fetchone()
print('Task:', r)
for s in cur.execute("SELECT id, task_id, role, provider, lease_until FROM sessions WHERE task_id = '2ef046aa30c3'").fetchall():
    print('Session:', s, 'Lease remaining:', s[4] - time.time())
