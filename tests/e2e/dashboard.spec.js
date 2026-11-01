const { test, expect } = require('@playwright/test');
// The Virtual Office is the default view; these tests exercise the board, so select it up front.
test.beforeEach(async ({ page }) => { await page.addInitScript(() => localStorage.setItem('center-view-mode', 'board')); });
test('dashboard shows durable state on the monitor tab and provider cards on the separate usage tab', async ({ page }) => {
  await page.route('**/api/quota', route => route.fulfill({ json: { updated: 'fixture', codex: null, claude: null, google: null } }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'AI Dev Command Center' })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('เชื่อมต่อแล้ว');
  await expect(page.locator('#scheduler-state')).toContainText('หยุดอยู่');
  await expect(page.locator('#scheduler-note')).toContainText('หน้าเว็บและฐานข้อมูลเชื่อมต่อได้');
  await expect(page.locator('#live')).toHaveText('ปิดไว้');
  await expect(page.locator('#tasks')).toContainText('sample-a');
  await expect(page.locator('#tasks')).toContainText('sample-b');
  await expect(page.locator('#tasks')).toContainText('waiting_for_independent_review');
  await expect(page.getByRole('heading', { name: 'Usage Meter', exact: true })).toBeHidden();
  await page.getByRole('button', { name: 'ดู', exact: true }).first().click();
  await expect(page.locator('#task-drawer')).toBeVisible();
  await expect(page.locator('#task-view')).toContainText('ภาพรวม');
  await expect(page.locator('#task-view')).toContainText('ไทม์ไลน์เหตุการณ์ทั้งหมด');
  await expect(page.locator('#detail')).toContainText('mock_pipeline_complete');
  await expect(page.locator('#detail')).toContainText('patch_hash');
  await page.keyboard.press('Escape');
  await expect(page.locator('#task-drawer')).toBeHidden();
  await page.getByRole('button', { name: 'อัปเดตสถานะ' }).click();
  await expect(page.getByRole('status')).toContainText('เชื่อมต่อแล้ว');
  await page.getByRole('tab', { name: 'Usage Meter' }).click();
  await expect(page.getByRole('heading', { name: 'Usage Meter', exact: true })).toBeVisible();
  await expect(page.locator('#providers')).toContainText('ChatGPT');
  await expect(page.locator('#providers')).toContainText('ไม่พบแหล่งข้อมูล quota');
  await expect(page.locator('#usage-note')).toContainText('ยังไม่มีข้อมูล token');
  await page.screenshot({ path: '.ai-team/dashboard-preview.png', fullPage: true });
});
test('the monitor and the usage meter are separate tabs and the choice survives a reload and a deep link', async ({ page }) => {
  await page.route('**/api/quota', route => route.fulfill({ json: { updated: 'fixture', codex: null, claude: null, google: null } }));
  await page.goto('/');
  await expect(page.getByRole('tab', { name: 'Monitor งาน' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#board')).toBeVisible();
  await expect(page.locator('#queue')).toBeVisible();
  await expect(page.locator('#usage')).toBeHidden();
  await expect(page.locator('#providers')).toBeHidden();
  await page.getByRole('tab', { name: 'Usage Meter' }).click();
  await expect(page).toHaveURL(/#usage$/);
  await expect(page.locator('#usage')).toBeVisible();
  await expect(page.locator('#board')).toBeHidden();
  await expect(page.locator('#queue')).toBeHidden();
  await expect(page.getByRole('tab', { name: 'Usage Meter' })).toHaveAttribute('aria-selected', 'true');
  await page.reload();
  await expect(page.locator('#usage')).toBeVisible();
  await page.goto('/#monitor');
  await expect(page.locator('#board')).toBeVisible();
  await expect(page.locator('#usage')).toBeHidden();
});
test('usage totals and the daily chart are on the usage tab, apart from the task monitor', async ({ page }) => {
  await page.route('**/api/quota', route => route.fulfill({ json: { updated: 'fixture', codex: null, claude: null, google: null } }));
  // Synthetic browser fixture only; it is never written to production usage.
  await page.route('**/api/status', async route => {
    const response = await route.fetch();
    const data = await response.json();
    const today = data.usage.providers.codex.days.at(-1);
    Object.assign(today, { input_tokens: 100, output_tokens: 20, cached_input_tokens: 60, total_tokens: 120, observed_invocations: 1 });
    today.workloads.tasks = 1;
    await route.fulfill({ json: data });
  });
  await page.goto('/#usage');
  await expect(page.locator('#usage-total')).toHaveText('120');
  await expect(page.locator('#providers')).not.toContainText('tokens');  // per-card token totals were removed on purpose; the daily chart keeps them
  await expect(page.locator('#usage-chart').getByRole('img')).toHaveCount(7);
  await expect(page.locator('#tasks')).toBeHidden();
  await page.getByLabel('ช่วงเวลา Usage Meter').selectOption('1');
  await expect(page.locator('#usage-chart').getByRole('img')).toHaveCount(1);
  await expect(page.locator('#providers')).toContainText('5 ชั่วโมง · เหลือ');
  await expect(page.locator('#providers')).toContainText('ไม่ทราบ');
  await page.screenshot({ path: '.ai-team/dashboard-test-fixture.png', fullPage: true });
});
test('every provider meter renders, including Google groups, with stale values labelled', async ({ page }) => {
  const window = (left, minutes) => ({ used_percent: 100 - left, remaining_percent: left, window_minutes: minutes, resets_at: '2026-11-01T00:00:00Z' });
  await page.route('**/api/quota', route => route.fulfill({ json: {
    updated: 'fixture',
    codex: { five_hour: window(95, 300), weekly: window(63, 10080), observed_at: '2026-10-31T09:00:00Z', stale: false },
    claude: { five_hour: window(55, 300), weekly: window(21, 10080), observed_at: '2026-10-31T09:00:00Z', stale: true },
    google: { groups: { 'Gemini Models': { five_hour: window(99, 300), weekly: window(99.5, 10080) }, 'Claude and GPT models': { five_hour: window(100, 300), weekly: window(49.8, 10080) } }, observed_at: '2026-10-31T09:00:00Z', stale: false },
  } }));
  await page.goto('/#usage');
  const providers = page.locator('#providers');
  await expect(providers).toContainText('95%');
  await expect(providers).toContainText('21%');
  await expect(providers).toContainText('Gemini Models');
  await expect(providers).toContainText('Claude and GPT models');
  await expect(providers).toContainText('49.8%');
  await expect(providers).toContainText('ใช้ค่าเดิมไปก่อน');
  await expect(providers).not.toContainText('ไม่พบแหล่งข้อมูล quota');
});
test('board shows who is running what, and groups tasks as todo / doing / review / approve / done / problem', async ({ page }) => {
  const plan = (provider, model, effort, skills) => ({ provider, model, effort, skills });
  const task = (id, project, title, status, extra = {}) => ({ id, project_id: project, title, status, provider: null, reviewer: null, attempt: 1, mode: 'live', error: null,
    updated_at: new Date(Date.now() - 120000).toISOString(), waiting_reason: null, plan: {}, ...extra });
  await page.route('**/api/status', async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.projects = [{ id: 'horoscope' }, { id: 'billing' }];
    data.tasks = [
      task('a1', 'horoscope', 'Add cn tests', 'running', { provider: 'codex', plan: { implementation: plan('codex', 'gpt-6-luna', 'low', ['test-driven-development']) } }),
      task('a2', 'horoscope', 'Fix login bug', 'queued', { waiting_reason: 'global_capacity' }),
      task('a3', 'billing', 'Refactor invoice', 'review', { provider: 'claude', plan: { implementation: plan('claude', 'claude-sonnet-5-5', 'medium', []), review: plan('codex', 'gpt-6-sol', 'medium', ['independent-code-review']) } }),
      task('a4', 'billing', 'Docs for API', 'ready_for_human_approval'),
      task('a5', 'horoscope', 'Old task', 'approved'),
      task('a6', 'billing', 'Broken task', 'failed', { error: 'quality_gate_failed' }),
    ];
    data.sessions = [
      { id: 's1', task_id: 'a1', provider: 'codex', role: 'implementation', adapter: 'live', model: 'gpt-6-luna', started_at: new Date(Date.now() - 60000).toISOString(), created_at: '' },
      { id: 's2', task_id: 'a3', provider: 'codex', role: 'review', adapter: 'live', model: 'gpt-6-sol', started_at: null, created_at: '' },
    ];
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  const running = page.locator('#running-now');
  await expect(running).toContainText('กำลังรันอยู่ตอนนี้ (2 session)');
  await expect(running).toContainText('ChatGPT');
  await expect(running).toContainText('gpt-6-luna · effort low');
  await expect(running).toContainText('horoscope › Add cn tests');
  await expect(running).toContainText('ยังไม่ยืนยันว่าเริ่ม');
  const columns = page.locator('#board-columns');
  await expect(columns.locator('.board-todo')).toContainText('ต้องทำ (รอคิว) (1)');
  await expect(columns.locator('.board-doing')).toContainText('Add cn tests');
  await expect(columns.locator('.board-doing')).toContainText('AI กำลังเขียนโค้ด');
  await expect(columns.locator('.board-doing')).toContainText('เขียน: ChatGPT · gpt-6-luna · effort low · test-driven-development');
  await expect(columns.locator('.board-review')).toContainText('ตรวจ: ChatGPT · gpt-6-sol · effort medium');
  await expect(columns.locator('.board-approve')).toContainText('Docs for API');
  await expect(columns.locator('.board-done')).toContainText('Old task');
  await expect(columns.locator('.board-problem')).toContainText('Broken task');
  await page.locator('#board-project').selectOption('billing');
  await expect(running).toContainText('กำลังรันอยู่ตอนนี้ (1 session)');
  await expect(columns.locator('.board-doing')).not.toContainText('Add cn tests');
  await expect(columns.locator('.board-review')).toContainText('Refactor invoice');
  await page.route('**/api/tasks/a3', route => route.fulfill({ json: {
    task: { id: 'a3', project_id: 'billing', title: 'Refactor invoice', status: 'review', provider: 'claude', reviewer: 'codex', attempt: 1, max_attempts: 3, review_attempt: 1, mode: 'live', complexity: 3,
      requested_provider: 'auto', error: null, created_at: '2026-10-31T09:00:00Z', updated_at: '2026-10-31T09:10:00Z', cancel_requested: 0, approved_at: null, approved_by: null,
      prompt: 'Extract the invoice total into a helper without changing behaviour.', scope_json: '["src/invoice"]', acceptance_json: '["all invoice tests pass"]', dependencies_json: '[]',
      base_rev: 'abc123', patch_hash: 'def456', worktree: 'W:/state/worktrees/billing/a3/attempt-1', branch: 'codex/center/billing/a3/1', checkpoint: 'W:/state/checkpoints/a3/1', run_dir: null, workspace: 'W:/billing',
      result: JSON.stringify({ summary: 'Extracted calcTotal()', status: 'completed', models_observed: ['claude-sonnet-5-5'], usage_observed: { total_tokens: 1234, input_tokens: 1000, output_tokens: 234 } }),
      config_json: JSON.stringify({ quality_gates: [['npm', 'run', 'lint'], ['npm', 'run', 'test']], prepare_commands: [['npm', 'ci']], read_set: ['src/invoice/total.ts'] }) },
    events: [
      { id: 1, event: 'queued', detail: '{}', created_at: '2026-10-31T09:00:00Z' },
      { id: 2, event: 'dispatch_recorded', detail: JSON.stringify({ role: 'implementation', provider: 'claude', model: 'claude-sonnet-5-5', effort: 'medium', skills: ['safe-refactoring'], adapter: 'live', task_kind: 'refactor', plan_reasons: ['complexity_3_implementation_refactor'], eligible_candidates: ['claude', 'codex'], candidate_notes: [] }), created_at: '2026-10-31T09:01:00Z' },
      { id: 3, event: 'dispatch_recorded', detail: JSON.stringify({ role: 'review', provider: 'codex', model: 'gpt-6-sol', effort: 'medium', skills: ['independent-code-review'], adapter: 'live', task_kind: 'refactor', plan_reasons: [], eligible_candidates: ['codex'], candidate_notes: ['codex_skipped_scope_99999_bytes'] }), created_at: '2026-10-31T09:08:00Z' },
    ],
    evidence: [
      { kind: 'gates', provider: null, simulated: 0, created_at: '2026-10-31T09:07:00Z', payload: JSON.stringify({ passed: true, outcomes: [{ argv: ['npm', 'run', 'lint'], code: 0, error: null }, { argv: ['npm', 'run', 'test'], code: 0, error: null }] }) },
      { kind: 'review', provider: 'codex', simulated: 0, created_at: '2026-10-31T09:10:00Z', payload: JSON.stringify({ verdict: 'approved', summary: 'Behaviour preserved; tests cover the helper.' }) },
    ],
    authorship: [{ provider: 'claude', attempt: 1, session_id: 'sess-1', created_at: '2026-10-31T09:02:00Z' }],
    sessions: [{ provider: 'codex', role: 'review', adapter: 'live', model: 'gpt-6-sol', started_at: '2026-10-31T09:09:00Z', lease_until: 1793500000, test_port: 32101 }],
  } }));
  await page.route('**/api/tasks/a3/live', route => route.fulfill({ json: { session: 'b'.repeat(32), session_age_seconds: 4, now: Date.now(), all_log_files: ['provider.log'],
    files: [{ name: 'provider.log', size: 321, age_seconds: 3, truncated: false, tail: '{"type":"thread.started"}' + String.fromCharCode(10) + '{"type":"item.completed","item":{"text":"Reading src/invoice/total.ts"}}' }] } }));
  await page.locator('#board-columns .board-card button').first().click();
  const live = page.locator('#live-panel');
  await expect(live).toBeVisible();
  await expect(live).toContainText('ตอนนี้กำลังทำอะไร');
  await expect(live).toContainText('ChatGPT (gpt-6-sol) กำลังตรวจ patch');
  await expect(live.locator('.step-current')).toHaveText('ตรวจ');
  await expect(live.locator('.step-done')).toHaveCount(6);
  await expect(live).toContainText('provider.log');
  await expect(live).toContainText('[item.completed] Reading src/invoice/total.ts');
  await expect(live.locator('#live-stamp')).toContainText('สด');
  const view = page.locator('#task-view');
  await expect(page.locator('#task-drawer')).toBeVisible();
  await expect(view).toContainText('Refactor invoice');
  await expect(view).toContainText('ผู้ตรวจกำลังตรวจ');
  await expect(view).toContainText('Extract the invoice total into a helper');
  await expect(view).toContainText('src/invoice');
  await expect(view).toContainText('all invoice tests pass');
  await expect(view).toContainText('npm run lint');
  await expect(view).toContainText('claude-sonnet-5-5');
  await expect(view).toContainText('safe-refactoring');
  await expect(view).toContainText('complexity_3_implementation_refactor');
  await expect(view).toContainText('codex_skipped_scope_99999_bytes');
  await expect(view).toContainText('ผ่าน');
  await expect(view).toContainText('Behaviour preserved; tests cover the helper.');
  await expect(view).toContainText('Extracted calcTotal()');
  await expect(view).toContainText('sess-1');
  await expect(view).toContainText('ไทม์ไลน์เหตุการณ์ทั้งหมด (3)');
  await expect(view).toContainText('codex/center/billing/a3/1');
  await expect(page.locator('#detail')).toContainText('"patch_hash": "def456"');
  await page.locator('#drawer-backdrop').click({ position: { x: 5, y: 5 } });
  await expect(page.locator('#task-drawer')).toBeHidden();
});
test('the open task view keeps updating by itself and follows the task through its phases', async ({ page }) => {
  const base = { id: 'c1', project_id: 'horoscope', title: 'Add cn tests', provider: 'codex', reviewer: null, attempt: 1, max_attempts: 3, review_attempt: 0, mode: 'live', complexity: 1, requested_provider: 'auto', error: null,
    created_at: '2026-10-31T09:00:00Z', cancel_requested: 0, prompt: 'p', scope_json: '["tests"]', acceptance_json: '[]', dependencies_json: '[]',
    config_json: JSON.stringify({ quality_gates: [['npm', 'run', 'lint'], ['npm', 'run', 'typecheck'], ['npm', 'run', 'test']], prepare_commands: [['npm', 'ci']] }) };
  let polls = 0;
  await page.route('**/api/status', async route => {
    const data = await (await route.fetch()).json();
    data.tasks = [{ id: 'c1', project_id: 'horoscope', title: 'Add cn tests', status: 'gates', provider: 'codex', reviewer: null, attempt: 1, mode: 'live', error: null, updated_at: new Date().toISOString(), waiting_reason: null, plan: {} }];
    await route.fulfill({ json: data });
  });
  await page.route('**/api/tasks/c1/live', route => route.fulfill({ json: { session: 'a'.repeat(32), session_age_seconds: 1, now: Date.now(),
    all_log_files: polls < 2 ? ['gate-0.log', 'gate-1.log'] : ['gate-0.log', 'gate-1.log', 'gate-2.log'],
    files: [{ name: polls < 2 ? 'gate-1.log' : 'gate-2.log', size: 40, age_seconds: 1, truncated: false, tail: polls < 2 ? 'typechecking src ...' : 'vitest running 12 tests ...' }] } }));
  await page.route('**/api/tasks/c1', route => {
    polls += 1;
    const status = polls < 4 ? 'gates' : 'ready_for_human_approval';
    route.fulfill({ json: { task: { ...base, status, updated_at: new Date().toISOString() }, events: [{ id: polls, event: 'queued', detail: '{}', created_at: '2026-10-31T09:00:00Z' }], evidence: [], authorship: [], sessions: [] } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'ดูรายละเอียด' }).first().click();
  const live = page.locator('#live-panel');
  await expect(live).toContainText('Center กำลังรัน gate ลำดับที่ 2 จาก 3: npm run typecheck (ไม่ใช้ AI)');
  await expect(live).toContainText('typechecking src');
  await expect(live.locator('.step-current')).toHaveText('รัน gates');
  await expect(live).toContainText('Center กำลังรัน gate ลำดับที่ 3 จาก 3: npm run test (ไม่ใช้ AI)', { timeout: 12000 });
  await expect(live).toContainText('vitest running 12 tests');
  await expect(live).toContainText('ครบทุกขั้นแล้ว รอคุณอนุมัติใน terminal ของ Center', { timeout: 12000 });
  await expect(live.locator('.step-current')).toHaveText('รออนุมัติ');
  await expect(live.locator('#live-stamp')).toContainText('ตรวจทุก 10 วินาที');
  await page.locator('#live-pause').check();
  const before = polls;
  await page.waitForTimeout(3500);
  expect(polls).toBe(before);
  await page.keyboard.press('Escape');
  const afterClose = polls;
  await page.waitForTimeout(3000);
  expect(polls).toBe(afterClose);
});
test('combined dashboard fits a mobile screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('เชื่อมต่อแล้ว');
  const overflowing = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflowing).toBe(false);
});
test('unreachable Center is visible and does not start a worker', async ({ page }) => {
  await page.route('**/api/status', route => route.fulfill({ status: 503, body: '{}' }));
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('ติดต่อ Center ไม่ได้');
  await expect(page.locator('#scheduler-state')).toContainText('ยังยืนยันสถานะไม่ได้');
});

test('scheduler health and waiting reasons stay truthful while tasks are filtered', async ({ page }) => {
  // Browser-only fixture: no scheduler, production state, or provider is started.
  await page.route('**/api/status', async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.service = { running: true, mode: 'live', heartbeat_age_seconds: 3, reason: 'running' };
    data.tasks[0].status = 'queued';
    data.tasks[0].waiting_reason = 'dependency_not_approved';
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  await expect(page.locator('#scheduler-state')).toHaveText('กำลังทำงาน');
  await expect(page.locator('#scheduler-mode')).toHaveText('โหมดใช้งานจริง');
  await expect(page.locator('#scheduler-age')).toContainText('3 วินาที');
  await expect(page.locator('#tasks')).toContainText('รออนุมัติงานก่อนหน้า');
  await page.getByLabel('กรองสถานะงาน', { exact: true }).selectOption('queued');
  await expect(page.locator('#tasks tr')).toHaveCount(1);
  await page.getByLabel('ค้นหางาน').fill('no_matching_task_123');
  await expect(page.locator('#tasks')).toContainText('ไม่พบงานตามเงื่อนไข');
  await page.getByLabel('ค้นหางาน').fill('');
  await page.getByLabel('กรองสถานะงาน', { exact: true }).selectOption('');
  await expect(page.locator('#tasks tr')).toHaveCount(2);
});

test('a stale scheduler heartbeat is visible even while the backend responds', async ({ page }) => {
  await page.route('**/api/status', async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.service = { running: false, mode: 'live', heartbeat_age_seconds: 45, reason: 'heartbeat_stale' };
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('เชื่อมต่อแล้ว');
  await expect(page.locator('#scheduler-state')).toContainText('หยุดอยู่');
  await expect(page.locator('#scheduler-note')).toContainText('ไม่ได้รับสัญญาณล่าสุด');
});
test('clear screen hides every task on this browser and can bring them back', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#tasks')).toContainText('sample-a');
  await page.getByRole('button', { name: '🧹 ล้างหน้าจอ' }).click();
  await expect(page.locator('#tasks')).not.toContainText('sample-a');
  await expect(page.locator('#approval-count')).toHaveText('0');
  await page.reload();
  await expect(page.locator('#tasks')).not.toContainText('sample-a');
  await page.getByRole('button', { name: /แสดงงานที่ซ่อน/ }).click();
  await expect(page.locator('#tasks')).toContainText('sample-a');
});
