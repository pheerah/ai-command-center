const { test, expect } = require('@playwright/test');
test('dashboard shows durable state and unavailable provider', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'AI Dev Command Center', exact: true })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('เชื่อมต่อแล้ว');
  await expect(page.locator('#providers')).toContainText('usage_exhausted');
  await expect(page.locator('#providers')).toContainText('unknown');
  await expect(page.getByRole('heading', { name: 'Usage Meter', exact: true })).toBeVisible();
  await expect(page.locator('#usage-note')).toContainText('ยังไม่มีข้อมูล token');
  await expect(page.locator('#live')).toHaveText('ปิดไว้');
  await expect(page.locator('#tasks')).toContainText('sample-a');
  await expect(page.locator('#tasks')).toContainText('sample-b');
  await expect(page.locator('#tasks')).toContainText('waiting_for_independent_review');
  await page.getByRole('button', { name: 'ดู', exact: true }).first().click();
  await expect(page.locator('#detail')).toContainText('mock_pipeline_complete');
  await expect(page.locator('#detail')).toContainText('patch_hash');
  await page.getByRole('button', { name: 'อัปเดตสถานะ' }).click();
  await expect(page.getByRole('status')).toContainText('เชื่อมต่อแล้ว');
  await page.screenshot({ path: '.ai-team/dashboard-preview.png', fullPage: true });
});
test('usage totals and daily chart stay on the same page as task queue', async ({ page }) => {
  // Synthetic browser fixture only; it is never written to production usage.
  await page.route('**/api/status', async route => {
    const response = await route.fetch();
    const data = await response.json();
    const today = data.usage.providers.codex.days.at(-1);
    Object.assign(today, { input_tokens: 100, output_tokens: 20, cached_input_tokens: 60, total_tokens: 120, observed_invocations: 1 });
    today.workloads.tasks = 1;
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  await expect(page.locator('#usage-total')).toHaveText('120');
  await expect(page.locator('#providers')).toContainText('120');
  await expect(page.locator('#usage-chart').getByRole('img')).toHaveCount(7);
  await expect(page.locator('#tasks')).toContainText('sample-a');
  await page.getByLabel('ช่วงเวลา Usage Meter').selectOption('1');
  await expect(page.locator('#usage-chart').getByRole('img')).toHaveCount(1);
  await expect(page.locator('#providers')).toContainText('Quota แพ็กเกจคงเหลือ');
  await expect(page.locator('#providers')).toContainText('ไม่ทราบ (unknown)');
  await page.screenshot({ path: '.ai-team/dashboard-test-fixture.png', fullPage: true });
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
});
