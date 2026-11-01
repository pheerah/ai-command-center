import json

with open('center.config.json', 'r', encoding='utf-8') as f:
    cfg = json.load(f)

cfg['worker_timeout_seconds'] = 1800
cfg['auto_retry'] = True

with open('center.config.json', 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2)

print("SUCCESS: center.config.json updated")
