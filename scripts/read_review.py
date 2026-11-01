import sqlite3, json
con = sqlite3.connect('.ai-team/tasks.sqlite3')
cur = con.cursor()
row = cur.execute("SELECT payload FROM evidence WHERE task_id='c71a02aec12b' AND kind='review' ORDER BY id DESC LIMIT 1").fetchone()
if row:
    data = json.loads(row[0])
    print('Reviewer verdict:', data.get('verdict'))
    print('Reviewer summary:', data.get('summary'))
