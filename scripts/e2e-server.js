// Build real mock evidence in two isolated repositories before browser tests.
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const result = spawnSync(python, [path.join(root, 'scripts/demo.py')], { cwd: root, encoding: 'utf8', timeout: 60000, windowsHide: true });
if (result.status !== 0) {
  console.error(result.stderr || result.error?.message || 'Mock fixture failed');
  process.exit(1);
}
const report = JSON.parse(result.stdout);
process.env.AI_CENTER_STATE_DIR = report.state_dir;
process.env.AI_CENTER_CONFIG = report.config;
require('../server.js').createServer().listen(Number(process.env.PORT || 3941), '127.0.0.1');
