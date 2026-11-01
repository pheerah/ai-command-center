import { describe, it, expect, afterAll, beforeAll } from 'vitest';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { URL } from 'node:url';
const require = createRequire(import.meta.url);
const state = mkdtempSync(path.join(tmpdir(), 'center-http-'));
process.env.AI_CENTER_STATE_DIR = state;
const testConfig = JSON.parse(readFileSync(new URL('../center.config.json', import.meta.url)));
testConfig.live_execution = false;
process.env.AI_CENTER_CONFIG = path.join(state, 'config.json');
writeFileSync(process.env.AI_CENTER_CONFIG, JSON.stringify(testConfig));
const { createServer } = require('../server.js');
let server, base;
beforeAll(async () => { server = createServer(); await new Promise(resolve => server.listen(0, '127.0.0.1', resolve)); base = `http://127.0.0.1:${server.address().port}`; });
afterAll(async () => { await new Promise(resolve => server.close(resolve)); if (!state.startsWith(path.resolve(tmpdir()) + path.sep)) throw new Error('Unsafe cleanup path'); rmSync(state, { recursive: true, force: true }); });
describe('read-only Center dashboard', () => {
  it('serves the operational dashboard', async () => { const r = await fetch(base); expect(r.status).toBe(200); expect(await r.text()).toContain('AI Dev Command Center'); });
  it('serves the combined usage dashboard assets with a strict content policy', async () => { const r = await fetch(base); expect(await r.text()).toContain('Usage Meter'); expect(r.headers.get('content-security-policy')).not.toContain('unsafe-inline'); expect((await fetch(base + '/js/dashboard.js')).status).toBe(200); expect((await fetch(base + '/css/dashboard.css')).status).toBe(200); });
  it('serves static files only from web/ and refuses traversal, backslashes and unknown types', async () => {
    for (const bad of ['/assets/..%5c..%5cpackage.json', '/..%2f..%2fpackage.json', '/assets/%2e%2e/%2e%2e/package.json', '/js/..%5c..%5cserver.js', '/assets/full/README.md', '/server.js', '/package.json']) {
      const r = await fetch(base + bad);
      expect(r.status, bad).toBe(404);
    }
    expect((await fetch(base + '/assets/sec_white_blouse.png')).headers.get('content-type')).toBe('image/png');
  });
  it('lists which optional sprite images exist', async () => { const r = await fetch(base + '/api/sprites'); const d = await r.json(); expect(Array.isArray(d.cutout)).toBe(true); expect(Array.isArray(d.full)).toBe(true); expect(d.full).not.toContain('README'); });
  it('reads actual SQLite state without claiming a stopped scheduler is ready', async () => { const r = await fetch(base + '/api/health'); const data = await r.json(); expect(data).toMatchObject({ ok: true, backend: 'available', database: 'available', storage: 'sqlite', live_execution: false, ready: false, service: { running: false } }); });
  it('reports running scheduler mode and heartbeat separately from backend health', async () => {
    const fixture = createServer({ readSnapshot: async () => ({ storage: 'sqlite', live_execution: true, service: { running: true, mode: 'live', heartbeat_age_seconds: 2, reason: 'running' } }) });
    await new Promise(resolve => fixture.listen(0, '127.0.0.1', resolve));
    try {
      const response = await fetch(`http://127.0.0.1:${fixture.address().port}/api/health`);
      expect(await response.json()).toMatchObject({ ok: true, ready: true, service: { mode: 'live', heartbeat_age_seconds: 2 } });
    } finally { await new Promise(resolve => fixture.close(resolve)); }
  });
  it('does not report backend or scheduler ready when snapshot reading fails', async () => {
    const fixture = createServer({ readSnapshot: async () => { throw new Error('backend unavailable'); } });
    await new Promise(resolve => fixture.listen(0, '127.0.0.1', resolve));
    try { expect((await fetch(`http://127.0.0.1:${fixture.address().port}/api/health`)).status).toBe(503); }
    finally { await new Promise(resolve => fixture.close(resolve)); }
  });
  it('reports Google as available once its adapter is verified and keeps plan quota unknown here', async () => { const r = await fetch(base + '/api/usage'); const d = await r.json(); expect(d.google.availability).toBe('available'); expect(d.google.reason).toContain('agy_headless_adapter'); expect(d.codex.quota).toBe('unknown'); });
  it('exposes activity separately from unknown subscription quota', async () => { const r = await fetch(base + '/api/status'); const d = await r.json(); expect(d.usage.source).toBe('center_owned_cli_output'); expect(d.usage.quota).toBe('unknown'); expect(d.usage.providers.codex.days).toHaveLength(30); expect(d.usage.latest_observed_at).toBeNull(); });
  it('serves live plan quota from the injected reader and never from a model call', async () => {
    const fixture = createServer({ readLiveQuota: async () => ({ codex: { five_hour: { remaining_percent: 90 } }, claude: null, google: null }) });
    await new Promise(resolve => fixture.listen(0, '127.0.0.1', resolve));
    try {
      const response = await fetch(`http://127.0.0.1:${fixture.address().port}/api/quota`);
      expect(response.status).toBe(200);
      expect(await response.json()).toMatchObject({ codex: { five_hour: { remaining_percent: 90 } }, claude: null, google: null });
    } finally { await new Promise(resolve => fixture.close(resolve)); }
  });
  describe('project API /api/v1', () => {
    const calls = [];
    const fixture = () => createServer({
      lookupToken: header => (header === 'Bearer cc_alpha_token_aaaaaaaaaaaaaaaa' ? 'alpha' : null),
      callApi: async (project, request) => { calls.push({ project, request }); return { ok: true, status: 200, data: { echo: request.op } }; },
    });
    const withServer = async run => {
      const api = fixture();
      await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
      try { return await run(`http://127.0.0.1:${api.address().port}`); } finally { await new Promise(resolve => api.close(resolve)); }
    };
    const auth = { Authorization: 'Bearer cc_alpha_token_aaaaaaaaaaaaaaaa' };
    it('rejects missing, malformed and unknown tokens without calling the Center', async () => {
      calls.length = 0;
      await withServer(async url => {
        for (const headers of [{}, { Authorization: 'Bearer nope' }, { Authorization: 'Bearer cc_other_token_aaaaaaaaaaaaaaaaa' }, { Authorization: 'Basic abc' }]) {
          expect((await fetch(url + '/api/v1/tasks', { headers })).status).toBe(401);
        }
      });
      expect(calls).toHaveLength(0);
    });
    it('derives the project only from the token, never from the request', async () => {
      calls.length = 0;
      await withServer(async url => {
        const response = await fetch(url + '/api/v1/tasks', { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'x', project: 'beta', project_id: 'beta' }) });
        expect(response.status).toBe(200);
      });
      expect(calls[0].project).toBe('alpha');
      expect(calls[0].request.op).toBe('submit');
    });
    it('maps routes to operations and refuses unknown routes and non-JSON posts', async () => {
      calls.length = 0;
      await withServer(async url => {
        expect((await (await fetch(url + '/api/v1/tasks/0123456789ab', { headers: auth })).json()).echo).toBe('get');
        expect((await (await fetch(url + '/api/v1/tasks/0123456789ab/patch', { headers: auth })).json()).echo).toBe('patch');
        expect((await (await fetch(url + '/api/v1/tasks/0123456789ab/cancel', { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: '{}' })).json()).echo).toBe('cancel');
        expect((await fetch(url + '/api/v1/tasks/..%2F..%2Fsecret', { headers: auth })).status).toBe(404);
        expect((await fetch(url + '/api/v1/other', { headers: auth })).status).toBe(404);
        expect((await fetch(url + '/api/v1/tasks', { method: 'POST', headers: { ...auth, 'Content-Type': 'text/plain' }, body: 'x' })).status).toBe(415);
        expect((await fetch(url + '/api/v1/tasks', { method: 'DELETE', headers: auth })).status).toBe(404);
      });
    });
    it('limits request bodies and rejects foreign browser origins', async () => {
      await withServer(async url => {
        const big = await fetch(url + '/api/v1/tasks', { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: 'x'.repeat(70000) }) });
        expect(big.status).toBe(413);
        expect((await fetch(url + '/api/v1/tasks', { headers: { ...auth, Origin: 'https://evil.invalid' } })).status).toBe(403);
      });
    });
    it('never throttles a valid token no matter how many bad tokens were tried', async () => {
      await withServer(async url => {
        for (let attempt = 0; attempt < 25; attempt += 1) await fetch(url + '/api/v1/tasks', { headers: { Authorization: 'Bearer cc_wrong_wrong_wrong_wrong_wrong' } });
        expect((await fetch(url + '/api/v1/tasks', { headers: { Authorization: 'Bearer cc_wrong_wrong_wrong_wrong_wrong' } })).status).toBe(429);
        expect((await fetch(url + '/api/v1/tasks', { headers: auth })).status).toBe(200);
      });
    });
    it('answers 503 instead of piling up when too many calls are in flight', async () => {
      let release;
      const gate = new Promise(resolve => { release = resolve; });
      const api = createServer({ lookupToken: () => 'alpha', callApi: async () => { await gate; return { ok: true, status: 200, data: {} }; } });
      await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
      const base = `http://127.0.0.1:${api.address().port}`;
      try {
        const pending = Array.from({ length: 4 }, () => fetch(base + '/api/v1/tasks', { headers: auth }));
        await new Promise(resolve => setTimeout(resolve, 150));
        const busy = await fetch(base + '/api/v1/tasks', { headers: auth });
        expect(busy.status).toBe(503);
        expect(busy.headers.get('retry-after')).toBe('5');
        release();
        for (const response of await Promise.all(pending)) expect(response.status).toBe(200);
      } finally { release(); await new Promise(resolve => api.close(resolve)); }
    });
    it('returns the Center error shape without extra detail', async () => {
      const api = createServer({ lookupToken: () => 'alpha', callApi: async () => ({ ok: false, status: 404, error: 'Task not found' }) });
      await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
      try {
        const response = await fetch(`http://127.0.0.1:${api.address().port}/api/v1/tasks/0123456789ab`, { headers: auth });
        expect(response.status).toBe(404);
        expect(await response.json()).toEqual({ error: 'Task not found' });
      } finally { await new Promise(resolve => api.close(resolve)); }
    });
  });
  describe('live task view', () => {
    const task = 'abcdef012345';
    const older = 'a'.repeat(32);
    const newer = 'b'.repeat(32);
    const put = (session, name, text) => {
      const dir = path.join(state, 'runs', task, session);
      mkdirSync(dir, { recursive: true });
      writeFileSync(path.join(dir, name), text);
    };
    it('returns the tail of the newest run logs and never the request file', async () => {
      put(older, 'provider.log', 'old run');
      await new Promise(resolve => setTimeout(resolve, 30));
      put(newer, 'gate-0.log', 'line one' + String.fromCharCode(10) + 'line two');
      put(newer, 'provider.log', 'x'.repeat(9000) + 'END');
      put(newer, 'request.json', '{"prompt":"SECRET SOURCE CODE"}');
      put(newer, 'notes.txt', 'not a log');
      const data = await (await fetch(base + `/api/tasks/${task}/live`)).json();
      expect(data.session).toBe(newer);
      const names = data.files.map(file => file.name).sort();
      expect(names).toEqual(['gate-0.log', 'provider.log']);
      const provider = data.files.find(file => file.name === 'provider.log');
      expect(provider.truncated).toBe(true);
      expect(provider.tail.length).toBeLessThanOrEqual(6000);
      expect(provider.tail.endsWith('END')).toBe(true);
      expect(JSON.stringify(data)).not.toContain('SECRET SOURCE CODE');
      expect(JSON.stringify(data)).not.toContain('not a log');
    });
    it('masks obvious secrets in log output', async () => {
      put(newer, 'gate-1.log', 'Authorization: Bearer abcdefghijklmnop1234 and key sk-abcdefghijklmnopqrstuv and api_key=hunter2hunter2 ok');
      const data = await (await fetch(base + `/api/tasks/${task}/live`)).json();
      const text = data.files.find(file => file.name === 'gate-1.log').tail;
      expect(text).not.toContain('abcdefghijklmnop1234');
      expect(text).not.toContain('sk-abcdefghijklmnopqrstuv');
      expect(text).not.toContain('hunter2hunter2');
      expect(text).toContain('[masked]');
      expect(text).toContain(' ok');
    });
    it('answers an unknown task with no session and rejects ids that are not 12 hex characters', async () => {
      expect((await (await fetch(base + '/api/tasks/ffffffffffff/live')).json()).session).toBeNull();
      for (const bad of ['ZZZZZZZZZZZZ', 'abcdef01234', 'abcdef0123456', '..%2F..%2Fx']) {
        expect((await fetch(base + `/api/tasks/${bad}/live`)).status).toBe(404);
      }
    });
  });
  it('blocks legacy direct execution', async () => { for (const route of ['/api/chat/synthesize', '/api/project/run-task', '/api/config']) { const r = await fetch(base + route, { method: 'POST', body: '{}' }); expect(r.status).toBe(410); } });
  it('rejects foreign origins and unknown routes', async () => { expect((await fetch(base + '/api/status', { headers: { Origin: 'https://external.invalid' } })).status).toBe(403); expect((await fetch(base + '/api/browse')).status).toBe(404); });
  it('does not expose files or credentials', async () => { for (const route of ['/.env', '/server.js', '/.git/config']) expect((await fetch(base + route)).status).toBe(404); });
});

