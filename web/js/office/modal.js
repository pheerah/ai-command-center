// Office module: modal (split out of office_game.js; behaviour unchanged).
(function() {
  'use strict';
  const K = (window.OfficeKit = window.OfficeKit || {});

  let selectedEntity = null;

  // Pseudo-3D portrait in the modal: tilts toward the pointer, sways when idle,
  // and shifts the photo/sheen for a parallax depth feel.
  const portraitMotion = { running: false, hover: false, tx: 0, ty: 0, cx: 0, cy: 0 };

  function setupPortraitMotion() {
    const frame = document.querySelector('.modal-big-photo-frame');
    if (!frame) return;
    frame.addEventListener('pointermove', (e) => {
      const r = frame.getBoundingClientRect();
      portraitMotion.hover = true;
      portraitMotion.tx = ((e.clientX - r.left) / r.width - 0.5) * 2;
      portraitMotion.ty = ((e.clientY - r.top) / r.height - 0.5) * 2;
    });
    frame.addEventListener('pointerleave', () => { portraitMotion.hover = false; });
  }

  function startPortraitMotion() {
    if (portraitMotion.running) return;
    const frame = document.querySelector('.modal-big-photo-frame');
    if (!frame) return;
    portraitMotion.running = true;
    const step = () => {
      if (!isModalOpen()) { portraitMotion.running = false; return; }
      const t = performance.now() / 1000;
      const m = portraitMotion;
      const tx = m.hover ? m.tx : Math.sin(t * 0.7) * 0.45;
      const ty = m.hover ? m.ty : Math.cos(t * 0.5) * 0.25;
      m.cx += (tx - m.cx) * 0.08;
      m.cy += (ty - m.cy) * 0.08;
      const breathe = Math.sin(t * 1.6);
      frame.style.setProperty('--ry', `${(m.cx * 9).toFixed(2)}deg`);
      frame.style.setProperty('--rx', `${(-m.cy * 7).toFixed(2)}deg`);
      frame.style.setProperty('--px', `${(-m.cx * 10).toFixed(2)}px`);
      frame.style.setProperty('--py', `${(-m.cy * 8 + breathe * 2).toFixed(2)}px`);
      frame.style.setProperty('--ps', (1.09 + breathe * 0.012).toFixed(4));
      frame.style.setProperty('--mx', `${((m.cx * 0.5 + 0.5) * 100).toFixed(1)}%`);
      frame.style.setProperty('--my', `${((m.cy * 0.5 + 0.5) * 100).toFixed(1)}%`);
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function isModalOpen() {
    const overlay = document.getElementById('agent-modal-overlay');
    return !!overlay && !overlay.hidden;
  }

  function closeAgentModal() {
    const overlay = document.getElementById('agent-modal-overlay');
    if (overlay) overlay.hidden = true;
  }

  function selectCharacter(char) {
    selectedEntity = char;

    const overlay = document.getElementById('agent-modal-overlay');
    const photoEl = document.getElementById('modal-agent-photo');
    const badgeEl = document.getElementById('modal-agent-badge');
    const projChip = document.getElementById('modal-project-chip');
    const nameEl = document.getElementById('modal-agent-name');
    const roleEl = document.getElementById('modal-agent-role');
    const statusEl = document.getElementById('modal-agent-status-pill');
    const quoteEl = document.getElementById('modal-quote-text');
    const summaryEl = document.getElementById('modal-task-summary');
    const chipsEl = document.getElementById('modal-task-chips-row');
    const approveZone = document.getElementById('modal-approve-zone');
    const btnApprove = document.getElementById('modal-btn-approve');
    const btnTerminal = document.getElementById('modal-btn-terminal');
    const mainProjSelect = document.getElementById('dispatch-project');

    if (photoEl) photoEl.src = char.photoUrl || '/assets/sec_white_blouse.png';
    if (badgeEl) badgeEl.textContent = char.badge;
    if (nameEl) nameEl.textContent = char.name;

    if (char.project) {
      if (projChip) projChip.textContent = `📁 ${char.project}`;
      if (roleEl) roleEl.textContent = `${char.badge || 'Agent'} · ${char.project}`;
      if (mainProjSelect) mainProjSelect.value = char.project;
    } else {
      if (projChip) projChip.textContent = `🏢 แผนก: ${char.zone || 'ส่วนกลาง'}`;
      if (roleEl) roleEl.textContent = char.zone || 'ส่วนกลาง';
    }

    const chatBox = document.getElementById('secretary-chat');
    if (chatBox) {
      chatBox.hidden = !char.project;
      if (char.project && window.SecretaryChat) window.SecretaryChat.mount(chatBox, char.project);
    }

    if (statusEl) {
      statusEl.textContent = char.active ? '🟢 กำลังปฏิบัติหน้าที่อย่างตั้งใจ' : '🔵 พร้อมรับคำสั่งใหม่ (Idle)';
      statusEl.classList.toggle('idle', !char.active);
    }
    if (quoteEl) quoteEl.textContent = `"${char.speech}"`;

    const snap = window.snapshot;
    const allTasks = snap?.tasks || [];
    const projTasks = char.project ? allTasks.filter(t => t.project_id === char.project) : allTasks;

    const waiting = projTasks.filter(t => t.status === 'ready_for_human_approval');
    const running = projTasks.filter(t => t.status === 'running');

    let currentTaskId = null;
    let summary;

    if (waiting.length > 0) {
      currentTaskId = waiting[0].id;
      summary = `🎉 มีงาน [${waiting[0].project_id}] ${waiting[0].title} ผ่านการตรวจสอบครบถ้วนแล้ว พร้อมให้ท่าน Director กดอนุมัติค่ะ!`;
    } else if (running.length > 0) {
      currentTaskId = running[0].id;
      summary = `กำลังลุยงาน [${running[0].project_id}] ${running[0].title} ให้ท่าน Director อยู่นะคะ ✨`;
    } else {
      summary = char.project
        ? `โปรเจกต์ ${char.project} พร้อมรับคำสั่งใหม่จากท่าน Director ทันทีค่ะ 💕`
        : 'ทุกระบบพร้อมรับคำสั่งใหม่จากท่าน Director ทันที 💕';
    }
    if (summaryEl) summaryEl.textContent = summary;

    if (chipsEl) {
      const counts = {};
      projTasks.forEach(t => { counts[t.status] = (counts[t.status] || 0) + 1; });
      chipsEl.replaceChildren(...Object.entries(counts).map(([status, n]) => {
        const chip = document.createElement('span');
        chip.className = 'modal-task-chip';
        chip.textContent = `${window.StatusLabels.label(status)}: ${n}`;
        return chip;
      }));
    }

    if (approveZone) approveZone.hidden = waiting.length === 0;
    if (btnApprove && waiting.length > 0) {
      btnApprove.textContent = `✓ กดอนุมัติงาน [${waiting[0].project_id}] ทันที 💕`;
      btnApprove.onclick = () => {
        if (window.approveTask) window.approveTask(currentTaskId);
      };
    }

    if (btnTerminal) {
      btnTerminal.hidden = !currentTaskId;
      btnTerminal.onclick = () => {
        closeAgentModal();
        if (window.details) window.details(currentTaskId);
      };
    }

    if (overlay) {
      overlay.hidden = false;
      startPortraitMotion();
      const chatInput = document.getElementById('chat-input');
      if (chatInput && chatBox && !chatBox.hidden) chatInput.focus();
    }
  }

  K.modal = {
    isOpen: isModalOpen,
    close: closeAgentModal,
    select: selectCharacter,
    setupPortraitMotion,
    selected() { return selectedEntity; },
    clearSelectionIf(char) { if (selectedEntity === char) { selectedEntity = null; closeAgentModal(); } },
  };
})();
