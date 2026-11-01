from pathlib import Path
log = Path('.ai-team/runs/ea90d4340e37/76242a9e5093434ba15a8b6462424585/gate-1.log')
text = log.read_text(encoding='utf-8', errors='replace')
lines = [l for l in text.splitlines() if 'FAIL' in l or 'error' in l.lower() or 'cannot' in l.lower()]
for l in lines[:30]:
    print(l.encode('ascii', errors='replace').decode('ascii'))
