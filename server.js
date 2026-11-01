// Local read-only dashboard. All task mutations go through the durable CLI.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFile } = require('node:child_process');

const ROOT = path.resolve(process.env.AI_CENTER_ROOT || __dirname);
const PORT = Number(process.env.PORT || 3939);
const localPython = path.join(ROOT, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const PYTHON = process.env.AI_CENTER_PYTHON || (fs.existsSync(localPython) ? localPython : path.join(ROOT, '..', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'));

const WEB_ROOT = path.join(ROOT, 'web');
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml',
};
const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.svg']);

// The one place that maps a URL to a file under web/. Anything that resolves outside it, uses a backslash,
// has an unknown extension or is a link pointing elsewhere is refused.
function resolveWebFile(pathname) {
  let rel;
  try { rel = decodeURIComponent(pathname); } catch { return null; }
  if (rel === '/' || rel === '/center.html') rel = '/index.html';
  if (rel.includes('\u0000') || rel.includes('\\')) return null;
  const file = path.resolve(WEB_ROOT, '.' + rel);
  if (!file.startsWith(WEB_ROOT + path.sep) || !MIME[path.extname(file).toLowerCase()]) return null;
  try {
    const real = fs.realpathSync(file);
    return real.startsWith(fs.realpathSync(WEB_ROOT) + path.sep) && fs.statSync(real).isFile() ? real : null;
  } catch { return null; }
}

function serveStatic(res, pathname) {
  const file = resolveWebFile(pathname);
  if (!file) { res.writeHead(404).end('Not found'); return; }
  const ext = path.extname(file).toLowerCase();
  const headers = { 'Content-Type': MIME[ext] };
  if (IMAGE_EXTENSIONS.has(ext)) headers['Cache-Control'] = 'public, max-age=86400';
  res.writeHead(200, headers);
  res.end(fs.readFileSync(file));
}

// Which optional sprite images exist, so the browser only requests files that are there.
function listSprites() {
  const names = (dir) => { try { return fs.readdirSync(path.join(WEB_ROOT, 'assets', dir)).filter(f => /\.png$/i.test(f)).map(f => f.replace(/\.png$/i, '')); } catch { return []; } };
  return { cutout: names('cutout'), full: names('full') };
}

function snapshot(taskId) {
  const args = [path.join(ROOT, 'backend', 'smart_router.py')];
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

// Plan quota is observed by the scheduler (center_quota.py, one owner) and stored in the state directory.
// The dashboard only reads that snapshot, so routing and the page can never disagree.
function readQuota() {
  const stateDir = process.env.AI_CENTER_STATE_DIR || path.join(ROOT, '.ai-team');
  try {
    const data = JSON.parse(fs.readFileSync(path.join(stateDir, 'quota-last.json'), 'utf8'));
    return { codex: data.codex || null, claude: data.claude || null, google: data.google || null };
  } catch { return { codex: null, claude: null, google: null }; }
}

// ---- Project API (/api/v1) --------------------------------------------------------------------------------------
// Other projects call the Center only here. A bearer token is bound to one registered project; the answer is built
// by center_api.py from an allowlist, so no Center path or file ever reaches the caller.
const stateDir = () => process.env.AI_CENTER_STATE_DIR || path.join(ROOT, '.ai-team');
const tokenCache = { mtime: 0, data: {} };

function projectForToken(header) {
  const match = /^Bearer (cc_[A-Za-z0-9_-]{20,80})$/.exec(header || '');
  if (!match) return null;
  const file = path.join(stateDir(), 'api-tokens.json');
  try {
    const mtime = fs.statSync(file).mtimeMs;
    if (mtime !== tokenCache.mtime) { tokenCache.data = JSON.parse(fs.readFileSync(file, 'utf8')); tokenCache.mtime = mtime; }
  } catch { return null; }
  const entry = tokenCache.data[crypto.createHash('sha256').update(match[1]).digest('hex')];
  return entry && !entry.revoked ? entry.project_id : null;
}

function callCenterApi(projectId, request) {
  const args = [path.join(ROOT, 'backend', 'smart_router.py')];
  if (process.env.AI_CENTER_STATE_DIR) args.push('--state-dir', process.env.AI_CENTER_STATE_DIR);
  if (process.env.AI_CENTER_CONFIG) args.push('--config', process.env.AI_CENTER_CONFIG);
  args.push('--project-id', projectId, 'api-call');
  return new Promise(resolve => {
    const child = execFile(PYTHON, args, { cwd: ROOT, timeout: 60000, maxBuffer: 16 * 1024 * 1024, windowsHide: true }, (error, stdout) => {
      try { resolve(JSON.parse(stdout)); } catch { resolve({ ok: false, status: 503, error: 'Center unavailable' }); }
    });
    child.stdin.end(JSON.stringify(request));
  });
}

const failedAuth = { windowStart: 0, count: 0 };
const MAX_INFLIGHT = 4;
let inflight = 0;
const V1_ROUTES = [
  ['GET', /^\/api\/v1\/health$/, () => ({ op: 'health' })],
  ['GET', /^\/api\/v1\/tasks$/, () => ({ op: 'list' })],
  ['POST', /^\/api\/v1\/tasks$/, (m, body) => ({ op: 'submit', body })],
  ['GET', /^\/api\/v1\/tasks\/([a-f0-9]{12})$/, m => ({ op: 'get', task_id: m[1] })],
  ['POST', /^\/api\/v1\/tasks\/([a-f0-9]{12})\/cancel$/, m => ({ op: 'cancel', task_id: m[1] })],
  ['GET', /^\/api\/v1\/tasks\/([a-f0-9]{12})\/patch$/, m => ({ op: 'patch', task_id: m[1] })],
];

function readBody(req, limit = 65536) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', chunk => { size += chunk.length; if (size <= limit) chunks.push(chunk); });
    req.on('end', () => (size > limit ? reject(new Error('too large')) : resolve(Buffer.concat(chunks).toString('utf8'))));
    req.on('error', reject);
  });
}

