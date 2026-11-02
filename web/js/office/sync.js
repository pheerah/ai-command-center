// Office module: sync (split out of office_game.js; behaviour unchanged).
(function() {
  'use strict';
  const K = (window.OfficeKit = window.OfficeKit || {});
  const { characters, miaWaypoints, SECRETARY_PERSONAS, secretaryIds, photos } = K.config;

  function syncSecretaries(projects, tasks) {
    const ids = projects.map(p => p.id);
    const wanted = new Set(ids.map(id => 'sec_' + id));

    for (const key of secretaryIds()) {
      if (!wanted.has(key)) {
        K.modal.clearSelectionIf(characters[key]);
        delete characters[key];
      }
    }

    const n = ids.length;
    const spacing = n > 1 ? Math.min(0.11, 0.34 / (n - 1)) : 0;
    const startX = n > 1 ? 0.10 : 0.26;

    ids.forEach((projectId, i) => {
      const key = 'sec_' + projectId;
      const x = startX + i * spacing;
      let char = characters[key];
      if (!char) {
        const pr = SECRETARY_PERSONAS[i % SECRETARY_PERSONAS.length];
        char = characters[key] = {
          id: key,
          project: projectId,
          name: `เลขาฯ ${pr.first} (${projectId})`,
          role: 'Chief Project Secretary',
          badge: `📁 ${pr.en} (${projectId})`,
          photoUrl: pr.url,
          photoImg: photos[pr.photo],
          zone: 'SECRETARY ROW',
          y: 0.20,
          baseY: 0.20,
          state: 'sitting',
          hairColor: pr.hair,
          hairStyle: 'long',
          dressColor: '#ffffff',
          skirtColor: pr.skirt,
          skinTone: pr.skin,
          glasses: !!pr.glasses,
          speech: `สวัสดีค่ะท่าน Director~ โปรเจกต์ ${projectId} ให้${pr.first}ช่วยดูแลเรื่องไหนดีคะ? 💕`,
          active: false,
          dialogues: [
            `สวัสดีค่ะท่าน Director~ โปรเจกต์ ${projectId} ให้${pr.first}ช่วยดูแลเรื่องไหนดีคะ? 💕`,
            `งานใน ${projectId} ${pr.first}ช่วยกำกับดูแลใกล้ชิดเลยค่ะ สั่งงานผ่าน${pr.first}ได้เลยนะคะ ✨`,
            `${pr.first}สแตนด์บายรอรับคำสั่งใหม่ของโปรเจกต์ ${projectId} เสมอค่ะ 💋`
          ]
        };
      }
      char.x = char.baseX = x;
      char.active = tasks.some(t => t.project_id === projectId && t.status === 'running');
    });
  }

  function updateGameState() {
    const snap = window.snapshot;
    if (!snap) return;

    const sessions = snap.sessions || [];
    const tasks = snap.tasks || [];

    const workingCounter = document.getElementById('game-working-counter');
    if (workingCounter) {
      workingCounter.textContent = `👩‍💻 กำลังทำงาน: ${sessions.length} / 3 ตัว`;
    }

    // 1. One Secretary Desk per project
    syncSecretaries(snap.projects || [], tasks);

    // 2. Sync AI Core Providers (Codex, Claude, Gemini)
    const codexSession = sessions.find(s => s.provider === 'codex');
    characters.ai_codex.active = !!codexSession;
    characters.ai_codex.typing = !!codexSession;

    const claudeSession = sessions.find(s => s.provider === 'claude');
    characters.ai_claude.active = !!claudeSession;
    characters.ai_claude.typing = !!claudeSession;

    const googleSession = sessions.find(s => s.provider === 'google');
    characters.ai_gemini.active = !!googleSession;
    characters.ai_gemini.typing = !!googleSession;

    // 3. Stage-Based Dynamic Workstations
    // Lead Zone (Analysis/Planning)
    const planningTask = tasks.find(t => t.status === 'queued' || (t.plan && !t.provider));
    characters.worker_lead.active = !!planningTask;

    // Dev Zone (Coding/Implementation)
    const implSession = sessions.find(s => s.role === 'implementation');
    characters.worker_dev.active = !!implSession;
    characters.worker_dev.typing = !!implSession;
    if (implSession) {
      const t = tasks.find(x => x.id === implSession.task_id);
      if (t) characters.worker_dev.speech = `กำลัง Dev โค้ด [${t.project_id}] ${t.title.slice(0, 24)}... 💻⚡`;
    }

    // QA Zone (Testing)
    const qaTask = tasks.find(t => t.status === 'running' && t.title.toLowerCase().includes('qa'));
    characters.worker_qa.active = !!qaTask || (!!implSession && implSession.provider === 'google');
    characters.worker_qa.typing = !!qaTask;

    // Review Zone (Independent Code Review)
    const reviewSession = sessions.find(s => s.role === 'review');
    characters.worker_review.active = !!reviewSession;
    characters.worker_review.typing = !!reviewSession;
    if (reviewSession) {
      const t = tasks.find(x => x.id === reviewSession.task_id);
      if (t) characters.worker_review.speech = `กำลังรัน Review และ Quality Gate สำหรับ [${t?.project_id || ''}]... 🛡️`;
    }

    // Ops Room: driven by queue state
    const byStatus = (st) => tasks.filter(t => st.includes(t.status));
    const queued = byStatus(['queued']);
    const retrying = byStatus(['retry_wait']);
    const blocked = byStatus(['blocked']);
    const awaiting = byStatus(['ready_for_human_approval']);

    characters.ops_planner.active = queued.length > 0;
    characters.ops_planner.typing = queued.length > 0;
    if (queued.length) characters.ops_planner.speech = `กำลังวางแผนงานที่รออยู่ ${queued.length} งาน เช่น [${queued[0].project_id}] ${queued[0].title.slice(0, 22)}... 🧭`;

    const routing = queued.length + retrying.length;
    characters.ops_router.active = routing > 0 || sessions.length > 0;
    characters.ops_router.typing = routing > 0;
    if (sessions.length) characters.ops_router.speech = `ตอนนี้กระจายงานให้ AI ${sessions.length} ตัวที่กำลังทำงานอยู่ค่ะ 🔀`;

    const stuck = retrying.length + blocked.length;
    characters.ops_recovery.active = stuck > 0;
    characters.ops_recovery.typing = stuck > 0;
    if (stuck) characters.ops_recovery.speech = `กำลังดูแลงานค้าง ${stuck} งาน (retry ${retrying.length} / blocked ${blocked.length}) ค่ะ 🛟`;

    characters.ops_reporter.active = awaiting.length > 0;
    characters.ops_reporter.typing = awaiting.length > 0;
    characters.ops_reporter.speech = awaiting.length
      ? `สรุปแล้วค่ะ มี ${awaiting.length} งานรอท่าน Director อนุมัติ 📊`
      : `งานทั้งหมด ${tasks.length} งาน ตอนนี้ไม่มีงานรออนุมัติค่ะ 📊`;

    updateDoingLabels(sessions, tasks);
    refreshEnergy();
    renderSchedulerChip(snap.service);

    // Update Courier Maid Mia Movement
    updateBotMovement(characters.mia, miaWaypoints, 0.0016);
  }

  function renderSchedulerChip(service) {
    const chip = document.getElementById('game-scheduler-chip');
    if (!chip) return;
    const running = !!service && service.running === true;
    chip.textContent = running ? 'SCHEDULER · ทำงานอยู่' : 'SCHEDULER · หยุดอยู่';
    chip.classList.toggle('stopped', !running);
  }

  // SYSTEM ENERGY bar: the lowest remaining quota window across providers (real data from /api/quota)
  let lastQuotaFetch = 0;

  function lowestQuotaPercent(quota) {
    const tightest = (windows) => {
      const pct = windows.filter(w => w && typeof w.remaining_percent === 'number').map(w => w.remaining_percent);
      return pct.length ? Math.min(...pct) : null;
    };
    const perProvider = [];
    for (const reading of Object.values(quota || {})) {
      if (!reading) continue;
      // Model groups are alternatives: a provider is as usable as its best group (same rule as the backend).
      const value = reading.groups
        ? Math.max(-1, ...Object.values(reading.groups).map(g => tightest([g.five_hour, g.weekly])).filter(v => v !== null))
        : tightest([reading.five_hour, reading.weekly]);
      if (value !== null && value >= 0) perProvider.push(value);
    }
    return perProvider.length ? Math.min(...perProvider) : null;
  }

  function renderEnergy(percent) {
    const fill = document.getElementById('game-energy-fill');
    const val = document.getElementById('game-energy-val');
    if (fill) fill.style.width = (percent === null ? 0 : Math.max(0, Math.min(100, percent))) + '%';
    if (val) val.textContent = percent === null ? 'ไม่ทราบโควตา' : `${Math.round(percent)}% USABLE`;
  }

  function refreshEnergy() {
    if (Date.now() - lastQuotaFetch < 30000) return;
    lastQuotaFetch = Date.now();
    fetch('/api/quota')
      .then(res => res.json())
      .then(quota => renderEnergy(lowestQuotaPercent(quota)))
      .catch(() => renderEnergy(null));
  }

  // Short "what is she doing right now" text shown under each name pill
  function updateDoingLabels(sessions, tasks) {
    const taskOf = (sess) => sess && tasks.find(x => x.id === sess.task_id);
    const set = (id, text) => { if (characters[id]) characters[id].doing = text || ''; };

    for (const id of secretaryIds()) {
      const c = characters[id];
      const mine = tasks.filter(t => t.project_id === c.project);
      const running = mine.find(t => t.status === 'running');
      const waiting = mine.filter(t => t.status === 'ready_for_human_approval');
      const queued = mine.filter(t => t.status === 'queued');
      c.doing = running ? `กำลังรัน: ${running.title}`
        : waiting.length ? `รออนุมัติ ${waiting.length} งาน`
        : queued.length ? `คิวรอ ${queued.length} งาน`
        : '';
    }

    for (const [id, provider] of [['ai_codex', 'codex'], ['ai_claude', 'claude'], ['ai_gemini', 'google']]) {
      const t = taskOf(sessions.find(x => x.provider === provider));
      set(id, t ? `ทำ: ${t.title}` : '');
    }

    const impl = taskOf(sessions.find(x => x.role === 'implementation'));
    const rev = taskOf(sessions.find(x => x.role === 'review'));
    const queued = tasks.filter(t => t.status === 'queued');
    const qa = tasks.find(t => t.status === 'running' && (t.title || '').toLowerCase().includes('qa'));
    set('worker_lead', queued.length ? `วางแผน: ${queued[0].title}` : '');
    set('worker_dev', impl ? `เขียนโค้ด: ${impl.title}` : '');
    set('worker_qa', qa ? `เทสต์: ${qa.title}` : '');
    set('worker_review', rev ? `รีวิว: ${rev.title}` : '');

    const retrying = tasks.filter(t => t.status === 'retry_wait');
    const blocked = tasks.filter(t => t.status === 'blocked');
    const awaiting = tasks.filter(t => t.status === 'ready_for_human_approval');
    set('ops_planner', queued.length ? `แตกแผน ${queued.length} งาน` : '');
    set('ops_router', (queued.length + retrying.length) ? `จัด AI ให้ ${queued.length + retrying.length} งาน` : '');
    set('ops_recovery', (retrying.length + blocked.length) ? `กู้งานค้าง ${retrying.length + blocked.length}` : '');
    set('ops_reporter', awaiting.length ? `สรุปรออนุมัติ ${awaiting.length}` : '');
  }

  function updateBotMovement(bot, waypoints, speed) {
    if (!waypoints || !waypoints.length) return;
    const wp = waypoints[bot.waypointIndex];
    const dx = wp.x - bot.x;
    const dy = wp.y - bot.y;
    const dist = Math.hypot(dx, dy);

    if (dist < 0.015) {
      if (!bot.waitCount) bot.waitCount = wp.wait;
      bot.waitCount--;
      if (wp.speech) bot.speech = wp.speech;
      if (bot.waitCount <= 0) {
        bot.waitCount = 0;
        bot.waypointIndex = (bot.waypointIndex + 1) % waypoints.length;
      }
    } else {
      bot.x += (dx / dist) * speed;
      bot.y += (dy / dist) * speed;
      bot.facingRight = dx > 0;
    }
  }

  // ==============================================================================
  // RENDERING DEPARTMENT-ZONED OFFICE ENVIRONMENT
  // ==============================================================================

  K.sync = { updateGameState };
})();
