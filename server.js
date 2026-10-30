// Local read-only dashboard. All task mutations go through the durable CLI.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { execFile } = require('node:child_process');

const ROOT = path.resolve(process.env.AI_CENTER_ROOT || __dirname);
const PORT = Number(process.env.PORT || 3939);
const localPython = path.join(ROOT, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const PYTHON = process.env.AI_CENTER_PYTHON || (fs.existsSync(localPython) ? localPython : path.join(ROOT, '..', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'));

function snapshot(taskId) {
  const args = [path.join(ROOT, 'smart_router.py')];
  if (process.env.AI_CENTER_STATE_DIR) args.push('--state-dir', process.env.AI_CENTER_STATE_DIR);
  if (process.env.AI_CENTER_CONFIG) args.push('--config', process.env.AI_CENTER_CONFIG);
  args.push('status');
  if (taskId) args.push(taskId);
  else args.push('--usage');
  return new Promise((resolve, reject) => {
    execFile(PYTHON, args, { cwd: ROOT, timeout: 15000, maxBuffer: 2 * 1024 * 1024, windowsHide: true }, (error, stdout) => {
      try {
        const data = JSON.parse(stdout);
        if (error || data.error) reject(new Error(data.error || 'Center status unavailable'));
        else resolve(data);
      } catch { reject(new Error('Center status unavailable')); }
    });
  });
}

function createServer() {
  return http.createServer(async (req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'");
    const host = req.headers.host || '';
    if (!/^(127\.0\.0\.1|localhost)(:\d+)?$/.test(host)) {
      res.writeHead(403).end('Local requests only');
      return;
    }
    const origin = req.headers.origin;
    if (origin && ![`http://${host}`, `http://127.0.0.1:${PORT}`, `http://localhost:${PORT}`].includes(origin)) {
      res.writeHead(403).end('Origin rejected');
      return;
    }
    if (req.method !== 'GET') {
      res.writeHead(410, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: 'Direct AI execution and legacy mutations are disabled. Use the Center CLI.' }));
      return;
    }
    const url = new URL(req.url, `http://${host}`);
    try {
      if (url.pathname === '/') {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(fs.readFileSync(path.join(ROOT, 'center.html')));
      } else if (url.pathname === '/dashboard.js' || url.pathname === '/dashboard.css') {
        const filename = url.pathname.slice(1);
        res.writeHead(200, { 'Content-Type': filename.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/css; charset=utf-8' });
        res.end(fs.readFileSync(path.join(ROOT, filename)));
      } else if (url.pathname === '/api/health') {
        const data = await snapshot();
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: true, storage: data.storage, live_execution: data.live_execution }));
      } else if (url.pathname === '/api/status') {
        const data = await snapshot();
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(data));
      } else if (/^\/api\/tasks\/[a-zA-Z0-9_-]{1,64}$/.test(url.pathname)) {
        const data = await snapshot(url.pathname.split('/').pop());
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(data));
      } else if (['/api/router-usage', '/api/usage'].includes(url.pathname)) {
        const data = await snapshot();
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ updated: data.updated, ...data.providers, meter: data.usage }));
      } else {
        res.writeHead(404, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: 'Route not available' }));
      }
    } catch {
      res.writeHead(503, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: 'Center unavailable. Check doctor and service status; no worker was launched.' }));
    }
  });
}

if (require.main === module) {
  createServer().listen(PORT, '127.0.0.1', () => console.log(`Center dashboard: http://127.0.0.1:${PORT}`));
}
module.exports = { createServer };