describe('secretary chat routes', () => {
  const calls = [];
  const json = { 'Content-Type': 'application/json' };
  const fixture = callApi => createServer({
    lookupToken: header => (header === 'Bearer cc_alpha_token_aaaaaaaaaaaaaaaa' ? 'alpha' : null),
    callApi: callApi || (async (project, request, timeoutMs) => { calls.push({ project, request, timeoutMs }); return { ok: true, status: 200, data: { echo: request.op } }; }),
  });
  const withServer = async (run, callApi) => {
    const api = fixture(callApi);
    await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
    try { return await run(`http://127.0.0.1:${api.address().port}`); } finally { await new Promise(resolve => api.close(resolve)); }
  };
  const post = (url, path, body, headers = json) => fetch(url + path, { method: 'POST', headers, body: typeof body === 'string' ? body : JSON.stringify(body) });

  it('forwards a message, the history request and a confirmation to the matching Center operation', async () => {
    calls.length = 0;
    await withServer(async url => {
      const sent = await post(url, '/api/chat', { project_id: 'alpha', message: 'hello', client_turn_id: 'turn-00000001' });
      expect(sent.status).toBe(200);
      expect((await sent.json()).echo).toBe('chat');
      expect((await (await fetch(url + '/api/chat/history?project_id=alpha')).json()).echo).toBe('chat_history');
      const confirmed = await post(url, '/api/chat/confirm', { project_id: 'alpha', message_id: 7, edits: { title: 'x' } });
      expect((await confirmed.json()).echo).toBe('chat_confirm');
    });
    expect(calls.map(c => c.request.op)).toEqual(['chat', 'chat_history', 'chat_confirm']);
    expect(calls[0]).toMatchObject({ project: 'alpha', request: { op: 'chat', body: { message: 'hello', client_turn_id: 'turn-00000001' } } });
    expect(calls[2].request.body).toEqual({ message_id: 7, edits: { title: 'x' } });
    expect(calls[0].timeoutMs).toBe(100000);
  });

  it('refuses a missing or malformed project id, bad bodies and non-JSON posts without calling the Center', async () => {
    calls.length = 0;
    await withServer(async url => {
      for (const bad of [undefined, '', '../x', 'UP PER', '-lead', 'a'.repeat(65), 5]) {
        expect((await post(url, '/api/chat', { project_id: bad, message: 'hi', client_turn_id: 'turn-00000001' })).status, String(bad)).toBe(400);
      }
      expect((await post(url, '/api/chat', { project_id: 'alpha', message: 5, client_turn_id: 'turn-00000001' })).status).toBe(400);
      expect((await post(url, '/api/chat', { project_id: 'alpha', message: 'hi' })).status).toBe(400);
      expect((await post(url, '/api/chat/confirm', { project_id: 'alpha' })).status).toBe(400);
      expect((await post(url, '/api/chat', '{not json')).status).toBe(400);
      expect((await post(url, '/api/chat', 'x', { 'Content-Type': 'text/plain' })).status).toBe(415);
      expect((await fetch(url + '/api/chat/history')).status).toBe(400);
    });
    expect(calls).toHaveLength(0);
  });

  it('is browser-only: a foreign origin is refused, project tokens cannot reach it and the old route shape stays closed', async () => {
    calls.length = 0;
    await withServer(async url => {
      expect((await post(url, '/api/chat', { project_id: 'alpha', message: 'hi', client_turn_id: 'turn-00000001' }, { ...json, Origin: 'https://evil.invalid' })).status).toBe(403);
      const auth = { Authorization: 'Bearer cc_alpha_token_aaaaaaaaaaaaaaaa' };
      for (const route of ['/api/v1/chat', '/api/v1/chat/history', '/api/v1/chat/confirm']) {
        expect((await post(url, route, { message: 'hi', client_turn_id: 'turn-00000001' }, { ...auth, ...json })).status, route).toBe(404);
      }
      expect((await fetch(url + '/api/chat')).status).not.toBe(200);
      expect((await post(url, '/api/chat/synthesize', {})).status).toBe(410);
    });
    expect(calls).toHaveLength(0);
  });

  it('answers a Center failure with its status and message, and says so when the Center is busy', async () => {
    await withServer(async url => {
      const failed = await post(url, '/api/chat', { project_id: 'alpha', message: 'hi', client_turn_id: 'turn-00000001' });
      expect(failed.status).toBe(409);
      expect((await failed.json()).error).toBe('nope');
    }, async () => ({ ok: false, status: 409, error: 'nope' }));
    const release = [];
    await withServer(async url => {
      const open = [1, 2, 3, 4].map(n => post(url, '/api/chat', { project_id: 'alpha', message: 'hi', client_turn_id: `turn-0000000${n}` }));
      await new Promise(resolve => setTimeout(resolve, 150));
      const busy = await post(url, '/api/chat', { project_id: 'alpha', message: 'hi', client_turn_id: 'turn-00000005' });
      expect(busy.status).toBe(503);
      release.forEach(fn => fn());
      expect((await Promise.all(open)).map(r => r.status)).toEqual([200, 200, 200, 200]);
    }, () => new Promise(resolve => release.push(() => resolve({ ok: true, status: 200, data: {} }))));
  });
});
