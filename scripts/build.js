const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const out = path.join(root, 'dist');
fs.mkdirSync(out, { recursive: true });
// Every backend/*.py is part of the app; a hand-kept list silently dropped modules before.
fs.mkdirSync(path.join(out, 'backend'), { recursive: true });
for (const name of fs.readdirSync(path.join(root, 'backend')).filter(file => file.endsWith('.py'))) {
  fs.copyFileSync(path.join(root, 'backend', name), path.join(out, 'backend', name));
}
for (const name of ['server.js', 'center.config.json', 'requirements.txt']) {
  fs.copyFileSync(path.join(root, name), path.join(out, name));
}
fs.cpSync(path.join(root, 'connector-template'), path.join(out, 'connector-template'), { recursive: true });
fs.cpSync(path.join(root, 'web'), path.join(out, 'web'), { recursive: true });
console.log(`Build copied app files to ${path.relative(root, out)}`);