async function handleV1(req, res, url, { lookupToken, callApi }) {
  const send = (status, body) => res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(body));
  const projectId = lookupToken(req.headers.authorization);
  if (!projectId) {
    // Only invalid tokens are throttled, so a stranger guessing tokens can never lock a valid project out.
    if (Date.now() - failedAuth.windowStart > 60000) Object.assign(failedAuth, { windowStart: Date.now(), count: 0 });
    if (failedAuth.count >= 20) return send(429, { error: 'Too many failed attempts; try again in a minute' });
    failedAuth.count += 1;
    return send(401, { error: 'Unauthorized' });
  }
  const route = V1_ROUTES.find(([method, pattern]) => method === req.method && pattern.test(url.pathname));
  if (!route) return send(404, { error: 'Route not available' });
  let body = {};
  if (req.method === 'POST') {
    if (!/^application\/json(;|$)/i.test(req.headers['content-type'] || '')) return send(415, { error: 'Content-Type must be application/json' });
    let raw;
    try { raw = await readBody(req); } catch { return send(413, { error: 'Body is limited to 64 KB' }); }
    try { body = JSON.parse(raw || '{}'); } catch { return send(400, { error: 'Body must be valid JSON' }); }
  }
  // Each call starts a Python process, so cap concurrency; a busy Center says so instead of piling up.
  if (inflight >= MAX_INFLIGHT) { res.setHeader('Retry-After', '5'); return send(503, { error: 'Center is busy; retry shortly' }); }
  inflight += 1;
  let answer;
  try { answer = await callApi(projectId, route[2](route[1].exec(url.pathname), body)); } finally { inflight -= 1; }
  return send(answer.status || 500, answer.ok ? answer.data : { error: answer.error || 'Request failed' });
}

// ---- Live view of one task: the tail of the newest run's log files (read-only, owner's dashboard) --------------------------
// Only *.log files inside runs/<task>/<session>/ are read (never request.json, which holds prompts and sources), the task id
// and session names must be hex, symlinks are skipped, and obvious secrets are masked. Masking is best effort.
const LIVE_TAIL_BYTES = 6000;
const LIVE_MAX_FILES = 6;
const SECRET_PATTERN = /(sk-[A-Za-z0-9_-]{16,}|cc_[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,}|(?:token|secret|password|api[_-]?key)["']?\s*[:=]\s*["']?[^\s"',]{6,})/gi;

function readTaskLive(taskId) {
  const base = path.join(stateDir(), 'runs', taskId);
  let newest = null;
  try {
    for (const entry of fs.readdirSync(base, { withFileTypes: true })) {
      if (!entry.isDirectory() || !/^[a-f0-9]{32}$/.test(entry.name)) continue;
      const mtime = fs.statSync(path.join(base, entry.name)).mtimeMs;
      if (!newest || mtime > newest.mtime) newest = { name: entry.name, mtime };
    }
  } catch { return { session: null, files: [], now: Date.now() }; }
  if (!newest) return { session: null, files: [], now: Date.now() };
  const dir = path.join(base, newest.name);
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isFile() || !/^[A-Za-z0-9._-]{1,80}\.log$/.test(entry.name)) continue;
    const stat = fs.statSync(path.join(dir, entry.name));
    files.push({ name: entry.name, size: stat.size, mtime: stat.mtimeMs });
  }
  files.sort((a, b) => b.mtime - a.mtime);
  const shown = files.slice(0, LIVE_MAX_FILES).map(file => {
    let tail = '';
    try {
      const fd = fs.openSync(path.join(dir, file.name), 'r');
      try {
        const length = Math.min(file.size, LIVE_TAIL_BYTES);
        const buffer = Buffer.alloc(length);
        fs.readSync(fd, buffer, 0, length, file.size - length);
        tail = buffer.toString('utf8');
      } finally { fs.closeSync(fd); }
    } catch { tail = ''; }
    return { name: file.name, size: file.size, age_seconds: Math.max(0, Math.round((Date.now() - file.mtime) / 1000)), truncated: file.size > LIVE_TAIL_BYTES, tail: tail.replace(SECRET_PATTERN, '[masked]') };
  });
  return { session: newest.name, session_age_seconds: Math.max(0, Math.round((Date.now() - newest.mtime) / 1000)), files: shown, all_log_files: files.map(f => f.name), now: Date.now() };
}

