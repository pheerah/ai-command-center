import sqlite3
con = sqlite3.connect('.ai-team/tasks.sqlite3')
cur = con.cursor()
p = cur.execute("SELECT * FROM projects WHERE id = 'spc-new-erp'").fetchone()
if p:
    print(p)
