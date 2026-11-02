const { test, expect } = require('@playwright/test');
// The shared mock Center has no task waiting for approval, so the task report and the review view are served from fixtures here.
test.beforeEach(async ({ page }) => { await page.addInitScript(() => localStorage.setItem('center-view-mode', 'board')); });

const REVIEW = {
  task: { id: 'abcdef012345', project_id: 'sample-a', title: 'Add b', status: 'ready_for_human_approval', provider: 'codex', attempt: 1 },
  changes: {
    available: true, patch_hash_short: 'abc123def456', truncated: false,
    files: [{ path: 'src/a.py', status: 'changed', added: 2, removed: 1 }, { path: 'src/new.py', status: 'added', added: null, removed: null }],
    diff: 'diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1,2 @@\n-old\n+new\n+<img src=x onerror=alert(1)>\n',
    untracked: [{ path: 'src/new.py', size: 12, preview: 'print("hi")\n' }],
  },
  gates: [{ command: 'python -m pytest', passed: true }, { command: 'node lint', passed: false }],
  review: { verdict: 'approved', summary: 'Looks fine <script>alert(1)</script>', provider: 'claude', simulated: false },
  human_review: null, applied: false, rework_requests: [], rejected_reason: null,
  actions: { approve: true, reject: true, rework: true, apply: false }, suggested_commit_message: null,
  diagnosis: { task_id: 'abcdef012345', reason_code: null, explanation: null, actions: [] },
};

async function openPanel(page, view = REVIEW, seen = {}) {
  let dialogs = 0;
  page.on('dialog', async dialog => { dialogs += 1; await dialog.dismiss(); });
  seen.dialogs = () => dialogs;
  await page.route('**/api/quota', route => route.fulfill({ json: { updated: 'fixture', codex: null, claude: null, google: null } }));
  await page.route('**/api/tasks/abcdef012345', route => route.fulfill({ json: {
    task: { ...view.task, config_json: '{}', created_at: '2026-11-02T00:00:00+00:00', updated_at: '2026-11-02T00:00:00+00:00' }, events: [], evidence: [], sessions: [], authorship: [] } }));
  await page.route('**/api/tasks/abcdef012345/live', route => route.fulfill({ json: { session: null, files: [], now: Date.now() } }));
  await page.route('**/api/review?**', route => route.fulfill({ json: view }));
  await page.route('**/api/review/*', route => { seen.last = { url: route.request().url(), body: route.request().postDataJSON() }; route.fulfill({ json: { task: { status: 'rejected' } } }); });
  await page.goto('/');
  await page.evaluate(() => window.details('abcdef012345'));
  await expect(page.locator('#task-review .rv-panel')).toBeVisible();
}

test('review: shows files, a coloured diff, gates and the reviewer verdict', async ({ page }) => {
  await openPanel(page);
  const panel = page.locator('#task-review');
  await expect(panel).toContainText('src/a.py');
  await expect(panel).toContainText('+2 −1');
  await expect(panel.locator('.rv-add').first()).toContainText('+new');
  await expect(panel.locator('.rv-del').first()).toContainText('-old');
  await expect(panel.locator('.rv-pass').first()).toContainText('python -m pytest');
  await expect(panel.locator('.rv-fail').first()).toContainText('node lint');
  await expect(panel).toContainText('อนุมัติ · claude');
  await expect(panel.getByRole('button', { name: /อนุมัติและนำโค้ดเข้าโปรเจกต์/ })).toBeVisible();
});

test('review: markup in a diff or a reviewer summary is shown as text and never runs', async ({ page }) => {
  const seen = {};
  await openPanel(page, REVIEW, seen);
  await expect(page.locator('#task-review')).toContainText('<img src=x onerror=alert(1)>');
  await expect(page.locator('#task-review')).toContainText('<script>alert(1)</script>');
  await expect(page.locator('#task-review img')).toHaveCount(0);
  await expect(page.locator('#task-review script')).toHaveCount(0);
  await page.waitForTimeout(300);
  expect(seen.dialogs()).toBe(0);
});

test('review: rejecting needs a reason and sends it with the project and task ids', async ({ page }) => {
  const seen = {};
  await openPanel(page, REVIEW, seen);
  const panel = page.locator('#task-review');
  await panel.getByRole('button', { name: 'ปฏิเสธ', exact: true }).click();
  await panel.getByRole('button', { name: 'ยืนยันปฏิเสธ' }).click();
  expect(seen.last).toBeUndefined();  // an empty reason sends nothing
  await panel.getByLabel('เหตุผลที่ปฏิเสธ (ต้องกรอก)').fill('ไม่ตรงกับที่ขอ');
  await panel.getByRole('button', { name: 'ยืนยันปฏิเสธ' }).click();
  await expect.poll(() => seen.last && seen.last.body).toEqual({ project_id: 'sample-a', task_id: 'abcdef012345', reason: 'ไม่ตรงกับที่ขอ' });
  expect(seen.last.url).toContain('/api/review/reject');
});

test('review: sending a task back needs instructions and the button is off when no attempts are left', async ({ page }) => {
  const seen = {};
  await openPanel(page, { ...REVIEW, actions: { ...REVIEW.actions, rework: false } }, seen);
  await expect(page.locator('#task-review').getByRole('button', { name: 'สั่งแก้ในงานเดิม' })).toBeDisabled();
});

test('review: a stuck task explains why in Thai and offers only the actions that can work', async ({ page }) => {
  const stuck = {
    ...REVIEW, task: { ...REVIEW.task, status: 'failed' }, changes: { available: false, reason: 'not_ready' }, gates: [], review: null,
    actions: { approve: false, reject: false, rework: false, apply: false },
    diagnosis: { task_id: 'abcdef012345', reason_code: 'usage_exhausted', explanation: 'โควตาของ AI ค่ายนี้หมด', actions: [
      { action: 'switch_provider', enabled: true, providers: ['claude'] }, { action: 'retry', enabled: false }] },
  };
  const seen = {};
  await openPanel(page, stuck, seen);
  const panel = page.locator('#task-review');
  await expect(panel).toContainText('โควตาของ AI ค่ายนี้หมด');
  await expect(panel.getByRole('button', { name: 'ลองใหม่' })).toBeDisabled();
  await panel.getByRole('button', { name: /ให้ค่ายอื่นรับ: claude/ }).click();
  await expect.poll(() => seen.last && seen.last.body).toEqual({ project_id: 'sample-a', task_id: 'abcdef012345', provider: 'claude' });
});

test('review: an approved task that was not applied says so, offers apply and a commit message to copy, and has no commit button', async ({ page }) => {
  const approved = {
    ...REVIEW, task: { ...REVIEW.task, status: 'approved' }, applied: false, suggested_commit_message: 'Add b',
    actions: { approve: false, reject: false, rework: false, apply: true },
  };
  const seen = {};
  await openPanel(page, approved, seen);
  const panel = page.locator('#task-review');
  await expect(panel).toContainText('ยังไม่ได้นำไปใช้ในโปรเจกต์');
  await expect(panel.locator('.rv-commit')).toHaveText('Add b');
  await expect(panel.getByRole('button', { name: /commit/i })).toHaveCount(0);
  await panel.getByRole('button', { name: /นำไปใช้ในโปรเจกต์ \(apply\)/ }).click();
  await expect.poll(() => seen.last && seen.last.url).toContain('/api/review/apply');
});

test('review: the panel fits a 390px wide screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openPanel(page);
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits).toBe(true);
});
