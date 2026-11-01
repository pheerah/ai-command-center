import json
import hashlib
from pathlib import Path

req_path = Path('.ai-team/runs/4d128cf678ae/736d6d092b7f418e86b25d8c7f8fa579/request.json')
req = json.loads(req_path.read_text(encoding='utf-8'))
root = Path(req['worktree'])

for f in req.get('source_files', [])[:5]:
    name = f['path']
    target = root / name
    if target.exists():
        raw = target.read_bytes()
        norm = raw.replace(b'\r\n', b'\n')
        h_raw = hashlib.sha256(raw).hexdigest()
        h_norm = hashlib.sha256(norm).hexdigest()
        print(f'{name}:')
        print(f'  snapshot:   {f["sha256"]}')
        print(f'  raw disk:   {h_raw}')
        print(f'  normalized: {h_norm}')
