const el = id => document.getElementById(id);
const format = value => new Intl.NumberFormat('th-TH').format(value);
const number = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
const names = { codex: 'Codex', claude: 'Claude', google: 'Google' };
const colors = { codex: '#6bc6aa', claude: '#dba07b', google: '#8baeff' };
let snapshot = null;
let refreshing = false;

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

function renderUsage() {
  if (!snapshot) return;
  el('providers').replaceChildren();
  const data = {};
  for (const [name, provider] of Object.entries(snapshot.providers)) {
    const usage = stats(name);
    data[name] = usage;
    const measured = usage.observed_invocations > 0;
    const card = node('article', 'provider-card');
    card.style.setProperty('--accent', colors[name] || '#96a7be');
    const heading = node('div', 'provider-heading');
    heading.append(node('h3', 'provider-brand', names[name] || name), node('span', 'badge ' + provider.availability, provider.availability === 'available' ? 'พร้อมทำงาน' : provider.availability === 'unavailable' ? 'ยังไม่พร้อม' : 'ยังไม่ยืนยัน'));
    card.append(heading, node('div', 'token-caption', 'Token ที่ CLI รายงานในช่วงที่เลือก'));
    const value = node('div', 'token-value', measured ? format(usage.total_tokens) : '—');
    value.append(node('small', '', 'tokens'));
    card.append(value);
    const breakdown = node('dl', 'token-breakdown');
    for (const [label, count] of [['Input', usage.input_tokens], ['Output', usage.output_tokens], ['Cache ใน input', usage.cached_input_tokens + usage.cache_write_tokens]]) {
      const item = node('div');
      item.append(node('dt', '', label), node('dd', '', measured ? format(count) : '—'));
      breakdown.append(item);
    }
    card.append(breakdown);
    const quota = node('div', 'quota-line');
    quota.append(node('span', '', 'Quota แพ็กเกจคงเหลือ'), node('strong', '', 'ไม่ทราบ (unknown)'));
    const reset = node('div', 'quota-line');
    reset.append(node('span', '', 'เวลารีเซ็ต'), node('strong', '', provider.reset_at === 'unknown' || !provider.reset_at ? 'ไม่ทราบ' : provider.reset_at));
    card.append(quota, reset, node('div', 'provider-note', `${format(usage.observed_invocations)} ครั้งมีข้อมูล token · ${format(usage.unmeasured_invocations)} ครั้งข้อมูลไม่ครบ`), node('div', 'provider-note', provider.reason || 'ยังไม่มีข้อมูล'));
    el('providers').append(card);
  }
  const all = Object.values(data);
  const measured = all.reduce((sum, p) => sum + p.observed_invocations, 0);
  const unmeasured = all.reduce((sum, p) => sum + p.unmeasured_invocations, 0);
  el('usage-total').textContent = measured ? format(all.reduce((sum, p) => sum + p.total_tokens, 0)) : '—';
  el('usage-note').textContent = measured ? `บันทึก token ได้ ${format(measured)} ครั้ง · ข้อมูลไม่ครบ ${format(unmeasured)} ครั้ง` : 'ยังไม่มีข้อมูล token ที่ CLI รายงานในช่วงนี้';
  const workload = key => all.reduce((sum, p) => sum + p.workloads[key], 0);
  const observed = snapshot.usage?.latest_observed_at;
  el('usage-source').textContent = `ขอบเขต: งาน Center ${format(workload('tasks'))} · ตรวจโค้ด ${format(workload('audits'))} · Live smoke ${format(workload('live_smoke'))} ครั้ง · ${observed ? 'ข้อมูลล่าสุด ' + new Date(observed).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' }) : 'ยังไม่มีหลักฐานการใช้จริง'}${snapshot.usage?.warnings?.length ? ' · ข้อมูลบางส่วนอ่านไม่ได้หรือเกินขนาดที่กำหนด' : ''}`;
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

async function details(id) {
  el('detail-panel').open = true;
  el('detail').textContent = 'กำลังอ่านหลักฐาน…';
  try {
    const response = await fetch('/api/tasks/' + encodeURIComponent(id));
    if (!response.ok) throw new Error('unavailable');
    el('detail').textContent = JSON.stringify(await response.json(), null, 2);
  } catch { el('detail').textContent = 'อ่านหลักฐานไม่ได้ กรุณาอัปเดตสถานะแล้วลองใหม่'; }
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
    el('sessions').textContent = snapshot.sessions.length + ' / ' + snapshot.global_capacity;
    el('approval-count').textContent = snapshot.tasks.filter(t => t.status === 'ready_for_human_approval').length;
    el('live').textContent = snapshot.live_execution ? 'เปิดใช้งาน' : 'ปิดไว้';
    renderUsage();
    el('tasks').replaceChildren();
    if (!snapshot.tasks.length) {
      const cell = el('tasks').insertRow().insertCell();
      cell.colSpan = 6;
      cell.textContent = 'ยังไม่มีงานในคิว';
    }
    for (const task of snapshot.tasks) {
      const row = el('tasks').insertRow();
      for (const value of [task.title, task.project_id, task.status, task.provider || 'รอมอบหมาย', task.mode]) row.insertCell().textContent = value;
      const button = node('button', '', 'ดู');
      button.type = 'button';
      button.addEventListener('click', () => details(task.id));
      row.insertCell().append(button);
    }
  } catch {
    el('health').textContent = 'ติดต่อ Center ไม่ได้ — ตรวจ doctor / service-status ไม่มีการเริ่ม worker แทนโดยอัตโนมัติ';
    el('health').className = 'error';
  } finally { refreshing = false; el('refresh').disabled = false; }
}

el('refresh').addEventListener('click', refresh);
el('usage-window').addEventListener('change', renderUsage);
refresh();
setInterval(refresh, 5000);
