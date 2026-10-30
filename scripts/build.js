const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const out = path.join(root, 'dist');
fs.mkdirSync(out, { recursive: true });
for (const name of ['center.html', 'server.js', 'smart_router.py', 'center_store.py', 'center_runtime.py', 'center_worker.py', 'center_process.py', 'center_workspace.py', 'center_context.py', 'center_usage.py', 'center.config.json', 'requirements.txt']) {
  fs.copyFileSync(path.join(root, name), path.join(out, name));
}
fs.cpSync(path.join(root, 'connector-template'), path.join(out, 'connector-template'), { recursive: true });
for (const name of ['dashboard.js', 'dashboard.css']) fs.copyFileSync(path.join(root, name), path.join(out, name));
console.log(`Build copied app files to ${path.relative(root, out)}`);