function createServer({ readSnapshot = snapshot, readLiveQuota = readQuota, readLive = readTaskLive, lookupToken = projectForToken, callApi = callCenterApi } = {}) {
  return http.createServer(async (req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'");
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
    if (req.url.startsWith('/api/v1/')) {
      try { await handleV1(req, res, new URL(req.url, `http://${host}`), { lookupToken, callApi }); }
      catch { if (!res.headersSent) res.writeHead(500, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: 'Request failed' })); }
      return;
    }
    const url = new URL(req.url, `http://${host}`);
    if (req.method === 'POST' && url.pathname === '/api/dispatch') {
      let body = {};
      try {
        const raw = await readBody(req);
        body = JSON.parse(raw);
      } catch {
        res.writeHead(400, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: 'Invalid JSON body' }));
        return;
      }
      const { project_id, prompt } = body;
      if (!project_id || !prompt || !prompt.trim()) {
        res.writeHead(400, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: 'Project and prompt are required' }));
        return;
      }
      let projectRoot = null;
      try {
        const snap = await readSnapshot();
        const p = (snap.projects || []).find(x => x.id === project_id);
        if (p) projectRoot = p.root_path;
      } catch {}
      if (!projectRoot || !fs.existsSync(projectRoot)) {
        res.writeHead(404, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: `Project '${project_id}' not found` }));
        return;
      }
      const connectorPy = path.join(projectRoot, 'connector.py');
      if (!fs.existsSync(connectorPy)) {
        res.writeHead(500, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: `connector.py missing in project root` }));
        return;
      }
      const args = [connectorPy, 'plan', prompt.trim(), '--submit'];
      execFile(PYTHON, args, { cwd: projectRoot, timeout: 60000, maxBuffer: 4 * 1024 * 1024, windowsHide: true }, (error, stdout, stderr) => {
        try {
          const data = JSON.parse(stdout);
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: true, data }));
        } catch {
          if (error) {
            res.writeHead(500, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: stderr || stdout || error.message }));
          } else {
            res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: true, raw: stdout }));
          }
        }
      });
      return;
    }
    if (req.method === 'POST' && /^\/api\/tasks\/[a-f0-9]{12}\/approve$/.test(url.pathname)) {
      const taskId = url.pathname.split('/')[3];
      const args = [path.join(ROOT, 'backend', 'smart_router.py')];
      if (process.env.AI_CENTER_STATE_DIR) args.push('--state-dir', process.env.AI_CENTER_STATE_DIR);
      if (process.env.AI_CENTER_CONFIG) args.push('--config', process.env.AI_CENTER_CONFIG);
      args.push('approve', taskId, '--yes');
      execFile(PYTHON, args, { cwd: ROOT, timeout: 30000, maxBuffer: 4 * 1024 * 1024, windowsHide: true }, (error, stdout) => {
        try {
          const data = JSON.parse(stdout);
          if (error || data.error) {
            res.writeHead(500, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: data.error || (error && error.message) }));
          } else {
            res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: true, data }));
          }
        } catch {
          res.writeHead(500, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: 'Approval execution failed' }));
        }
      });
      return;
    }
    if (req.method !== 'GET') {
      res.writeHead(410, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: 'Direct AI execution and legacy mutations are disabled. Use the Center CLI.' }));
      return;
    }
    try {
      if (!url.pathname.startsWith('/api/')) {
        serveStatic(res, url.pathname);
      } else if (url.pathname === '/api/sprites') {
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(listSprites()));
      } else if (url.pathname === '/api/health') {
        const data = await readSnapshot();
        const service = data.service || { running: false, mode: 'unknown', reason: 'not_observed', heartbeat_age_seconds: null };
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({
          ok: true, backend: 'available', database: 'available', storage: data.storage,
          live_execution: data.live_execution, ready: service.running === true, service,
        }));
      } else if (url.pathname === '/api/status') {
        const data = await readSnapshot();
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(data));
      } else if (/^\/api\/tasks\/[a-f0-9]{12}\/live$/.test(url.pathname)) {
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(readLive(url.pathname.split('/')[3])));
      } else if (/^\/api\/tasks\/[a-zA-Z0-9_-]{1,64}$/.test(url.pathname)) {
        const data = await readSnapshot(url.pathname.split('/').pop());
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(data));
      } else if (url.pathname === '/api/quota') {
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ updated: new Date().toISOString(), ...(await readLiveQuota()) }));
      } else if (['/api/router-usage', '/api/usage'].includes(url.pathname)) {
        const data = await readSnapshot();
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
  const server = createServer();
  server.on('error', (error) => {
    if (error.code !== 'EADDRINUSE') throw error;
    console.error(`Port ${PORT} is already in use (an earlier dashboard is probably still running).`);
    console.error(`Stop it (stop_center.bat) or pick another port: set PORT=${PORT + 1} && npm run dev`);
    process.exit(1);
  });
  server.listen(PORT, '127.0.0.1', () => console.log(`Center dashboard: http://127.0.0.1:${PORT}`));
}
module.exports = { createServer };
