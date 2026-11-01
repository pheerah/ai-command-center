// One command to bring the Center up for development: `npm run dev`.
//   npm run dev                 dashboard (auto-restarts when server.js changes) + scheduler (live)
//   npm run dev -- --mode mock  same, but the scheduler only runs mock work
//   npm run dev:ui              dashboard only, scheduler left alone
// Ctrl+C stops what this script started. A scheduler that was already running is never touched.
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const python = process.env.AI_CENTER_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const port = process.env.PORT || 3939;
const args = process.argv.slice(2);
const withScheduler = !args.includes('--no-scheduler');
const modeIndex = args.indexOf('--mode');
const mode = modeIndex >= 0 ? args[modeIndex + 1] : 'live';
if (!['live', 'mock'].includes(mode)) {
  console.error(`--mode must be live or mock, got "${mode}"`);
  process.exit(2);
}

function schedulerRunning() {
  const result = spawnSync(python, ['smart_router.py', 'service-status'], { cwd: root, encoding: 'utf8', windowsHide: true, timeout: 15000 });
  try { return JSON.parse(result.stdout).running === true; } catch { return false; }
}

const children = [];
let startedScheduler = false;

function run(label, command, commandArgs) {
  const child = spawn(command, commandArgs, { cwd: root, stdio: 'inherit', windowsHide: true });
  child.on('exit', (code) => {
    if (!shuttingDown) {
      console.error(`[dev] ${label} exited (${code}); stopping the rest`);
      shutdown(code || 1);
    }
  });
  children.push(child);
  return child;
}

let shuttingDown = false;
function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  if (startedScheduler) spawnSync(python, ['smart_router.py', 'stop'], { cwd: root, windowsHide: true, timeout: 15000 });
  for (const child of children) child.kill();
  process.exit(code);
}
process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));

if (!fs.existsSync(python)) {
  console.error(`Python not found at ${python}. Create .venv first (see README) or set AI_CENTER_PYTHON.`);
  process.exit(1);
}

if (withScheduler) {
  if (schedulerRunning()) {
    console.log('[dev] scheduler already running; leaving it alone');
  } else {
    console.log(`[dev] starting scheduler (${mode})`);
    startedScheduler = true;
    run('scheduler', python, ['smart_router.py', 'serve', '--mode', mode]);
  }
}
console.log(`[dev] dashboard: http://127.0.0.1:${port}`);
run('dashboard', process.execPath, ['--watch', 'server.js']);
