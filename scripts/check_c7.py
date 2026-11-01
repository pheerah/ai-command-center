import sqlite3
con = sqlite3.connect('.ai-team/tasks.sqlite3')
for r in con.execute("SELECT event, detail, created_at FROM events WHERE task_id='c71a02aec12b' ORDER BY id DESC LIMIT 10"):
    print(f"[{r[2]}] {r[0]}: {r[1][:150]}")
