// Review panel: what changed, did it pass, and the owner's decisions (approve, reject, send back, retry, apply) for one task.
// All text from the Center, the model and the owner is inserted with textContent; nothing is ever parsed as markup.
(() => {
  'use strict';

  const T = {
    title: 'ตรวจผลงานก่อนตัดสินใจ',
    loading: 'กำลังโหลดผลงาน…',
    failedLoad: 'โหลดผลงานไม่สำเร็จ',
    changes: 'การเปลี่ยนแปลง',
    noDiff: { not_ready: 'ยังไม่มีผลงานให้ดู (งานยังไม่ถึงขั้นรออนุมัติ)', checkpoint_missing: 'ไม่พบไฟล์ผลงานที่บันทึกไว้', checkpoint_mismatch: 'ผลงานที่บันทึกไว้ไม่ตรงกับที่ตรวจ จึงไม่แสดงเพื่อความปลอดภัย' },
    truncated: 'diff ยาวเกินจึงแสดงเฉพาะส่วนแรก',
    newFiles: 'ไฟล์ใหม่',
    checks: 'ผลตรวจ',
    gates: 'ตรวจอัตโนมัติ (gates)',
    noGates: 'ยังไม่มีผล gates',
    review: 'ผู้ตรวจจากอีกค่าย',
    noReview: 'ยังไม่มีผลรีวิว',
    approved: 'อนุมัติ', rejected: 'ปฏิเสธ',
    why: 'เกิดอะไรขึ้น',
    decide: 'ตัดสินใจ',
    approve: '✓ อนุมัติและนำโค้ดเข้าโปรเจกต์',
    reject: 'ปฏิเสธ', rejectWhy: 'เหตุผลที่ปฏิเสธ (ต้องกรอก)', rejectConfirm: 'ยืนยันปฏิเสธ',
    rework: 'สั่งแก้ในงานเดิม', reworkWhat: 'บอกว่าต้องแก้อะไร (ต้องกรอก)', reworkConfirm: 'ส่งกลับให้แก้',
    retry: 'ลองใหม่', switchTo: 'ให้ค่ายอื่นรับ:',
    apply: 'นำไปใช้ในโปรเจกต์ (apply)', applied: 'นำไปใช้ในโปรเจกต์แล้ว',
    notApplied: 'อนุมัติแล้ว แต่ยังไม่ได้นำไปใช้ในโปรเจกต์ (อาจเพราะโปรเจกต์เปลี่ยนไปหลังตรวจ)',
    commit: 'ข้อความ commit ที่แนะนำ (Center ไม่ commit ให้ คัดลอกไปใช้เอง)',
    rejectedBy: 'คุณปฏิเสธงานนี้แล้ว', reworked: 'คำสั่งแก้ที่ส่งไปก่อนหน้านี้',
    failed: 'ทำไม่สำเร็จ',
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function request(path, options) {
    const response = await fetch(path, options);
    let data = {};
    try { data = await response.json(); } catch { /* an error page is not JSON */ }
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  const post = (path, body) => request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  function section(title) {
    const box = el('section', 'rv-section');
    box.append(el('h4', 'rv-title', title));
    return box;
  }

  function diffView(diff) {
    const pre = el('pre', 'rv-diff');
    for (const line of diff.split('\n')) {
      let kind = 'ctx';
      if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff --git') || line.startsWith('index ')) kind = 'meta';
      else if (line.startsWith('@@')) kind = 'hunk';
      else if (line.startsWith('+')) kind = 'add';
      else if (line.startsWith('-')) kind = 'del';
      pre.append(el('span', `rv-line rv-${kind}`, line + '\n'));
    }
    return pre;
  }

  function renderChanges(view) {
    const box = section(T.changes);
    const changes = view.changes;
    if (!changes.available) {
      box.append(el('p', 'rv-muted', T.noDiff[changes.reason] || T.noDiff.not_ready));
      return box;
    }
    const list = el('ul', 'rv-files');
    for (const file of changes.files) {
      const counts = file.added === null ? T.newFiles : `+${file.added} −${file.removed}`;
      list.append(el('li', '', `${file.path}  (${counts})`));
    }
    box.append(list);
    if (changes.diff) box.append(diffView(changes.diff));
    if (changes.truncated) box.append(el('p', 'rv-muted', T.truncated));
    for (const item of changes.untracked) {
      const details = el('details', 'rv-new');
      details.append(el('summary', '', `${T.newFiles}: ${item.path}`), el('pre', 'rv-diff', item.preview));
      box.append(details);
    }
    return box;
  }

  function renderChecks(view) {
    const box = section(T.checks);
    const gates = el('div', 'rv-block');
    gates.append(el('strong', '', T.gates));
    if (!view.gates.length) gates.append(el('p', 'rv-muted', T.noGates));
    for (const gate of view.gates) gates.append(el('div', gate.passed ? 'rv-pass' : 'rv-fail', `${gate.passed ? '✓' : '✗'} ${gate.command}`));
    box.append(gates);
    const review = el('div', 'rv-block');
    review.append(el('strong', '', T.review));
    if (!view.review) {
      review.append(el('p', 'rv-muted', T.noReview));
    } else {
      const verdict = view.review.verdict === 'approved' ? T.approved : T.rejected;
      review.append(el('div', view.review.verdict === 'approved' ? 'rv-pass' : 'rv-fail', `${verdict}${view.review.provider ? ` · ${view.review.provider}` : ''}`));
      if (view.review.summary) review.append(el('p', 'rv-summary', view.review.summary));
    }
    box.append(review);
    return box;
  }

  function renderDiagnosis(view, ctx) {
    const diagnosis = view.diagnosis;
    if (!diagnosis || !diagnosis.reason_code) return null;
    const box = section(T.why);
    box.append(el('p', 'rv-summary', diagnosis.explanation));
    const bar = el('div', 'rv-actions');
    for (const action of diagnosis.actions) {
      if (action.action === 'retry') {
        bar.append(button(T.retry, !action.enabled, () => ctx.run('/api/review/retry', {})));
      } else if (action.action === 'switch_provider') {
        for (const provider of action.providers || []) {
          bar.append(button(`${T.switchTo} ${provider}`, !action.enabled, () => ctx.run('/api/review/switch', { provider })));
        }
      }
    }
    if (bar.children.length) box.append(bar);
    return box;
  }

  function button(label, disabled, onClick, className = 'rv-btn') {
    const node = el('button', className, label);
    node.type = 'button';
    node.disabled = disabled;
    node.addEventListener('click', onClick);
    return node;
  }

  function reasonForm(label, confirmLabel, field, ctx, path) {
    const form = el('div', 'rv-form');
    form.hidden = true;
    const text = el('textarea', 'rv-text');
    text.rows = 3;
    text.maxLength = field === 'reason' ? 1000 : 2000;
    text.placeholder = label;
    text.setAttribute('aria-label', label);
    const confirm = button(confirmLabel, false, () => {
      if (!text.value.trim()) { text.focus(); return; }
      ctx.run(path, { [field]: text.value.trim() });
    });
    form.append(text, confirm);
    return form;
  }

  function renderDecisions(view, ctx) {
    const box = section(T.decide);
    const actions = view.actions;
    if (view.rejected_reason) box.append(el('p', 'rv-fail', `${T.rejectedBy}: ${view.rejected_reason}`));
    if (view.rework_requests.length) box.append(el('p', 'rv-muted', `${T.reworked}: ${view.rework_requests.join(' / ')}`));
    const bar = el('div', 'rv-actions');
    const rejectForm = reasonForm(T.rejectWhy, T.rejectConfirm, 'reason', ctx, '/api/review/reject');
    const reworkForm = reasonForm(T.reworkWhat, T.reworkConfirm, 'instructions', ctx, '/api/review/rework');
    if (actions.approve) {
      bar.append(button(T.approve, false, () => ctx.approve(), 'rv-btn rv-approve'));
      bar.append(button(T.reject, false, () => { rejectForm.hidden = !rejectForm.hidden; reworkForm.hidden = true; }, 'rv-btn rv-danger'));
    }
    if (actions.approve) bar.append(button(T.rework, !actions.rework, () => { reworkForm.hidden = !reworkForm.hidden; rejectForm.hidden = true; }));
    if (view.task.status === 'approved') {
      if (view.applied) {
        bar.append(el('span', 'rv-pass', T.applied));
      } else {
        box.append(el('p', 'rv-fail', T.notApplied));
        bar.append(button(T.apply, !actions.apply, () => ctx.run('/api/review/apply', {}), 'rv-btn rv-approve'));
      }
    }
    box.append(bar, rejectForm, reworkForm);
    if (view.suggested_commit_message) {
      const commit = el('div', 'rv-block');
      commit.append(el('strong', '', T.commit));
      commit.append(el('code', 'rv-commit', view.suggested_commit_message));
      box.append(commit);
    }
    return box;
  }

  function mount(container, task, hooks = {}) {
    container.replaceChildren(el('p', 'rv-muted', T.loading));
    let alive = true;
    const ctx = {
      approve: () => hooks.approve && hooks.approve(task.id),
      async run(path, extra) {
        const problem = container.querySelector('.rv-problem') || el('p', 'rv-fail rv-problem');
        problem.textContent = '';
        try {
          await post(path, { project_id: task.project_id, task_id: task.id, ...extra });
          if (hooks.changed) await hooks.changed();
          if (alive) load();
        } catch (error) {
          problem.textContent = `${T.failed}: ${error.message}`;
          container.append(problem);
        }
      },
    };

    async function load() {
      try {
        const view = await request(`/api/review?project_id=${encodeURIComponent(task.project_id)}&task_id=${encodeURIComponent(task.id)}`);
        if (!alive) return;
        const wrap = el('div', 'rv-panel');
        wrap.append(el('h3', 'rv-head', T.title));
        const diagnosis = renderDiagnosis(view, ctx);
        if (diagnosis) wrap.append(diagnosis);
        wrap.append(renderChecks(view), renderChanges(view), renderDecisions(view, ctx));
        container.replaceChildren(wrap);
      } catch (error) {
        if (alive) container.replaceChildren(el('p', 'rv-fail', `${T.failedLoad}: ${error.message}`));
      }
    }

    load();
    return { destroy() { alive = false; } };
  }

  window.ReviewPanel = { mount };
})();
