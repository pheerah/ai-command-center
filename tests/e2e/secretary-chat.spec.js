const { test, expect } = require('@playwright/test');
// File name sorts after dashboard.spec.js on purpose: these tests create tasks and chat history in the shared mock fixture.

async function openSecretary(page, project = 'sample-a') {
  await page.goto('/');
  await page.waitForFunction(() => window.OfficeGame);
  await page.waitForFunction(id => {
    window.OfficeGame.selectCharacter(id);
    const overlay = document.getElementById('agent-modal-overlay');
    return overlay && !overlay.hidden;
  }, `sec_${project}`);
  await expect(page.locator('#secretary-chat')).toBeVisible();
}

async function say(page, text) {
  await page.locator('#chat-input').fill(text);
  await page.locator('#chat-send').click();
}

async function sayForDraft(page, text) {
  const drafts = page.locator('#chat-log .chat-draft');
  const before = await drafts.count();
  await say(page, text);
  await expect(drafts).toHaveCount(before + 1);
  return drafts.last();
}

async function taskCount(page, title) {
  const status = await (await page.request.get('/api/status')).json();
  return (status.tasks || []).filter(task => task.title === title).length;
}

test('chat: a question gets a reply and no task is created', async ({ page }) => {
  const before = await taskCount(page, 'งานจำลองจากแชท');
  await openSecretary(page);
  await say(page, '? โปรเจกต์นี้ทำอะไร');
  await expect(page.locator('#chat-log')).toContainText('นี่คือคำตอบจำลอง');
  expect(await taskCount(page, 'งานจำลองจากแชท')).toBe(before);
});

test('chat: an ambiguous message shows the clarifying question', async ({ page }) => {
  await openSecretary(page);
  await say(page, '~ แก้ให้หน่อย');
  await expect(page.locator('#chat-log')).toContainText('ต้องการให้แก้ที่ส่วนไหน');
  await expect(page.locator('#chat-log .chat-draft')).toHaveCount(0);
});

test('chat: an instruction shows an editable draft and nothing is created until "ส่งงาน"', async ({ page }) => {
  await openSecretary(page);
  const before = await taskCount(page, 'ชื่อที่แก้เอง');
  const draft = await sayForDraft(page, 'เพิ่มปุ่มรีเฟรช');
  await expect(draft).toBeVisible();
  await expect(draft.locator('[name=title]')).toHaveValue('งานจำลองจากแชท');
  await expect(draft).toContainText('provider: auto');
  expect(await taskCount(page, 'ชื่อที่แก้เอง')).toBe(before);
  await draft.locator('[name=title]').fill('ชื่อที่แก้เอง');
  await draft.getByRole('button', { name: 'ส่งงาน' }).click();
  await expect(draft).toContainText('ส่งงานแล้ว');
  await expect(draft.getByRole('button', { name: 'ส่งงาน' })).toHaveCount(0);
  expect(await taskCount(page, 'ชื่อที่แก้เอง')).toBe(before + 1);
});

test('chat: double clicking "ส่งงาน" creates one task', async ({ page }) => {
  await openSecretary(page);
  const before = await taskCount(page, 'งานคลิกสองครั้ง');
  const draft = await sayForDraft(page, 'งานที่จะกดซ้ำ');
  await draft.locator('[name=title]').fill('งานคลิกสองครั้ง');
  // A real double click lands before the first answer re-renders the card, so fire both clicks in the same tick.
  await draft.getByRole('button', { name: 'ส่งงาน' }).evaluate(button => { button.click(); button.click(); });
  await expect(draft).toContainText('ส่งงานแล้ว');
  expect(await taskCount(page, 'งานคลิกสองครั้ง')).toBe(before + 1);
});

test('chat: history survives a reload and a confirmed draft stays confirmed', async ({ page }) => {
  await openSecretary(page);
  await say(page, '? ข้อความที่ต้องจำ');
  await expect(page.locator('#chat-log')).toContainText('นี่คือคำตอบจำลอง');
  await page.reload();
  await openSecretary(page);
  await expect(page.locator('#chat-log')).toContainText('ข้อความที่ต้องจำ');
  await expect(page.locator('#chat-log')).toContainText('นี่คือคำตอบจำลอง');
  await expect(page.locator('#chat-log .chat-draft', { hasText: 'ส่งงานแล้ว' }).first()).toBeVisible();
});

test('chat: history is per project', async ({ page }) => {
  await openSecretary(page, 'sample-b');
  await say(page, '? เฉพาะโปรเจกต์บี');
  await expect(page.locator('#chat-log')).toContainText('เฉพาะโปรเจกต์บี');
  await page.keyboard.press('Escape');
  await page.evaluate(() => window.OfficeGame.selectCharacter('sec_sample-a'));
  await expect(page.locator('#chat-log')).not.toContainText('เฉพาะโปรเจกต์บี');
});

test('chat: model text with markup is shown as text and never runs', async ({ page }) => {
  let dialogs = 0;
  page.on('dialog', async dialog => { dialogs += 1; await dialog.dismiss(); });
  await openSecretary(page);
  await say(page, '!ทดสอบมาร์กอัป');
  await expect(page.locator('#chat-log')).toContainText('<script>alert(1)</script>');
  await expect(page.locator('#chat-log img')).toHaveCount(0);
  await expect(page.locator('#chat-log script')).toHaveCount(0);
  await page.waitForTimeout(300);
  expect(dialogs).toBe(0);
});

test('chat: fits a 390px wide screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await openSecretary(page);
  await say(page, '? ทดสอบจอเล็ก');
  await expect(page.locator('#chat-log')).toContainText('นี่คือคำตอบจำลอง');
  const fits = await page.evaluate(() => {
    const form = document.getElementById('chat-form').getBoundingClientRect();
    return document.documentElement.scrollWidth <= window.innerWidth && form.right <= window.innerWidth && form.left >= 0;
  });
  expect(fits).toBe(true);
  // Nothing else in the modal may sit on top of the chat once it is scrolled into view.
  await page.locator('#chat-form').scrollIntoViewIfNeeded();
  const covered = await page.evaluate(() => {
    const box = document.getElementById('chat-form').getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return !hit || !document.getElementById('secretary-chat').contains(hit);
  });
  expect(covered).toBe(false);
  const titleCovered = await page.evaluate(() => {
    const title = document.querySelector('#secretary-chat h4');
    title.scrollIntoView({ block: 'center' });
    const box = title.getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + 20, box.top + box.height / 2);
    return !hit || !document.getElementById('secretary-chat').contains(hit);
  });
  expect(titleCovered).toBe(false);
});

test('chat: a server error shows a Thai message and keeps the page usable', async ({ page }) => {
  await page.route('**/api/chat', route => route.fulfill({ status: 500, json: { error: 'Center unavailable' } }));
  await openSecretary(page);
  await say(page, '? ลองส่ง');
  await expect(page.locator('#chat-log > .chat-error')).toContainText('ส่งข้อความไม่สำเร็จ');
  await expect(page.locator('#chat-input')).toBeEnabled();
});

test('chat: the old direct command box is gone from the secretary window', async ({ page }) => {
  await openSecretary(page);
  await expect(page.locator('#modal-command-input')).toHaveCount(0);
});
