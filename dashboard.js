const el = id => document.getElementById(id);
const format = value => new Intl.NumberFormat('th-TH').format(value);
const number = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
const names = { codex: 'ChatGPT', claude: 'Claude', google: 'Google' };
const colors = { codex: '#6bc6aa', claude: '#dba07b', google: '#8baeff' };
let snapshot = null;
let refreshing = false;
const waitingLabels = {
  held_for_ide_handoff: 'รอ session ใน IDE รับงาน (hold-for-ide)',
  provider_quota_floor: 'รอ: quota ของ AI ที่ใช้ได้ต่ำกว่าเกณฑ์ที่ตั้งไว้ (ดูแท็บ Usage Meter)',
  ready: 'พร้อมรับงาน', dependency_not_approved: 'รออนุมัติงานก่อนหน้า', dependencies_pending: 'รอผลจากงานก่อนหน้า',
  dependency_pending: 'รอผลจากงานก่อนหน้า', dependency_unapproved: 'รออนุมัติงานก่อนหน้า',
  global_capacity: 'รอช่องทำงานว่าง', global_capacity_occupied: 'รอช่องทำงานว่าง', provider_capacity: 'รอช่องทำงานของ AI ว่าง',
  provider_unavailable: 'AI ที่กำหนดยังไม่พร้อม', provider_cooldown: 'พักการเรียก AI ชั่วคราว', no_eligible_provider: 'ยังไม่มี AI ที่รับงานนี้ได้',
  no_independent_reviewer: 'รอผู้ตรวจจากอีกค่าย', requested_provider_unavailable: 'AI ที่ระบุยังไม่พร้อม',
  awaiting_handoff: 'รอรับงานใน IDE', human_review_required: 'รอผู้ใช้ตรวจโค้ด', retry_backoff: 'รอเวลาลองใหม่',
  retry_wait: 'รอเวลาลองใหม่', attempt_limit: 'ครบจำนวนครั้งที่อนุญาต', cancelled: 'ยกเลิกแล้ว',
  session_active: 'มีผู้รับงานอยู่แล้ว', live_execution_disabled: 'ยังไม่ได้เปิดให้ AI ทำงาน',
  task_not_dispatchable: 'ยังไม่ถึงขั้นรับงาน', adapter_mode_mismatch: 'ช่องทางรับงานไม่ตรงกับโหมดงาน',
  active_assignment: 'มีผู้รับงานอยู่แล้ว', project_capacity: 'รอช่องทำงานของโปรเจกต์ว่าง',
  awaiting_independent_or_human_review: 'รอผู้ตรวจจากอีกค่ายหรือผู้ใช้ตรวจโค้ด',
  provider_unavailable_or_handoff_required: 'AI ยังไม่พร้อม หรือรอรับงานใน IDE',
  eligible_by_capacity_capability_health_quality_and_observed_usage: 'พร้อมรับงาน',
};

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function stats(provider) {
  const days = Number(el('usage-window').value);
  const rows = snapshot?.usage?.providers?.[provider]?.days?.slice(-days) || [];
  const total = { input_tokens: 0, output_tokens: 0, cached_input_tokens: 0, cache_write_tokens: 0, total_tokens: 0, observed_invocations: 0, unmeasured_invocations: 0, workloads: { tasks: 0, audits: 0, live_smoke: 0 } };
  for (const row of rows) {
    for (const key of Object.keys(total)) if (key !== 'workloads') total[key] += number(row[key]);
    for (const key of Object.keys(total.workloads)) total.workloads[key] += number(row.workloads?.[key]);
  }
  return { rows, ...total };
}

let quotaData = null;

