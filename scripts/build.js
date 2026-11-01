const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const out = path.join(root, 'dist');
fs.mkdirSync(out, { recursive: true });
// Every center_*.py is part of the app; a hand-kept list silently dropped modules (center_capacity.py was already missing).
const modules = fs.readdirSync(root).filter(name => /^center_[a-z_]+\.py$/.test(name));
for (const name of ['server.js', 'smart_router.py', ...modules, 'center.config.json', 'requirements.txt']) {
  fs.copyFileSync(path.join(root, name), path.join(out, name));
}
fs.cpSync(path.join(root, 'connector-template'), path.join(out, 'connector-template'), { recursive: true });
fs.cpSync(path.join(root, 'web'), path.join(out, 'web'), { recursive: true });
console.log(`Build copied app files to ${path.relative(root, out)}`);
