// Secretary chat panel: history, composer, and draft-task cards.
// Everything the model or the user wrote is inserted with textContent only; the browser never interprets it as markup.
(() => {
  'use strict';

  const TEXT = {
    thinking: 'เลขาฯ กำลังคิด…',
    sendFailed: 'ส่งข้อความไม่สำเร็จ',
    confirmFailed: 'ส่งงานไม่สำเร็จ',
    historyFailed: 'โหลดประวัติการคุยไม่สำเร็จ',
    sources: 'ไฟล์ที่อ้างอิง',
    confirm: 'ส่งงาน',
    confirmed: 'ส่งงานแล้ว',
    draftHint: 'ร่างงาน (แก้ได้ก่อนกดส่ง ยังไม่ได้สร้างงานจริง)',
    related: 'งานที่เกี่ยวข้อง',
    labels: { title: 'ชื่องาน', prompt: 'รายละเอียด', scope: 'ขอบเขตไฟล์ (บรรทัดละหนึ่งรายการ)', accept: 'เกณฑ์ที่ต้องผ่าน (บรรทัดละหนึ่งข้อ)', complexity: 'ความยาก (1-5)' },
  };

  let current = null;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function newTurnId() {
    const random = (window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/[^A-Za-z0-9]/g, '');
    return ('turn-' + random).slice(0, 40);
  }

  async function post(path, body) {
    const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    let data = {};
    try { data = await response.json(); } catch { /* an error page is not JSON */ }
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function parse(row) {
    try { return JSON.parse(row.body); } catch { return {}; }
  }

  function lines(value) {
    return value.split('\n').map(line => line.trim()).filter(Boolean);
  }

  function field(card, name, labelText, control) {
    const label = el('label', 'chat-field');
    label.append(el('span', 'chat-field-label', labelText));
    control.name = name;
    label.append(control);
    card.append(label);
    return control;
  }

  function renderDraft(box, row, draft, ctx) {
    const card = el('div', 'chat-draft');
    card.append(el('div', 'chat-draft-hint', TEXT.draftHint));
    // What the draft will also use when confirmed, even though it is not editable here.
    const meta = [`provider: ${draft.provider || 'auto'}`];
    if (draft.related_task_id) meta.push(`${TEXT.related}: ${draft.related_task_id}`);
    card.append(el('div', 'chat-draft-meta', meta.join(' · ')));
    const title = field(card, 'title', TEXT.labels.title, el('input'));
    title.type = 'text';
    title.value = draft.title || '';
    const prompt = field(card, 'prompt', TEXT.labels.prompt, el('textarea'));
    prompt.rows = 4;
    prompt.value = draft.prompt || '';
    const scope = field(card, 'scope', TEXT.labels.scope, el('textarea'));
    scope.rows = 2;
    scope.value = (draft.scope || []).join('\n');
    const accept = field(card, 'accept', TEXT.labels.accept, el('textarea'));
    accept.rows = 2;
    accept.value = (draft.accept || []).join('\n');
    const complexity = field(card, 'complexity', TEXT.labels.complexity, el('select'));
    for (let level = 1; level <= 5; level += 1) complexity.append(new Option(String(level), String(level)));
    complexity.value = String(draft.complexity || 1);
    const footer = el('div', 'chat-draft-footer');
    card.append(footer);
    box.append(card);

    if (row.task_id) {
      for (const control of [title, prompt, scope, accept, complexity]) control.disabled = true;
      footer.append(el('span', 'chat-draft-done', `${TEXT.confirmed} · ${row.task_id}`));
      return;
    }
    const button = el('button', 'chat-confirm', TEXT.confirm);
    button.type = 'button';
    const problem = el('div', 'chat-error');
    problem.hidden = true;
    footer.append(button, problem);
    let busy = false;
    button.addEventListener('click', async () => {
      if (busy) return;
      busy = true;
      button.disabled = true;
      problem.hidden = true;
      const edits = {};
      if (title.value !== draft.title) edits.title = title.value;
      if (prompt.value !== draft.prompt) edits.prompt = prompt.value;
      if (scope.value !== (draft.scope || []).join('\n')) edits.scope = lines(scope.value);
      if (accept.value !== (draft.accept || []).join('\n')) edits.accept = lines(accept.value);
      if (Number(complexity.value) !== draft.complexity) edits.complexity = Number(complexity.value);
      try {
        const body = { project_id: ctx.projectId, message_id: row.id };
        if (Object.keys(edits).length) body.edits = edits;
        const data = await post('/api/chat/confirm', body);
        if (!ctx.active()) return;
        row.task_id = data.task && data.task.id ? data.task.id : 'ok';
        footer.replaceChildren(el('span', 'chat-draft-done', `${TEXT.confirmed} · ${row.task_id}`));
        for (const control of [title, prompt, scope, accept, complexity]) control.disabled = true;
        if (typeof window.refresh === 'function') window.refresh();
      } catch (error) {
        if (!ctx.active()) return;
        problem.textContent = `${TEXT.confirmFailed}: ${error.message}`;
        problem.hidden = false;
        busy = false;
        button.disabled = false;
      }
    });
  }

  function renderRow(box, row, ctx) {
    if (row.role === 'user') {
      box.append(el('div', 'chat-msg chat-user', row.body));
      return;
    }
    const wrap = el('div', 'chat-msg chat-secretary');
    const value = row.kind === 'error' ? {} : parse(row);
    if (row.kind === 'reply') {
      wrap.append(el('div', 'chat-text', value.text || ''));
      if (Array.isArray(value.files) && value.files.length) wrap.append(el('div', 'chat-sources', `${TEXT.sources}: ${value.files.join(', ')}`));
    } else if (row.kind === 'clarify') {
      const list = el('ul', 'chat-questions');
      for (const question of value.questions || []) list.append(el('li', '', question));
      wrap.append(list);
    } else if (row.kind === 'draft_task') {
      renderDraft(wrap, row, value, ctx);
    } else {
      wrap.classList.add('chat-error');
      wrap.textContent = row.body;
    }
    box.append(wrap);
  }

  function mount(container, projectId) {
    if (current) current.destroy();
    const log = container.querySelector('#chat-log');
    const form = container.querySelector('#chat-form');
    const input = container.querySelector('#chat-input');
    const send = container.querySelector('#chat-send');
    let alive = true;
    let pending = false;
    const ctx = { projectId, active: () => alive };
    log.replaceChildren();

    const scrollDown = () => { log.scrollTop = log.scrollHeight; };
    const fail = (message) => {
      log.append(el('div', 'chat-msg chat-error', message));
      scrollDown();
    };

    (async () => {
      try {
        const response = await fetch(`/api/chat/history?project_id=${encodeURIComponent(projectId)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        if (!alive) return;
        for (const row of data.messages || []) renderRow(log, row, ctx);
        scrollDown();
      } catch (error) {
        if (alive) fail(`${TEXT.historyFailed}: ${error.message}`);
      }
    })();

    form.onsubmit = async (event) => {
      event.preventDefault();
      const message = input.value.trim();
      if (!message || pending) return;
      pending = true;
      input.disabled = true;
      send.disabled = true;
      input.value = '';
      log.append(el('div', 'chat-msg chat-user', message));
      const thinking = el('div', 'chat-msg chat-thinking', TEXT.thinking);
      thinking.setAttribute('role', 'status');
      log.append(thinking);
      scrollDown();
      try {
        const row = await post('/api/chat', { project_id: projectId, message, client_turn_id: newTurnId() });
        if (!alive) return;
        thinking.remove();
        renderRow(log, row, ctx);
      } catch (error) {
        if (!alive) return;
        thinking.remove();
        fail(`${TEXT.sendFailed}: ${error.message}`);
      } finally {
        if (alive) {
          pending = false;
          input.disabled = false;
          send.disabled = false;
          scrollDown();
          input.focus();
        }
      }
    };

    current = { destroy() { alive = false; form.onsubmit = null; if (current && current.destroy === this.destroy) current = null; } };
    return current;
  }

  window.SecretaryChat = { mount };
})();