function quotaMeter(label, win) {
  const row = node('div', 'quota-meter');
  const head = node('div', 'quota-line');
  head.append(node('span', '', label + ' · เหลือ'), node('strong', '', win ? (win.at_least ? '≥ ' : '') + win.remaining_percent + '%' : 'ไม่ทราบ'));
  const track = node('div', 'quota-track');
  const fill = node('div', 'quota-fill' + (win && win.remaining_percent < 15 ? ' low' : win && win.remaining_percent < 40 ? ' mid' : ''));
  fill.style.width = (win ? win.remaining_percent : 0) + '%';
  track.append(fill);
  row.append(head, track);
  if (win?.resets_at) row.append(node('div', 'provider-note', 'รีเซ็ต ' + new Date(win.resets_at).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok', dateStyle: 'short', timeStyle: 'short' })));
  return row;
}

async function refreshQuota() {
  try {
    const response = await fetch('/api/quota');
    if (!response.ok) return;
    quotaData = await response.json();
    renderUsage();
  } catch { /* keep last values */ }
}

function renderUsage() {
  if (!snapshot) return;
  el('providers').replaceChildren();
  const data = {};
  for (const [name, provider] of Object.entries(snapshot.providers)) {
    const usage = stats(name);
    data[name] = usage;
    const card = node('article', 'provider-card');
    card.style.setProperty('--accent', colors[name] || '#96a7be');
    const heading = node('div', 'provider-heading');
    heading.append(node('h3', 'provider-brand', names[name] || name), node('span', 'badge ' + provider.availability, provider.availability === 'available' ? 'พร้อมทำงาน' : provider.availability === 'unavailable' ? 'ยังไม่พร้อม' : 'ยังไม่ยืนยัน'));
    card.append(heading);
    const live = quotaData?.[name];
    const meters = live?.groups
      ? Object.entries(live.groups).flatMap(([groupName, group]) => [node('div', 'quota-group', groupName), quotaMeter('5 ชั่วโมง', group.five_hour), quotaMeter('รายสัปดาห์', group.weekly)])
      : [['5 ชั่วโมง', live?.five_hour], ['รายสัปดาห์', live?.weekly]].map(([label, win]) => quotaMeter(label, win));
    const stale = live?.stale === true;
    card.append(...meters, node('div', 'provider-note', live ? `${stale ? 'ค่าล่าสุดที่อ่านได้' : 'ข้อมูลสด'} · อ่านเมื่อ ${new Date(live.observed_at).toLocaleTimeString('th-TH', { timeZone: 'Asia/Bangkok' })}${stale ? ' · ดึงใหม่ไม่สำเร็จ ใช้ค่าเดิมไปก่อน' : ''}` : 'ไม่พบแหล่งข้อมูล quota ของ provider นี้'), node('div', 'provider-note', `${format(usage.observed_invocations)} ครั้งมีข้อมูล token · ${format(usage.unmeasured_invocations)} ครั้งข้อมูลไม่ครบ`), node('div', 'provider-note', provider.reason || 'ยังไม่มีข้อมูล'));
    el('providers').append(card);
  }
  const all = Object.values(data);
  const measured = all.reduce((sum, p) => sum + p.observed_invocations, 0);
  const unmeasured = all.reduce((sum, p) => sum + p.unmeasured_invocations, 0);
  el('usage-total').textContent = measured ? format(all.reduce((sum, p) => sum + p.total_tokens, 0)) : '—';
  el('usage-note').textContent = measured ? `บันทึก token ได้ ${format(measured)} ครั้ง · ข้อมูลไม่ครบ ${format(unmeasured)} ครั้ง` : 'ยังไม่มีข้อมูล token ที่ CLI รายงานในช่วงนี้';
  const workload = key => all.reduce((sum, p) => sum + p.workloads[key], 0);
  const observed = snapshot.usage?.latest_observed_at;
  el('usage-source').textContent = `ขอบเขต: งาน Center ${format(workload('tasks'))} · พัฒนา/ตรวจ Center ${format(workload('audits'))} · Live smoke ${format(workload('live_smoke'))} ครั้ง · ${observed ? 'ข้อมูลล่าสุด ' + new Date(observed).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' }) : 'ยังไม่มีหลักฐานการใช้จริง'}${snapshot.usage?.warnings?.length ? ' · ข้อมูลบางส่วนอ่านไม่ได้หรือเกินขนาดที่กำหนด' : ''}`;
  renderChart(data, measured);
}

function renderChart(data, measured) {
  const chart = el('usage-chart');
  chart.replaceChildren();
  if (!measured) {
    chart.className = 'chart empty';
    chart.append(node('span', '', 'ข้อมูลจริงจะแสดงที่นี่เมื่อ CLI รายงาน token'));
    return;
  }
  chart.className = 'chart';
  const dates = data.codex?.rows.map(d => d.date) || [];
  chart.style.setProperty('--days', dates.length);
  const totals = dates.map((date, i) => Object.values(data).reduce((sum, p) => sum + number(p.rows[i]?.total_tokens), 0));
  const maximum = Math.max(1, ...totals);
  dates.forEach((date, i) => {
    const column = node('div', 'chart-column');
    column.tabIndex = 0;
    column.setAttribute('role', 'img');
    const label = `${date} · ${format(totals[i])} tokens`;
    column.setAttribute('aria-label', label);
    column.title = label;
    const stack = node('div', 'bar-stack');
    for (const name of ['codex', 'claude', 'google']) {
      const part = node('div', 'bar-part ' + name);
      part.style.height = `${130 * number(data[name]?.rows[i]?.total_tokens) / maximum}px`;
      stack.append(part);
    }
    const showLabel = dates.length <= 7 || i % 5 === 0 || i === dates.length - 1;
    const pieces = date.split('-');
    column.append(stack, node('span', 'day-label', showLabel ? `${Number(pieces[2])}/${Number(pieces[1])}` : ''));
    chart.append(column);
  });
}

// ---- Task detail drawer: every field of a task, its plan, gates, reviews, authors and full timeline -------------------
const EVENT_LABELS = {
  queued: 'เข้าคิว', assigned: 'มอบหมายให้ AI', dispatch_recorded: 'บันทึกการเลือก AI / model', preparation_completed: 'เตรียม worktree เสร็จ (เช่น npm ci)',
  policy_context_delivered: 'ส่งกฎของโปรเจกต์ให้ AI', worker_started: 'AI เริ่มทำงาน', running: 'กำลังรัน', checkpoint_saved: 'บันทึก checkpoint (patch)',
  implementation_done: 'เขียนโค้ดเสร็จ', background_gates_started: 'เริ่มรัน gates เบื้องหลัง', gates: 'ผลรัน gates', waiting_for_independent_review: 'รอผู้ตรวจจากอีกค่าย',
  review: 'ผู้ตรวจเริ่มตรวจ', review_recorded: 'บันทึกผลการตรวจ', ready_for_human_approval: 'พร้อมให้คุณอนุมัติ', approved: 'อนุมัติแล้ว', blocked: 'ติดขัด',
  failed: 'ล้มเหลว', cancelled: 'ยกเลิก', provider_result_observed: 'อ่านผลและ usage จาก CLI', handoff_heartbeat_observed: 'IDE ส่งสัญญาณว่ายังทำงาน',
  cancellation_requested: 'มีคำขอยกเลิก', retry_wait: 'รอลองใหม่',
};
const parseJson = text => { try { return JSON.parse(text); } catch { return null; } };
const bangkok = iso => (iso ? new Date(iso).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' }) : '—');
const short = (value, max = 160) => { const text = typeof value === 'string' ? value : JSON.stringify(value); return text.length > max ? text.slice(0, max) + '…' : text; };

function viewSection(title, ...children) {
  const box = node('section', 'view-section');
  box.append(node('h3', '', title), ...children);
  return box;
}

function keyValues(rows) {
  const list = node('dl', 'kv');
  for (const [label, value] of rows) {
    if (value === undefined || value === null || value === '') continue;
    list.append(node('dt', '', label), node('dd', '', typeof value === 'string' ? value : String(value)));
  }
  return list;
}

function bullets(items, empty = '—') {
  if (!items?.length) return node('p', 'muted', empty);
  const list = node('ul', 'view-list');
  for (const item of items) list.append(node('li', '', item));
  return list;
}

function viewTable(headers, rows, empty) {
  if (!rows.length) return node('p', 'muted', empty);
  const table = node('table', 'view-table');
  const head = table.createTHead().insertRow();
  for (const header of headers) head.append(node('th', '', header));
  const body = table.createTBody();
  for (const row of rows) {
    const tr = body.insertRow();
    for (const cell of row) tr.insertCell().textContent = cell ?? '—';
  }
  const wrap = node('div', 'table-wrap');
  wrap.append(table);
  return wrap;
}

function columnOf(status) {
  const found = BOARD_COLUMNS.find(([, , statuses]) => statuses.includes(status));
  return found ? found[0] : 'todo';
}

function renderTaskView(data) {
  const task = data.task;
  const config = parseJson(task.config_json) || {};
  const events = (data.events || []).map(row => ({ ...row, info: parseJson(row.detail) || {} }));
  const dispatches = events.filter(e => e.event === 'dispatch_recorded');
  const view = el('task-static');
  view.replaceChildren();

  const badge = node('span', `status-badge board-${columnOf(task.status)}-badge`, STEP_LABELS[task.status] || task.status);
  const head = node('div', 'view-head');
  head.append(node('h3', 'view-title', task.title), badge, node('span', 'muted', `${task.project_id} · รหัส ${task.id} · สถานะภายใน: ${task.status}`));
  view.append(head);
  const reason = task.error || events.filter(e => e.event === 'blocked').map(e => e.info.reason).pop();
  if (reason) view.append(node('p', 'view-alert', `สาเหตุที่ติดขัด/ล้มเหลว: ${waitingLabels[reason] || reason}`));

  view.append(viewSection('ภาพรวม', keyValues([
    ['โหมด', task.mode], ['ความซับซ้อน (1-5)', task.complexity], ['ครั้งที่ทำ', `${task.attempt} จาก ${task.max_attempts}`], ['ครั้งที่ตรวจ', task.review_attempt],
    ['AI ที่ขอไว้', task.requested_provider], ['ผู้เขียนล่าสุด', task.provider ? names[task.provider] || task.provider : 'ยังไม่ได้เลือก'],
    ['ผู้ตรวจ', task.reviewer ? names[task.reviewer] || task.reviewer : 'ยังไม่มี'], ['สร้างเมื่อ', bangkok(task.created_at)], ['อัปเดตล่าสุด', bangkok(task.updated_at)],
    ['อนุมัติเมื่อ', task.approved_at ? bangkok(task.approved_at) : ''], ['อนุมัติโดย', task.approved_by], ['ขอให้ยกเลิก', task.cancel_requested ? 'ใช่' : ''],
    ['เริ่มได้หลังเวลา', task.not_before ? bangkok(new Date(task.not_before * 1000).toISOString()) : ''],
  ])));

  view.append(viewSection('สิ่งที่สั่งให้ทำ',
    node('h4', '', 'คำสั่ง (prompt)'), node('pre', 'view-pre', task.prompt || '—'),
    node('h4', '', 'ขอบเขตไฟล์ (scope)'), bullets(parseJson(task.scope_json)),
    node('h4', '', 'เงื่อนไขสำเร็จ (acceptance)'), bullets(parseJson(task.acceptance_json)),
    node('h4', '', 'ต้องรอผลงานก่อนหน้า'), bullets(parseJson(task.dependencies_json), 'ไม่มี'),
    node('h4', '', 'ไฟล์ที่ AI ต้องอ่านเป็นพิเศษ (read set)'), bullets(config.read_set, 'ไม่ระบุ (ใช้ทั้ง scope)'),
    node('h4', '', 'คำสั่ง quality gates ของโปรเจกต์'), bullets((config.quality_gates || []).map(g => g.join(' ')), 'ไม่มี'),
    node('h4', '', 'คำสั่งเตรียม worktree'), bullets((config.prepare_commands || []).map(g => g.join(' ')), 'ไม่มี')));

  view.append(viewSection('AI ที่ Center เลือก (แต่ละขั้น)', viewTable(
    ['ขั้น', 'AI', 'model', 'effort', 'skill', 'ช่องทาง', 'ประเภทงาน', 'เหตุผลที่เลือก', 'ผู้ที่เข้าเกณฑ์', 'หมายเหตุ'],
    dispatches.map(e => [ROLE_LABELS[e.info.role] || e.info.role, names[e.info.provider] || e.info.provider, e.info.model, e.info.effort || '—', (e.info.skills || []).join(', ') || '—',
      ADAPTER_LABELS[e.info.adapter] || e.info.adapter, e.info.task_kind, (e.info.plan_reasons || []).join(' · '), (e.info.eligible_candidates || []).map(p => names[p] || p).join(', '),
      (e.info.candidate_notes || []).join(' · ')]), 'ยังไม่มีการเลือก AI (งานยังไม่ถูกหยิบ)')));

  const gateEvidence = (data.evidence || []).filter(e => e.kind === 'gates').map(e => ({ row: e, payload: parseJson(e.payload) || {} }));
  const gateFailure = events.filter(e => e.event === 'failed' && e.info.gate_failed !== undefined).pop();
  const gateRows = gateEvidence.flatMap(({ payload }) => (payload.outcomes || []).map(o => [(o.argv || []).join(' '), o.code === 0 && !o.error ? 'ผ่าน' : 'ไม่ผ่าน', o.code, o.error || '—']));
  view.append(viewSection('ผล quality gates', gateRows.length ? viewTable(['คำสั่ง', 'ผล', 'exit code', 'ข้อผิดพลาด'], gateRows)
    : node('p', gateFailure ? 'view-alert' : 'muted', gateFailure ? `gate ลำดับที่ ${Number(gateFailure.info.gate_failed) + 1} ไม่ผ่าน (ดู log ในไทม์ไลน์) จึงไม่มีหลักฐานการผ่าน` : 'ยังไม่ถึงขั้นรัน gates หรือยังไม่มีผล')));

  const reviews = (data.evidence || []).filter(e => e.kind === 'review' || e.kind === 'human_review').map(e => ({ row: e, payload: parseJson(e.payload) || {} }));
  view.append(viewSection('ผลการตรวจโดยอีกค่าย', viewTable(['ผู้ตรวจ', 'ชนิด', 'ผล', 'สรุป', 'เวลา'],
    reviews.map(({ row, payload }) => [names[row.provider] || row.provider || 'คน', row.kind === 'human_review' ? 'ตรวจโดยคน' : row.simulated ? 'จำลอง (mock)' : 'AI จริง', payload.verdict, payload.summary, bangkok(row.created_at)]),
    'ยังไม่มีผลการตรวจ')));

  const result = parseJson(task.result);
  view.append(viewSection('ผลที่ AI ส่งกลับ (ขั้นเขียนโค้ด)', result ? keyValues([
    ['สรุป', result.summary], ['สถานะที่ AI รายงาน', result.status], ['model ที่ CLI รายงาน', (result.models_observed || []).join(', ')], ['session ของ CLI', result.provider_session_ref],
    ['ไฟล์ที่ถูกแก้', (result.applied_paths || []).join(', ')],
    ['token (รวม)', result.usage_observed?.total_tokens], ['token เข้า/ออก', result.usage_observed ? `${result.usage_observed.input_tokens} / ${result.usage_observed.output_tokens}` : ''],
  ]) : node('p', 'muted', 'ยังไม่มีผลจาก AI')));

  view.append(viewSection('ผู้เขียนทั้งหมดของงานนี้ (authorship)', viewTable(['AI', 'ครั้งที่', 'session', 'เวลา'],
    (data.authorship || []).map(a => [names[a.provider] || a.provider, a.attempt, a.session_id, bangkok(a.created_at)]), 'ยังไม่มี (ยังไม่มี AI เขียนงานนี้)')));

  view.append(viewSection('Session ที่กำลังครองงานนี้', viewTable(['AI', 'ขั้น', 'ช่องทาง', 'model', 'เริ่ม', 'lease หมดเมื่อ', 'port ทดสอบ'],
    (data.sessions || []).map(s => [names[s.provider] || s.provider, ROLE_LABELS[s.role] || s.role, ADAPTER_LABELS[s.adapter] || s.adapter, s.model || '—',
      bangkok(s.started_at), bangkok(new Date(s.lease_until * 1000).toISOString()), s.test_port || '—']), 'ไม่มี session ที่กำลังทำงาน')));

  view.append(viewSection(`ไทม์ไลน์เหตุการณ์ทั้งหมด (${events.length})`, viewTable(['เวลา', 'เหตุการณ์', 'รายละเอียด'],
    events.map(e => [bangkok(e.created_at), EVENT_LABELS[e.event] || e.event, Object.entries(e.info).filter(([k]) => k !== 'eligible_candidates').map(([k, v]) => `${k}: ${short(v, 120)}`).join(' · ')]), 'ยังไม่มีเหตุการณ์')));

  view.append(viewSection('ตำแหน่งไฟล์ (เจ้าของ Center เท่านั้น)', keyValues([
    ['โปรเจกต์ต้นทาง', task.workspace], ['worktree ของงาน', task.worktree], ['branch', task.branch], ['โฟลเดอร์ผลรัน', task.run_dir], ['checkpoint', task.checkpoint],
    ['base revision', task.base_rev], ['patch hash', task.patch_hash],
  ])));
}

// ---- Live view inside the drawer: current phase, what is running, and the tail of the run's logs ---------------------------
const FLOW = [
  ['queued', 'เข้าคิว'], ['assigned', 'รับงาน/เตรียม'], ['running', 'AI เขียนโค้ด'], ['implementation_done', 'เขียนเสร็จ'], ['gates', 'รัน gates'],
  ['waiting_for_independent_review', 'รอผู้ตรวจ'], ['review', 'ตรวจ'], ['ready_for_human_approval', 'รออนุมัติ'], ['approved', 'อนุมัติ'],
];
const POLL_ACTIVE_MS = 2500;
const POLL_IDLE_MS = 10000;
const ACTIVE_STATUSES = new Set(['queued', 'retry_wait', 'assigned', 'running', 'implementation_done', 'gates', 'waiting_for_independent_review', 'review']);
const drawerState = { id: null, timer: null, key: '' };

function nowSentence(task, sessions, live, events) {
  const config = parseJson(task.config_json) || {};
  const session = sessions[0];
  const who = session ? `${names[session.provider] || session.provider}${session.model ? ' (' + session.model + ')' : ''}` : 'AI';
  const gates = (config.quality_gates || []).map(g => g.join(' '));
  const gateLogs = (live?.all_log_files || []).filter(n => /^gate-\d+\.log$/.test(n)).map(n => Number(n.match(/\d+/)[0]));
  const lastReason = events.filter(e => e.event === 'blocked' || e.event === 'failed').map(e => e.info.reason || e.info.gate_failed).pop();
  switch (task.status) {
    case 'queued': case 'retry_wait': {
      const reason = snapshot?.tasks?.find(t => t.id === task.id)?.waiting_reason;
      return `รอคิว${reason && reason !== 'ready' ? ' — ' + (waitingLabels[reason] || reason) : ' — ระบบกำลังรอหยิบงานนี้'}`;
    }
    case 'assigned': return `มอบหมายให้ ${who} แล้ว Center กำลังเตรียม worktree และรันคำสั่งเตรียม (${(config.prepare_commands || []).map(c => c.join(' ')).join(', ') || 'ไม่มี'})`;
    case 'running': return `${who} กำลังเขียนโค้ดใน worktree${session?.started_at ? ' (เริ่ม ' + ago(session.started_at) + ')' : ''}`;
    case 'implementation_done': return 'เขียนโค้ดเสร็จแล้ว กำลังจะเริ่มรัน quality gates';
    case 'gates': {
      const index = gateLogs.length ? Math.max(...gateLogs) : 0;
      return `Center กำลังรัน gate ลำดับที่ ${index + 1} จาก ${gates.length || '?'}${gates[index] ? ': ' + gates[index] : ''} (ไม่ใช้ AI)`;
    }
    case 'waiting_for_independent_review': return 'โค้ดผ่าน gates แล้ว กำลังรอเลือกผู้ตรวจจากอีกค่าย (ต้องไม่ใช่ผู้เขียน)';
    case 'review': return `${who} กำลังตรวจ patch`;
    case 'ready_for_human_approval': return 'ครบทุกขั้นแล้ว รอคุณอนุมัติใน terminal ของ Center';
    case 'approved': return 'อนุมัติแล้ว งานนี้เสร็จสมบูรณ์';
    case 'cancelled': return 'งานถูกยกเลิก';
    default: return `${STEP_LABELS[task.status] || task.status}${task.error || lastReason ? ' — สาเหตุ: ' + (waitingLabels[task.error || lastReason] || task.error || lastReason) : ''}`;
  }
}

function stepper(task, events) {
  let position = FLOW.findIndex(([status]) => status === task.status);
  let stalled = false;
  if (position < 0) {
    stalled = true;
    const seen = events.map(e => FLOW.findIndex(([status]) => status === e.event)).filter(i => i >= 0);
    position = seen.length ? Math.max(...seen) : 0;
  }
  const row = node('ol', 'stepper');
  FLOW.forEach(([, label], index) => {
    const state = index < position ? 'done' : index === position ? (stalled ? 'stalled' : 'current') : 'todo';
    row.append(node('li', `step step-${state}`, label));
  });
  return row;
}

function formatLogLine(line) {
  const text = line.trim();
  if (text.startsWith('{')) {
    const item = parseJson(text);
    if (item) {
      const type = item.type || item.event || item.status || 'json';
      const body = item.item?.command || item.item?.text || item.message || item.error?.message || item.result || item.response || '';
      return `[${type}] ${short(typeof body === 'string' ? body : JSON.stringify(body), 220)}`;
    }
  }
  return short(text, 260);
}

function renderLogs(live) {
  const box = node('div', 'live-logs');
  box.append(node('h4', '', 'ผลลัพธ์สดของขั้นนี้ (ท้าย log ล่าสุด)'));
  if (!live?.files?.length) {
    box.append(node('p', 'muted', 'ยังไม่มี log ของรอบนี้ (งานอาจยังไม่ถูกหยิบ หรือเสร็จแล้วและเก็บ log ไว้ที่อื่น)'));
    return box;
  }
  live.files.forEach((file, index) => {
    const details = node('details', 'log-file');
    details.open = index === 0;
    details.dataset.name = file.name;
    details.append(node('summary', '', `${file.name} · ${format(file.size)} bytes · เขียนล่าสุด ${file.age_seconds} วินาทีที่แล้ว${file.truncated ? ' · แสดงเฉพาะท้ายไฟล์' : ''}`));
    const lines = file.tail.split(String.fromCharCode(10)).filter(l => l.trim()).slice(-40).map(formatLogLine);
    details.append(node('pre', 'log-tail', lines.length ? lines.join(String.fromCharCode(10)) : '(ว่าง)'));
    box.append(details);
  });
  return box;
}

function renderLive(report, live) {
  const task = report.task;
  const events = (report.events || []).map(row => ({ ...row, info: parseJson(row.detail) || {} }));
  const sessions = report.sessions || [];
  const body = el('live-body');
  // Keep what the reader had open and where they had scrolled, so a refresh never yanks the view away.
  const open = new Set([...body.querySelectorAll('details.log-file[open]')].map(d => d.dataset.name));
  const hadLogs = body.querySelector('details.log-file');
  const pinned = new Map([...body.querySelectorAll('details.log-file')].map(d => { const pre = d.querySelector('pre'); return [d.dataset.name, pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8]; }));
  const lead = node('p', 'live-now', nowSentence(task, sessions, live, events));
  const parts = [lead, stepper(task, events)];
  for (const session of sessions) {
    parts.push(node('p', 'live-session', `session: ${names[session.provider] || session.provider} · ${ROLE_LABELS[session.role] || session.role} · ${ADAPTER_LABELS[session.adapter] || session.adapter} · ${session.model || 'model ตามค่าเริ่มต้น'} · เริ่ม ${session.started_at ? ago(session.started_at) : 'ยังไม่ยืนยัน'} · lease หมดใน ${Math.max(0, Math.round(session.lease_until - Date.now() / 1000))} วินาที`));
  }
  if (task.status === 'running' && Date.now() - Date.parse(task.updated_at) > 15 * 60000) {
    parts.push(node('p', 'view-alert', `ไม่มีความเคลื่อนไหวในฐานข้อมูลมา ${ago(task.updated_at)} (AI ที่คิดนานอาจเงียบได้ ถ้านานผิดปกติให้ตรวจ log ด้านล่าง)`));
  }
  const logs = renderLogs(live);
  parts.push(logs);
  body.replaceChildren(...parts);
  if (hadLogs) {
    for (const d of body.querySelectorAll('details.log-file')) {
      d.open = open.has(d.dataset.name);
      const pre = d.querySelector('pre');
      if (pinned.get(d.dataset.name) !== false) pre.scrollTop = pre.scrollHeight;
    }
  } else {
    const first = body.querySelector('pre');
    if (first) first.scrollTop = first.scrollHeight;
  }
  el('live-stamp').textContent = `● สด · อัปเดต ${new Date().toLocaleTimeString('th-TH', { timeZone: 'Asia/Bangkok' })}${ACTIVE_STATUSES.has(task.status) ? '' : ' (งานไม่ได้กำลังทำงาน ตรวจทุก 10 วินาที)'}`;
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error('unavailable');
  return response.json();
}

async function pollTask(id) {
  if (drawerState.id !== id) return;
  let status = '';
  try {
    const [report, live] = await Promise.all([getJson('/api/tasks/' + encodeURIComponent(id)), getJson('/api/tasks/' + encodeURIComponent(id) + '/live').catch(() => null)]);
    if (drawerState.id !== id) return;
    status = report.task.status;
    el('detail').textContent = JSON.stringify(report, null, 2);
    el('live-panel').hidden = false;
    renderLive(report, live);
    const key = `${report.task.updated_at}|${status}|${report.events.length}|${report.evidence.length}|${report.sessions.length}`;
    if (key !== drawerState.key) {
      drawerState.key = key;
      renderTaskView(report);
    }
  } catch {
    if (!drawerState.key) {
      el('task-static').textContent = 'อ่านรายละเอียดไม่ได้ กรุณาอัปเดตสถานะแล้วลองใหม่';
      el('detail').textContent = 'อ่านหลักฐานไม่ได้ กรุณาอัปเดตสถานะแล้วลองใหม่';
    } else el('live-stamp').textContent = '● ติดต่อ Center ไม่ได้ จะลองใหม่เอง';
  }
  if (drawerState.id === id && !el('live-pause').checked) {
    drawerState.timer = setTimeout(() => pollTask(id), ACTIVE_STATUSES.has(status) ? POLL_ACTIVE_MS : POLL_IDLE_MS);
  }
}

function openDrawer() {
  el('task-drawer').hidden = false;
  el('drawer-backdrop').hidden = false;
  el('drawer-close').focus();
}

function closeDrawer() {
  clearTimeout(drawerState.timer);
  drawerState.id = null;
  drawerState.key = '';
  el('task-drawer').hidden = true;
  el('drawer-backdrop').hidden = true;
}

async function details(id) {
  clearTimeout(drawerState.timer);
  openDrawer();
  Object.assign(drawerState, { id, key: '' });
  el('live-pause').checked = false;
  el('live-panel').hidden = true;
  el('live-body').replaceChildren();
  el('task-static').textContent = 'กำลังอ่านรายละเอียด…';
  el('detail').textContent = 'กำลังอ่านหลักฐาน…';
  await pollTask(id);
}

// ---- Tabs: task monitoring and the usage meter are separate screens ---------------------------------------------------
function selectTab(name) {
  const tab = name === 'usage' ? 'usage' : 'monitor';
  for (const key of ['monitor', 'usage']) {
    el('panel-' + key).hidden = key !== tab;
    el('tab-' + key).setAttribute('aria-selected', String(key === tab));
    el('tab-' + key).classList.toggle('tab-active', key === tab);
  }
  closeDrawer();
  try { history.replaceState(null, '', '#' + tab); } catch { /* the page still works without a hash */ }
  try { localStorage.setItem('center-tab', tab); } catch { /* storage may be blocked */ }
}

function initialTab() {
  const hash = location.hash.replace('#', '');
  if (hash === 'usage' || hash === 'monitor') return hash;
  try { return localStorage.getItem('center-tab') === 'usage' ? 'usage' : 'monitor'; } catch { return 'monitor'; }
}

// Board: what is waiting, running, under review, or done, grouped by status (todo / in progress / done).
const BOARD_COLUMNS = [
  ['todo', 'ต้องทำ (รอคิว)', ['queued', 'retry_wait']],
  ['doing', 'กำลังทำ', ['assigned', 'running', 'implementation_done', 'gates']],
  ['review', 'ตรวจโดยอีกค่าย', ['waiting_for_independent_review', 'review']],
  ['approve', 'รอคุณอนุมัติ', ['ready_for_human_approval']],
  ['done', 'เสร็จ (อนุมัติแล้ว)', ['approved']],
  ['problem', 'ติดปัญหา / ยกเลิก', ['blocked', 'failed', 'cancelled']],
];
const STEP_LABELS = {
  queued: 'รอคิว', retry_wait: 'รอลองใหม่', assigned: 'รับงานแล้ว กำลังเตรียม', running: 'AI กำลังเขียนโค้ด',
  implementation_done: 'เขียนเสร็จ รอรัน gates', gates: 'กำลังรัน gates (ไม่ใช้ AI)', waiting_for_independent_review: 'รอผู้ตรวจจากอีกค่าย',
  review: 'ผู้ตรวจกำลังตรวจ', ready_for_human_approval: 'รอคุณอนุมัติ', approved: 'อนุมัติแล้ว', blocked: 'ติดขัด ต้องดูสาเหตุ', failed: 'ล้มเหลว', cancelled: 'ยกเลิกแล้ว',
};
const ROLE_LABELS = { implementation: 'เขียนโค้ด', review: 'ตรวจ' };
const ADAPTER_LABELS = { live: 'CLI ของค่าย', handoff: 'IDE ทำเอง', gates: 'รัน gates (ไม่ใช้ AI)', mock: 'ทดสอบ (mock)' };
const BOARD_LIMIT = 8;

function ago(iso) {
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 1000));
  if (!Number.isFinite(seconds)) return '';
  if (seconds < 90) return `${seconds} วินาทีที่แล้ว`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} นาทีที่แล้ว`;
  return `${Math.round(seconds / 3600)} ชั่วโมงที่แล้ว`;
}

function stepText(step) {
  if (!step?.model) return '';
  return `${names[step.provider] || step.provider} · ${step.model}${step.effort ? ' · effort ' + step.effort : ''}${step.skills?.length ? ' · ' + step.skills.join(', ') : ''}`;
}

function renderRunningNow(tasksById, project) {
  const box = el('running-now');
  box.replaceChildren();
  const sessions = snapshot.sessions.filter(s => !project || tasksById.get(s.task_id)?.project_id === project);
  box.append(node('h3', '', `กำลังรันอยู่ตอนนี้ (${format(sessions.length)} session)`));
  if (!sessions.length) {
    box.append(node('p', 'muted', 'ไม่มีงานที่กำลังรันอยู่ ณ ตอนนี้'));
    return;
  }
  for (const session of sessions) {
    const task = tasksById.get(session.task_id);
    const step = task?.plan?.[session.role];
    const row = node('div', 'run-row');
    row.style.setProperty('--accent', colors[session.provider] || '#96a7be');
    row.append(node('strong', 'run-ai', names[session.provider] || session.provider),
      node('span', '', `${ROLE_LABELS[session.role] || session.role} · ${ADAPTER_LABELS[session.adapter] || session.adapter}`),
      node('span', 'run-model', `${session.model || step?.model || 'model ตามค่าเริ่มต้นของ CLI'}${step?.effort ? ' · effort ' + step.effort : ''}`),
      node('span', 'run-task', `${task?.project_id || '?'} › ${task?.title || session.task_id}`),
      node('span', 'muted', session.started_at ? `เริ่ม ${ago(session.started_at)}` : 'ยังไม่ยืนยันว่าเริ่ม'));
    box.append(row);
  }
}

function boardCard(task) {
  const card = node('article', 'board-card');
  card.append(node('strong', '', task.title), node('span', 'muted', `${task.project_id} · ครั้งที่ ${task.attempt || 0} · ${ago(task.updated_at)}`),
    node('span', 'board-step', STEP_LABELS[task.status] || task.status));
  const reason = task.waiting_reason || task.error;
  if (reason && reason !== 'ready') card.append(node('small', 'task-reason', waitingLabels[reason] || reason));
  const write = stepText(task.plan?.implementation);
  const check = stepText(task.plan?.review);
  if (write) card.append(node('small', 'board-ai', 'เขียน: ' + write));
  if (check) card.append(node('small', 'board-ai', 'ตรวจ: ' + check));
  if (!write && !check) card.append(node('small', 'muted', task.provider ? names[task.provider] || task.provider : 'ยังไม่ได้เลือก AI'));
  const button = node('button', '', 'ดูรายละเอียด');
  button.type = 'button';
  button.addEventListener('click', () => details(task.id));
  card.append(button);
  return card;
}

function renderBoard() {
  if (!snapshot) return;
  const select = el('board-project');
  const chosen = select.value;
  const projects = [...new Set([...snapshot.projects.map(p => p.id), ...snapshot.tasks.map(t => t.project_id)])].sort();
  select.replaceChildren(new Option('ทุกโปรเจกต์', ''), ...projects.map(id => new Option(id, id)));
  select.value = projects.includes(chosen) ? chosen : '';
  const project = select.value;
  const tasks = snapshot.tasks.filter(t => !project || t.project_id === project);
  renderRunningNow(new Map(snapshot.tasks.map(t => [t.id, t])), project);
  el('status-chips').replaceChildren(...BOARD_COLUMNS.map(([key, title, statuses]) => node('span', `chip chip-${key}`, `${title}: ${format(tasks.filter(t => statuses.includes(t.status)).length)}`)));
  el('board-columns').replaceChildren(...BOARD_COLUMNS.map(([key, title, statuses]) => {
    const items = tasks.filter(t => statuses.includes(t.status));
    const column = node('div', `board-column board-${key}`);
    column.append(node('h3', '', `${title} (${format(items.length)})`));
    if (!items.length) column.append(node('p', 'muted', '—'));
    for (const task of items.slice(0, BOARD_LIMIT)) column.append(boardCard(task));
    if (items.length > BOARD_LIMIT) column.append(node('p', 'muted', `และอีก ${format(items.length - BOARD_LIMIT)} งาน (ดูในตารางด้านล่าง)`));
    return column;
  }));
  el('board-note').textContent = `แสดงจากงานล่าสุด ${format(snapshot.tasks.length)} งาน อัปเดตทุก 5 วินาที · งานที่ Claude Code ทำเองนอก Center ไม่ปรากฏที่นี่ และ session ที่เปิดนอก Center นับไม่ได้`;
}

function renderService() {
  const service = snapshot.service || {};
  const running = service.running === true;
  el('scheduler-info').className = 'service-panel ' + (running ? 'service-running' : 'service-stopped');
  el('scheduler-state').textContent = running ? 'กำลังทำงาน' : 'หยุดอยู่ / ยังไม่พร้อม';
  el('scheduler-mode').textContent = service.mode === 'live' ? 'โหมดใช้งานจริง' : service.mode === 'mock' ? 'โหมดทดสอบ' : 'ยังไม่ทราบโหมด';
  const age = service.heartbeat_age_seconds;
  el('scheduler-age').textContent = typeof age === 'number' && Number.isFinite(age) ? ` · ยืนยันล่าสุด ${Math.floor(age)} วินาทีที่แล้ว` : '';
  el('scheduler-note').textContent = running ? (service.mode === 'mock' ? 'กำลังประมวลผลงานทดสอบ งานจริงยังไม่ถูกเรียก' : 'ระบบพร้อมหยิบงานที่ผ่านเงื่อนไขจากคิว')
    : service.reason === 'heartbeat_stale' ? 'ไม่ได้รับสัญญาณล่าสุดจากตัวประมวลผลคิว งานใหม่จะรอจนกว่าจะตรวจและเปิดระบบอีกครั้ง'
      : 'หน้าเว็บและฐานข้อมูลเชื่อมต่อได้ แต่งานใหม่จะรอจนกว่าจะเปิดตัวประมวลผลคิว';
}

function renderTasks() {
  if (!snapshot) return;
  const search = el('task-search').value.trim().toLocaleLowerCase('th-TH');
  const status = el('task-status').value;
  const tasks = snapshot.tasks.filter(task => (!status || task.status === status)
    && (!search || `${task.title} ${task.project_id} ${task.id}`.toLocaleLowerCase('th-TH').includes(search)));
  el('task-count').textContent = `${format(tasks.length)} จาก ${format(snapshot.tasks.length)} งานที่โหลดล่าสุด`;
  el('tasks').replaceChildren();
  if (!tasks.length) {
    const cell = el('tasks').insertRow().insertCell();
    cell.colSpan = 6;
    cell.textContent = snapshot.tasks.length ? 'ไม่พบงานตามเงื่อนไขที่เลือก' : 'ยังไม่มีงานในคิว';
  }
  for (const task of tasks) {
    const row = el('tasks').insertRow();
    row.insertCell().textContent = task.title;
    row.insertCell().textContent = task.project_id;
    const state = row.insertCell();
    state.append(node('span', '', task.status));
    const reason = task.waiting_reason || task.error;
    if (reason && reason !== 'ready') state.append(node('small', 'task-reason', waitingLabels[reason] || reason));
    const provider = row.insertCell();
    provider.textContent = task.provider || 'รอมอบหมาย';
    for (const [role, label] of [['implementation', 'ทำ'], ['review', 'ตรวจ']]) {
      const step = task.plan?.[role];
      if (step?.model) provider.append(node('small', 'task-reason', `${label}: ${step.provider} · ${step.model}${step.effort ? ' · ' + step.effort : ''}${step.skills?.length ? ' · ' + step.skills.join(', ') : ''}`));
    }
    if (task.routing_reason) provider.title = typeof task.routing_reason === 'string' ? task.routing_reason : JSON.stringify(task.routing_reason);
    row.insertCell().textContent = task.mode;
    const button = node('button', '', 'ดู');
    button.type = 'button';
    button.addEventListener('click', () => details(task.id));
    row.insertCell().append(button);
  }
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  el('refresh').disabled = true;
  try {
    const response = await fetch('/api/status');
    if (!response.ok) throw new Error('unavailable');
    snapshot = await response.json();
    el('health').className = '';
    el('health').textContent = 'เชื่อมต่อแล้ว · อัปเดต ' + new Date(snapshot.updated).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' });
    el('projects').textContent = snapshot.projects.length;
    el('sessions').textContent = snapshot.sessions.length + ' / ' + (snapshot.capacity ? snapshot.capacity.usable_global : snapshot.global_capacity) + (snapshot.capacity && snapshot.capacity.ide_reserved > 0 ? ' (สำรอง IDE ' + snapshot.capacity.ide_reserved + ')' : '');
    el('approval-count').textContent = snapshot.tasks.filter(t => t.status === 'ready_for_human_approval').length;
    el('live').textContent = snapshot.live_execution ? 'เปิดใช้งาน' : 'ปิดไว้';
    renderService();
    renderUsage();
    renderBoard();
    renderTasks();
  } catch {
    el('health').textContent = 'ติดต่อ Center ไม่ได้ — ตรวจ doctor / service-status ไม่มีการเริ่ม worker แทนโดยอัตโนมัติ';
    el('health').className = 'error';
    el('scheduler-state').textContent = 'ยังยืนยันสถานะไม่ได้';
    el('scheduler-info').className = 'service-panel service-stopped';
    el('scheduler-mode').textContent = 'ยังไม่ทราบโหมด';
    el('scheduler-age').textContent = '';
    el('scheduler-note').textContent = 'ข้อมูลก่อนหน้าอาจไม่ใช่สถานะปัจจุบัน กรุณาตรวจการเชื่อมต่อแล้วอัปเดตอีกครั้ง';
  } finally { refreshing = false; el('refresh').disabled = false; }
}

el('refresh').addEventListener('click', refresh);
el('usage-window').addEventListener('change', renderUsage);
el('board-project').addEventListener('change', renderBoard);
el('tab-monitor').addEventListener('click', () => selectTab('monitor'));
el('tab-usage').addEventListener('click', () => selectTab('usage'));
el('drawer-close').addEventListener('click', closeDrawer);
el('drawer-backdrop').addEventListener('click', closeDrawer);
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeDrawer(); });
window.addEventListener('hashchange', () => selectTab(initialTab()));
selectTab(initialTab());
el('task-search').addEventListener('input', renderTasks);
el('task-status').addEventListener('change', renderTasks);
refresh();
setInterval(refresh, 5000);
refreshQuota();
setInterval(refreshQuota, 3000);
el('live-pause').addEventListener('change', () => { if (!el('live-pause').checked && drawerState.id) { clearTimeout(drawerState.timer); pollTask(drawerState.id); } });
