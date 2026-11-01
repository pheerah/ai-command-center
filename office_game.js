// ==============================================================================
// AI COMMAND CENTER - 2D VIRTUAL AGENT OFFICE (Department & Stage-Zoned Edition)
// Featuring 8 Functional Zones: Secretary Row, AI Hub, Lead, Dev, QA, Review, Approval, Ops Room
// ==============================================================================

(function() {
  'use strict';

  let canvas, ctx;
  let animFrameId = null;
  let gameContainer = null;
  let width = 0, height = 0;
  let dpr = 1;

  // Sound Engine
  let audioCtx = null;
  let soundEnabled = true;

  function playCuteSound(freq = 587, type = 'sine', duration = 0.12) {
    if (!soundEnabled) return;
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(freq * 1.5, audioCtx.currentTime + duration);
      gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + duration);
    } catch {}
  }

  // Pre-load Sexy Secretary Real Photos
  const photos = {
    whiteBlouse: new Image(),
    purpleHair: new Image(),
    blondeSuit: new Image(),
    darkGlasses: new Image(),
    doubleSlit: new Image(),
    trioCouch: new Image()
  };
  photos.whiteBlouse.src = '/assets/sec_white_blouse.png';
  photos.purpleHair.src = '/assets/sec_purple_hair.png';
  photos.blondeSuit.src = '/assets/sec_blonde_suit.png';
  photos.darkGlasses.src = '/assets/sec_dark_glasses.jpg';
  photos.doubleSlit.src = '/assets/sec_double_slit.png';
  photos.trioCouch.src = '/assets/sec_trio_couch.jpg';

  // Base Characters List (Dynamic positions & roles updated from snapshot)
  const characters = {
    // --- 1. SECRETARY ROW: one per project, built by syncSecretaries() ---

    // --- 2. 3 CORE AI PROVIDER HUBS (Codex, Claude, Gemini) ---
    ai_codex: {
      id: 'ai_codex',
      project: '',
      name: 'โคเด็กซ์ (ChatGPT Codex)',
      role: 'Core AI Provider 1',
      badge: '🟢 Codex (GPT-6)',
      photoUrl: '/assets/sec_dark_glasses.jpg',
      photoImg: photos.darkGlasses,
      zone: 'AI HUB',
      x: 0.12, y: 0.46,
      baseX: 0.12, baseY: 0.46,
      state: 'sitting',
      hairColor: '#10b981',
      hairStyle: 'twintail',
      dressColor: '#064e3b',
      skirtColor: '#0f172a',
      skinTone: '#fed7aa',
      speech: 'ChatGPT Codex พร้อมประมวลผลคำสั่ง Logic และ Algorithm สปีดสูงสุดค่ะ! ⚡',
      active: false,
      dialogues: [
        'ChatGPT Codex สแตนด์บายพร้อมรับงาน Implementation และ Architecture ค่ะ ⚡',
        'โมเดล GPT-6 Sol ทำงานแม่นยำ ไร้ข้อผิดพลาด!'
      ]
    },
    ai_claude: {
      id: 'ai_claude',
      project: '',
      name: 'โคลด์ (Claude Code)',
      role: 'Core AI Provider 2',
      badge: '🟣 Claude (Sonnet/Opus)',
      photoUrl: '/assets/sec_purple_hair.png',
      photoImg: photos.purpleHair,
      zone: 'AI HUB',
      x: 0.26, y: 0.46,
      baseX: 0.26, baseY: 0.46,
      state: 'sitting',
      hairColor: '#8b5cf6',
      hairStyle: 'long',
      dressColor: '#4c1d95',
      skirtColor: '#18181b',
      skinTone: '#fde68a',
      glasses: true,
      speech: 'Claude Code พร้อมรันสถาปัตยกรรมโค้ดและการรีวิวระดับพรีเมียมค่ะ 💜',
      active: false,
      dialogues: [
        'โคลด์เขียนโค้ดอย่างรอบคอบและปลอดภัยตามมาตรฐานสากลค่ะ 💜',
        'งานทุกชิ้นผ่านการคิดวิเคราะห์อย่างเป็นระบบค่ะท่าน Director~'
      ]
    },
    ai_gemini: {
      id: 'ai_gemini',
      project: '',
      name: 'เจมินี่ (Google Gemini)',
      role: 'Core AI Provider 3',
      badge: '🔵 Gemini (Flash 3.8)',
      photoUrl: '/assets/sec_blonde_suit.png',
      photoImg: photos.blondeSuit,
      zone: 'AI HUB',
      x: 0.40, y: 0.46,
      baseX: 0.40, baseY: 0.46,
      state: 'sitting',
      hairColor: '#38bdf8',
      hairStyle: 'long',
      dressColor: '#0369a1',
      skirtColor: '#0f172a',
      skinTone: '#fed7aa',
      speech: 'Google Gemini สปีดความเร็วสูง พร้อมลุยงานด่วนและ QA ให้ทันทีค่ะ 💙',
      active: true,
      dialogues: [
        'เจมินี่กำลังดำเนินการเขียนโค้ดและรันงานให้ท่าน Director อยู่ค่ะ ✨',
        'ความเร็ว Flash Response ช่วยให้โปรเจกต์เสร็จไวขึ้นแน่นอนค่ะ!'
      ]
    },

    // --- 3. STAGE-BASED WORKSTATION SPECIALISTS ---
    worker_lead: {
      id: 'worker_lead',
      project: '',
      name: 'ลีดเดอร์ อาเรีย (Lead Architect)',
      role: 'Requirements & Architecture Lead',
      badge: '🧠 Lead (Plan)',
      photoUrl: '/assets/sec_dark_glasses.jpg',
      photoImg: photos.darkGlasses,
      zone: 'LEAD ZONE',
      x: 0.12, y: 0.76,
      baseX: 0.12, baseY: 0.76,
      state: 'sitting',
      hairColor: '#1e1b4b',
      hairStyle: 'long',
      dressColor: '#ffffff',
      skirtColor: '#18181b',
      skinTone: '#fed7aa',
      glasses: true,
      speech: 'กำลังวิเคราะห์ Requirement และวางแผน Implementation ให้ Zero-Waste ค่ะ 🧠',
      active: false,
      dialogues: [
        'กำลังย่อยโจทย์และทำ Test-Driven Plan ให้ทีม Dev ลุยต่อได้ราบรื่นค่ะ!',
        'การวางแผนที่ดี ช่วยลดบั๊กในโปรดักชันได้มากกว่า 90% ค่ะ ✨'
      ]
    },
    worker_dev: {
      id: 'worker_dev',
      project: 'spc-new-erp',
      name: 'เอมิรี่ (Dev Implementation)',
      role: 'Senior Full-Stack Developer',
      badge: '💻 Dev (Coding)',
      photoUrl: '/assets/sec_white_blouse.png',
      photoImg: photos.whiteBlouse,
      zone: 'DEV ZONE',
      x: 0.26, y: 0.76,
      baseX: 0.26, baseY: 0.76,
      state: 'sitting',
      hairColor: '#451a03',
      hairStyle: 'long',
      dressColor: '#ffffff',
      skirtColor: '#0f172a',
      skinTone: '#fed7aa',
      speech: 'กำลังเขียนโค้ดอย่างดุเดือด! สปีดเต็มพิกัดค่ะ 💻⚡',
      active: true,
      typing: true,
      dialogues: [
        'กำลัง Implement โค้ดในโปรเจกต์ให้อย่างรวดเร็วและแม่นยำค่ะ 💻',
        'ทุกฟังก์ชันถูกออกแบบให้ Clean Code อ่านง่าย บำรุงรักษาง่ายค่ะ!'
      ]
    },
    worker_qa: {
      id: 'worker_qa',
      project: 'spc-new-erp',
      name: 'แคลร์ (QA & Testing)',
      role: 'Quality Assurance Specialist',
      badge: '🔎 QA (Testing)',
      photoUrl: '/assets/sec_blonde_suit.png',
      photoImg: photos.blondeSuit,
      zone: 'QA ZONE',
      x: 0.40, y: 0.76,
      baseX: 0.40, baseY: 0.76,
      state: 'sitting',
      hairColor: '#eab308',
      hairStyle: 'long',
      dressColor: '#94a3b8',
      skirtColor: '#475569',
      skinTone: '#fed7aa',
      glasses: true,
      speech: 'กำลังรัน Unit & Integration Tests ตรวจสอบทุก Acceptance Criteria ค่ะ 🔎',
      active: true,
      typing: true,
      dialogues: [
        'รันเทสต์ผ่านหมดทุกข้อ! ไม่ปล่อยให้มีบั๊กหลุดรอดแน่นอนค่ะ 🔎',
        'Quality Gates เข้มงวด เพื่อความเสถียรสูงสุดของโปรเจกต์ค่ะ ✨'
      ]
    },
    worker_review: {
      id: 'worker_review',
      project: 'horoscope',
      name: 'วิเวียน (Independent Reviewer)',
      role: 'Independent Code Reviewer',
      badge: '🛡️ Review (Security & Gates)',
      photoUrl: '/assets/sec_double_slit.png',
      photoImg: photos.doubleSlit,
      zone: 'REVIEW ZONE',
      x: 0.54, y: 0.76,
      baseX: 0.54, baseY: 0.76,
      state: 'sitting',
      hairColor: '#581c87',
      hairStyle: 'long',
      dressColor: '#ffffff',
      skirtColor: '#0f172a',
      skinTone: '#fed7aa',
      speech: 'ตรวจสอบ Scoped Patch และความปลอดภัย ปราศจากบั๊กและช่องโหว่ 100% ค่ะ 🛡️',
      active: false,
      dialogues: [
        'ทำการตรวจสอบแบบสองฝ่าย (Cross-Review) ให้มั่นใจว่าโค้ดไม่มี Regression ค่ะ 🛡️',
        'เมื่อ Patch ผ่านการตรวจแล้ว วิเวียนจะส่งต่อให้ท่าน Director เซ็นอนุมัติทันทีค่ะ 💕'
      ]
    },

    // --- 4. COURIER & LOUNGE ---
    mia: {
      id: 'mia',
      project: '',
      name: 'น้องมีอา (Courier Maid)',
      role: 'Task Messenger & Coffee Maid',
      badge: '🎀 Mia (Courier)',
      photoUrl: '/assets/sec_white_blouse.png',
      photoImg: photos.whiteBlouse,
      zone: 'OFFICE FLOOR',
      x: 0.35, y: 0.50,
      waypointIndex: 0,
      waitCount: 0,
      state: 'walking',
      facingRight: true,
      hairColor: '#f43f5e',
      hairStyle: 'bunny',
      dressColor: '#1e293b',
      skirtColor: '#ffffff',
      skinTone: '#fed7aa',
      speech: 'มีอากำลังวิ่งส่งมอบ Patch และเอกสารระหว่างแผนกต่างๆ ค่ะ 💌',
      active: true,
      dialogues: [
        'มีอากำลังนำ Patch จาก Dev ส่งไปให้แผนก QA ตรวจค่ะ 💌',
        'เสิร์ฟกาแฟร้อนๆ ให้ท่าน Director และสาวๆ ทุกแผนกค่ะ ☕✨'
      ]
    },
    ops_planner: {
      id: 'ops_planner',
      project: '',
      name: 'พลอย (Planner)',
      role: 'Autonomous Supervisor & Planner',
      badge: '🧭 Planner (Supervisor)',
      photoUrl: '/assets/sec_double_slit.png',
      photoImg: photos.doubleSlit,
      zone: 'OPS ROOM',
      x: 0.74, y: 0.66,
      baseX: 0.74, baseY: 0.66,
      state: 'sitting',
      hairColor: '#0ea5e9',
      hairStyle: 'long',
      dressColor: '#e0f2fe',
      skirtColor: '#0f172a',
      skinTone: '#fed7aa',
      speech: 'พลอยแตกคำสั่งของท่าน Director เป็นแผนงานให้ทุกทีมทันทีค่ะ 🧭',
      active: false,
      dialogues: [
        'งานง่ายส่ง Fast Path งานซับซ้อนเรียก Council Path ให้เองค่ะ 🧭',
        'พิมพ์คำสั่งยาวๆ มาได้เลยค่ะ เดี๋ยวพลอยแตกเป็นขั้นตอนให้ ✨'
      ]
    },
    ops_router: {
      id: 'ops_router',
      project: '',
      name: 'รีน่า (Router)',
      role: 'AI Router & Model Selector',
      badge: '🔀 Router (Smart Routing)',
      photoUrl: '/assets/sec_dark_glasses.jpg',
      photoImg: photos.darkGlasses,
      zone: 'OPS ROOM',
      x: 0.88, y: 0.66,
      baseX: 0.88, baseY: 0.66,
      state: 'sitting',
      hairColor: '#f97316',
      hairStyle: 'twintail',
      dressColor: '#ffedd5',
      skirtColor: '#1c1917',
      skinTone: '#fed7aa',
      glasses: true,
      speech: 'รีน่าเลือก AI และระดับโมเดลที่เหมาะกับแต่ละงานให้ค่ะ 🔀',
      active: false,
      dialogues: [
        'งานนี้ควรไป Codex, Claude หรือ Gemini ให้รีน่าเลือกเองค่ะ 🔀',
        'ประหยัดโควตาและคุมคุณภาพไปพร้อมกัน ด้วยการจัดเส้นทางที่ฉลาดค่ะ ✨'
      ]
    },
    ops_recovery: {
      id: 'ops_recovery',
      project: '',
      name: 'ริสา (Recovery)',
      role: 'Recovery & On-call Engineer',
      badge: '🛟 Recovery (On-call)',
      photoUrl: '/assets/sec_blonde_suit.png',
      photoImg: photos.blondeSuit,
      zone: 'OPS ROOM',
      x: 0.74, y: 0.88,
      baseX: 0.74, baseY: 0.88,
      state: 'sitting',
      hairColor: '#ef4444',
      hairStyle: 'long',
      dressColor: '#fee2e2',
      skirtColor: '#1e293b',
      skinTone: '#fed7aa',
      speech: 'ริสาเฝ้างานที่ค้างและกู้ให้กลับมาวิ่งต่อค่ะ 🛟',
      active: false,
      dialogues: [
        'งานค้าง งานล่ม provider ล่ม ริสาจัดการ retry และย้ายให้เองค่ะ 🛟',
        'ไม่ต้องห่วงนะคะท่าน Director ริสาเฝ้าคิวอยู่ตลอดค่ะ ✨'
      ]
    },
    ops_reporter: {
      id: 'ops_reporter',
      project: '',
      name: 'รายา (Reporter)',
      role: 'Status Reporter',
      badge: '📊 Reporter (Status & Usage)',
      photoUrl: '/assets/sec_purple_hair.png',
      photoImg: photos.purpleHair,
      zone: 'OPS ROOM',
      x: 0.88, y: 0.88,
      baseX: 0.88, baseY: 0.88,
      state: 'sitting',
      hairColor: '#a855f7',
      hairStyle: 'long',
      dressColor: '#f3e8ff',
      skirtColor: '#0f172a',
      skinTone: '#fde68a',
      glasses: true,
      speech: 'รายาสรุปสถานะงานและการใช้ token ให้ท่าน Director ค่ะ 📊',
      active: false,
      dialogues: [
        'รายาสรุปให้แล้วค่ะ ว่ามีงานรออนุมัติและใช้โควตาไปเท่าไหร่ 📊',
        'อยากรู้ภาพรวมโปรเจกต์ไหน ถามรายาได้เลยค่ะ ✨'
      ]
    }
  };

  // Particles
  const particles = [];
  function addParticle(x, y, text, color, vx = 0, vy = -0.7) {
    if (particles.length > 50) return;
    particles.push({
      x, y, text, color, vx, vy,
      alpha: 1,
      decay: 0.015 + Math.random() * 0.01
    });
  }

  // Active Walking Waypoints for Mia (Messenger Courier running between all zones)
  const miaWaypoints = [
    { x: 0.26, y: 0.26, wait: 50, speech: 'รับโจทย์ใหม่จากเลขาฯ หลินหลิน [spc-new-erp] 💌' },
    { x: 0.12, y: 0.68, wait: 50, speech: 'ส่งต่อไปยัง แผนก Lead Architect เพื่อวางแผน 🧠' },
    { x: 0.26, y: 0.68, wait: 50, speech: 'ส่งต่อให้ แผนก Dev เริ่ม Implement โค้ด! 💻' },
    { x: 0.40, y: 0.68, wait: 50, speech: 'นำ Patch ส่งให้ แผนก QA ตรวจสอบการทำงาน 🔎' },
    { x: 0.54, y: 0.68, wait: 50, speech: 'ส่งเข้า แผนก Review เพื่อตรวจความปลอดภัย 🛡️' },
    { x: 0.82, y: 0.26, wait: 50, speech: 'ส่งขึ้นโต๊ะท่าน Director รอเซ็นอนุมัติ! 👑' }
  ];

  let tick = 0;
  let hoveredEntity = null;
  let selectedEntity = null;
  let mouseX = 0, mouseY = 0;

  function initGame() {
    gameContainer = document.getElementById('office-game-container');
    if (!gameContainer) return;

    const canvas3d = document.getElementById('office-game-3d-canvas');
    if (canvas3d) canvas3d.remove();

    canvas = document.getElementById('office-game-canvas');
    if (!canvas) {
      canvas = document.createElement('canvas');
      canvas.id = 'office-game-canvas';
      gameContainer.prepend(canvas);
    }
    canvas.style.display = 'block';
    ctx = canvas.getContext('2d');

    setupUIButtons();
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('click', onCanvasClick);

    if (!animFrameId) {
      animFrameId = requestAnimationFrame(gameLoop);
    }

    console.log('🏢 Department-Zoned AI Virtual Office Initialized Successfully!');
  }

  function setupUIButtons() {
    const fsBtn = document.getElementById('btn-fullscreen');
    const soundBtn = document.getElementById('btn-game-sound');
    const workspace = document.querySelector('.pixel-office-workspace');

    if (soundBtn) {
      soundBtn.onclick = () => {
        soundEnabled = !soundEnabled;
        soundBtn.textContent = soundEnabled ? '🔊 เสียงเปิด' : '🔇 เสียงปิด';
        soundBtn.classList.toggle('active', soundEnabled);
        if (soundEnabled) playCuteSound(659, 'triangle', 0.15);
      };
    }

    if (fsBtn && workspace) {
      const toggleFullscreen = () => {
        if (!document.fullscreenElement && !workspace.classList.contains('fake-fullscreen')) {
          if (workspace.requestFullscreen) {
            workspace.requestFullscreen().catch(() => {
              workspace.classList.add('fake-fullscreen');
              fsBtn.innerHTML = '🗗 ย่อหน้าจอ';
              resizeCanvas();
            });
          } else {
            workspace.classList.add('fake-fullscreen');
            fsBtn.innerHTML = '🗗 ย่อหน้าจอ';
            resizeCanvas();
          }
        } else {
          if (document.fullscreenElement) {
            document.exitFullscreen().catch(() => {});
          }
          workspace.classList.remove('fake-fullscreen');
          fsBtn.innerHTML = '⛶ ขยายเต็มจอ';
          resizeCanvas();
        }
      };

      fsBtn.onclick = toggleFullscreen;

      document.addEventListener('fullscreenchange', () => {
        const isFs = !!document.fullscreenElement;
        fsBtn.innerHTML = isFs ? '🗗 ย่อหน้าจอ' : '⛶ ขยายเต็มจอ';
        setTimeout(resizeCanvas, 100);
      });

      window.addEventListener('keydown', (e) => {
        if ((e.key === 'f' || e.key === 'F') && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
          e.preventDefault();
          toggleFullscreen();
        }
        if (e.key === 'Escape' && isModalOpen()) {
          closeAgentModal();
          return;
        }
        if (e.key === 'Escape' && workspace.classList.contains('fake-fullscreen')) {
          workspace.classList.remove('fake-fullscreen');
          fsBtn.innerHTML = '⛶ ขยายเต็มจอ';
          resizeCanvas();
        }
      });
    }

    // Agent modal controls
    setupPortraitMotion();
    const overlay = document.getElementById('agent-modal-overlay');
    const closeBtn = document.getElementById('agent-modal-close');
    if (closeBtn) closeBtn.onclick = closeAgentModal;
    if (overlay) {
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeAgentModal();
      });
    }

    // Modal Command Input
    const cmdInput = document.getElementById('modal-command-input');
    const cmdSend = document.getElementById('modal-command-send');
    if (cmdSend && cmdInput) {
      const handleSend = () => {
        const prompt = cmdInput.value.trim();
        if (!prompt || !selectedEntity) return;
        cmdInput.value = '';

        const proj = selectedEntity.project || document.getElementById('dispatch-project')?.value || 'spc-new-erp';

        playCuteSound(880, 'triangle', 0.2);
        for (let i = 0; i < 6; i++) {
          addParticle(
            selectedEntity.x * width + (Math.random() * 40 - 20),
            selectedEntity.y * height - 80,
            '🚀', '#ec4899',
            Math.random() * 1 - 0.5,
            -1.5 - Math.random() * 0.5
          );
        }

        const quoteEl = document.getElementById('modal-quote-text');
        if (quoteEl) {
          quoteEl.textContent = `"${selectedEntity.name.split(' ')[0]} รับคำสั่งงานโปรเจกต์ [${proj}] เรียบร้อยค่ะ: '${prompt}' กำลังส่งให้ AI เริ่มลุยทันทีนะคะ 💕"`;
        }

        fetch('/api/dispatch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: proj, prompt: prompt })
        })
        .then(res => res.json())
        .then(data => {
          if (data.ok) {
            playCuteSound(1046, 'sine', 0.25);
            if (window.refresh) window.refresh();
          }
        })
        .catch(err => console.error('Dispatch error:', err));
      };

      cmdSend.onclick = handleSend;
      cmdInput.onkeydown = (e) => {
        if (e.key === 'Enter') handleSend();
      };
    }
  }

  function resizeCanvas() {
    if (!gameContainer || !canvas) return;
    const rect = gameContainer.getBoundingClientRect();
    width = rect.width || 800;
    height = rect.height || 540;
    dpr = window.devicePixelRatio || 1;

    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
  }

  function onMouseMove(e) {
    const rect = canvas.getBoundingClientRect();
    mouseX = e.clientX - rect.left;
    mouseY = e.clientY - rect.top;

    hoveredEntity = null;
    for (const char of Object.values(characters)) {
      const cx = char.x * width;
      const cy = char.y * height;
      const distBody = Math.hypot(mouseX - cx, mouseY - cy);
      const distBust = Math.hypot(mouseX - cx, mouseY - (cy - 40));
      if (distBody < 30 || distBust < 42) {
        hoveredEntity = char;
        canvas.style.cursor = 'pointer';
        return;
      }
    }
    canvas.style.cursor = 'default';
  }

  function onCanvasClick() {
    if (hoveredEntity) {
      playCuteSound(784, 'triangle', 0.15);
      if (hoveredEntity.dialogues && hoveredEntity.dialogues.length) {
        const rand = hoveredEntity.dialogues[Math.floor(Math.random() * hoveredEntity.dialogues.length)];
        hoveredEntity.speech = rand;
      }
      for (let i = 0; i < 5; i++) {
        addParticle(
          hoveredEntity.x * width + (Math.random() * 30 - 15),
          hoveredEntity.y * height - 80,
          '💖', '#f43f5e',
          Math.random() * 0.8 - 0.4,
          -1.2 - Math.random() * 0.5
        );
      }
      selectCharacter(hoveredEntity);
    }
  }

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
    const cmdInput = document.getElementById('modal-command-input');
    const mainProjSelect = document.getElementById('dispatch-project');

    if (photoEl) photoEl.src = char.photoUrl || '/assets/sec_white_blouse.png';
    if (badgeEl) badgeEl.textContent = char.badge;
    if (nameEl) nameEl.textContent = char.name;

    if (char.project) {
      if (projChip) projChip.textContent = `📁 ${char.project}`;
      if (roleEl) roleEl.textContent = `${char.badge || 'Agent'} · ${char.project}`;
      if (mainProjSelect) mainProjSelect.value = char.project;
      if (cmdInput) cmdInput.placeholder = `สั่งงาน [${char.project}] ผ่าน${char.name.split(' ')[0]}...`;
    } else {
      if (projChip) projChip.textContent = `🏢 แผนก: ${char.zone || 'ส่วนกลาง'}`;
      if (roleEl) roleEl.textContent = char.zone || 'ส่วนกลาง';
      if (cmdInput) cmdInput.placeholder = 'สั่งงานส่วนกลาง หรือ ทักทายสาวๆ...';
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
        chip.textContent = `${status}: ${n}`;
        return chip;
      }));
    }

    if (approveZone) approveZone.style.display = waiting.length > 0 ? 'block' : 'none';
    if (btnApprove && waiting.length > 0) {
      btnApprove.textContent = `✓ กดอนุมัติงาน [${waiting[0].project_id}] ทันที 💕`;
      btnApprove.onclick = () => {
        if (window.approveTask) window.approveTask(currentTaskId);
      };
    }

    if (btnTerminal) {
      btnTerminal.style.display = currentTaskId ? '' : 'none';
      btnTerminal.onclick = () => {
        closeAgentModal();
        if (window.details) window.details(currentTaskId);
      };
    }

    if (overlay) {
      overlay.hidden = false;
      startPortraitMotion();
      if (cmdInput) cmdInput.focus();
    }
  }

  const SECRETARY_PERSONAS = [
    { first: 'หลินหลิน', en: 'Linlin', photo: 'whiteBlouse', url: '/assets/sec_white_blouse.png', hair: '#451a03', skirt: '#f8fafc', skin: '#fed7aa' },
    { first: 'ยูกิ', en: 'Yuki', photo: 'purpleHair', url: '/assets/sec_purple_hair.png', hair: '#7c3aed', skirt: '#0f172a', skin: '#fde68a', glasses: true },
    { first: 'เซเรน่า', en: 'Serena', photo: 'doubleSlit', url: '/assets/sec_double_slit.png', hair: '#581c87', skirt: '#0f172a', skin: '#fed7aa' },
    { first: 'มิลลี่', en: 'Milly', photo: 'blondeSuit', url: '/assets/sec_blonde_suit.png', hair: '#ca8a04', skirt: '#1e293b', skin: '#fed7aa' },
    { first: 'ซาร่า', en: 'Sara', photo: 'darkGlasses', url: '/assets/sec_dark_glasses.jpg', hair: '#0f172a', skirt: '#f8fafc', skin: '#fed7aa', glasses: true }
  ];

  function secretaryIds() {
    return Object.keys(characters).filter(id => id.startsWith('sec_'));
  }

  function syncSecretaries(projects, tasks) {
    const ids = projects.map(p => p.id);
    const wanted = new Set(ids.map(id => 'sec_' + id));

    for (const key of secretaryIds()) {
      if (!wanted.has(key)) {
        if (selectedEntity === characters[key]) {
          selectedEntity = null;
          closeAgentModal();
        }
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

    // Update Courier Maid Mia Movement
    updateBotMovement(characters.mia, miaWaypoints, 0.0016);
  }

  // Short "what is she doing right now" text shown under each name pill
  function updateDoingLabels(sessions, tasks) {
    const title = (t) => `${t.project_id ? '[' + t.project_id + '] ' : ''}${t.title || ''}`;
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

  function drawDepartmentZonedOffice() {
    // 1. Rich Warm Parquet Wood Floor
    const floorGrad = ctx.createLinearGradient(0, 0, 0, height);
    floorGrad.addColorStop(0, '#3e2316');
    floorGrad.addColorStop(0.5, '#2e190e');
    floorGrad.addColorStop(1, '#1e1008');
    ctx.fillStyle = floorGrad;
    ctx.fillRect(0, 0, width, height);

    // Diagonal/Parquet Wood Planks
    ctx.strokeStyle = 'rgba(15, 8, 4, 0.45)';
    ctx.lineWidth = 1.2;
    const plankSize = 42;
    for (let x = -height; x < width + height; x += plankSize) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x + height, height);
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(x + plankSize, 0);
      ctx.lineTo(x - height + plankSize, height);
      ctx.stroke();
    }

    // Top Panoramic Glass Wall
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, width, 24);
    ctx.fillStyle = '#475569';
    ctx.fillRect(0, 24, width, 3);

    // -------------------------------------------------------------
    // 2. THE 8 FUNCTIONAL ZONES WITH PROMINENT LABELS & NEON RUGS
    // -------------------------------------------------------------

    // ZONE 1: SECRETARY & PM ROW (Top Left)
    drawZoneRug(
      width * 0.04, height * 0.08, width * 0.44, height * 0.22,
      'rgba(236, 72, 153, 0.12)', '#ec4899', '👑 ZONE 1: SECRETARY & PM ROW (ตามจำนวน Project)'
    );

    // ZONE 2: AI CORE PROVIDER ROW (Middle Left)
    drawZoneRug(
      width * 0.04, height * 0.34, width * 0.44, height * 0.22,
      'rgba(59, 130, 246, 0.12)', '#3b82f6', '🤖 ZONE 2: AI AGENT HUB (ChatGPT · Claude · Gemini)'
    );

    // ZONE 3-6: STAGE-BASED WORKSTATIONS (Bottom Row)
    // Zone 3: Lead (Analysis & Plan)
    drawZoneRug(
      width * 0.04, height * 0.62, width * 0.13, height * 0.32,
      'rgba(168, 85, 247, 0.15)', '#a855f7', '🧠 3. LEAD (Plan)'
    );
    // Zone 4: Dev (Coding & Impl)
    drawZoneRug(
      width * 0.18, height * 0.62, width * 0.13, height * 0.32,
      'rgba(16, 185, 129, 0.15)', '#10b981', '💻 4. DEV (Coding)'
    );
    // Zone 5: QA (Testing)
    drawZoneRug(
      width * 0.32, height * 0.62, width * 0.13, height * 0.32,
      'rgba(245, 158, 11, 0.15)', '#f59e0b', '🔎 5. QA (Testing)'
    );
    // Zone 6: Review (Security & Gates)
    drawZoneRug(
      width * 0.46, height * 0.62, width * 0.14, height * 0.32,
      'rgba(244, 63, 94, 0.15)', '#f43f5e', '🛡️ 6. REVIEW (Gates)'
    );

    // ZONE 7: OPS ROOM (Bottom Right)
    drawZoneRug(
      width * 0.64, height * 0.46, width * 0.33, height * 0.48,
      'rgba(14, 165, 233, 0.12)', '#0ea5e9', '🛰️ ZONE 7: OPS ROOM (Plan · Route · Recover · Report)'
    );

    // ZONE 8: DIRECTOR & APPROVAL SUITE (Top Right)
    drawZoneRug(
      width * 0.64, height * 0.08, width * 0.33, height * 0.34,
      'rgba(234, 179, 8, 0.14)', '#eab308', '👑 ZONE 8: DIRECTOR & APPROVAL SUITE'
    );

    // -------------------------------------------------------------
    // 3. WORKSTATION DESKS FOR EACH ZONE
    // -------------------------------------------------------------

    // Zone 1 Desks (Secretary Row: one per project)
    for (const key of secretaryIds()) {
      const sec = characters[key];
      drawOfficeDesk(sec.x, sec.y, sec.active, sec.project);
    }

    // Zone 2 Desks (AI Hub: Codex, Claude, Gemini)
    drawOfficeDesk(characters.ai_codex.x, characters.ai_codex.y, characters.ai_codex.active, '🟢 Codex');
    drawOfficeDesk(characters.ai_claude.x, characters.ai_claude.y, characters.ai_claude.active, '🟣 Claude');
    drawOfficeDesk(characters.ai_gemini.x, characters.ai_gemini.y, characters.ai_gemini.active, '🔵 Gemini');

    // Zone 3-6 Desks (Lead, Dev, QA, Review)
    drawOfficeDesk(characters.worker_lead.x, characters.worker_lead.y, characters.worker_lead.active, 'Lead Spec');
    drawOfficeDesk(characters.worker_dev.x, characters.worker_dev.y, characters.worker_dev.active, 'Dev Station');
    drawOfficeDesk(characters.worker_qa.x, characters.worker_qa.y, characters.worker_qa.active, 'QA Station');
    drawOfficeDesk(characters.worker_review.x, characters.worker_review.y, characters.worker_review.active, 'Review Gate');

    // Zone 7 Desks (Ops Room)
    drawOfficeDesk(characters.ops_planner.x, characters.ops_planner.y, characters.ops_planner.active, 'Planner');
    drawOfficeDesk(characters.ops_router.x, characters.ops_router.y, characters.ops_router.active, 'Router');
    drawOfficeDesk(characters.ops_recovery.x, characters.ops_recovery.y, characters.ops_recovery.active, 'Recovery');
    drawOfficeDesk(characters.ops_reporter.x, characters.ops_reporter.y, characters.ops_reporter.active, 'Reporter');

    // Zone 8 Director Desk
    drawDirectorExecutiveDesk(0.80, 0.22);

    // -------------------------------------------------------------
    // 4. DYNAMIC STAGE PIPELINE WORKFLOW ARROWS
    // -------------------------------------------------------------
    drawPipelineArrows();
  }

  function drawZoneRug(x, y, w, h, bg, border) {
    ctx.save();
    ctx.fillStyle = bg;
    ctx.strokeStyle = border;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 10);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  function drawPipelineArrows() {
    ctx.save();
    const dash = -tick * 1.5;

    // From Lead ➔ Dev
    drawAnimatedPipeline(
      characters.worker_lead.x * width + 28, characters.worker_lead.y * height,
      characters.worker_dev.x * width - 28, characters.worker_dev.y * height,
      '#a855f7', 'REQ ➔', dash
    );

    // From Dev ➔ QA
    drawAnimatedPipeline(
      characters.worker_dev.x * width + 28, characters.worker_dev.y * height,
      characters.worker_qa.x * width - 28, characters.worker_qa.y * height,
      '#10b981', 'TEST ➔', dash
    );

    // From QA ➔ Review
    drawAnimatedPipeline(
      characters.worker_qa.x * width + 28, characters.worker_qa.y * height,
      characters.worker_review.x * width - 28, characters.worker_review.y * height,
      '#f59e0b', 'GATE ➔', dash
    );

    // From Review ➔ Director Suite
    drawAnimatedPipeline(
      characters.worker_review.x * width, characters.worker_review.y * height - 35,
      width * 0.72, height * 0.32,
      '#ec4899', 'APPROVAL ➔', dash
    );

    ctx.restore();
  }

  function drawAnimatedPipeline(x1, y1, x2, y2, color, label, dash) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.2;
    ctx.setLineDash([7, 5]);
    ctx.lineDashOffset = dash;
    ctx.shadowColor = color;
    ctx.shadowBlur = 6;

    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();

    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    ctx.setLineDash([]);
    ctx.fillStyle = '#0f172a';
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    const tw = ctx.measureText(label).width;
    ctx.beginPath();
    ctx.roundRect(mx - tw / 2 - 5, my - 8, tw + 10, 16, 4);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 8.5px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, mx, my);

    ctx.restore();
  }

  function drawOfficeDesk(xRatio, yRatio, isWorking, label) {
    const x = xRatio * width;
    const y = yRatio * height;

    ctx.save();
    // Chair
    ctx.fillStyle = isWorking ? '#f43f5e' : '#334155';
    ctx.fillRect(x - 14, y - 30, 28, 12);

    // Desk Top (Warm Wood)
    ctx.fillStyle = '#b45309';
    ctx.strokeStyle = '#78350f';
    ctx.lineWidth = 1.6;
    ctx.fillRect(x - 36, y - 16, 72, 32);
    ctx.strokeRect(x - 36, y - 16, 72, 32);

    // Monitor with Code Matrix Glow
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(x - 16, y - 15, 32, 16);
    ctx.fillStyle = isWorking ? (Math.sin(tick * 0.3) > 0 ? '#38bdf8' : '#0284c7') : '#1e293b';
    ctx.fillRect(x - 14, y - 13, 28, 12);

    if (isWorking) {
      ctx.fillStyle = '#ffffff';
      for (let l = 0; l < 2; l++) {
        ctx.fillRect(x - 10 + ((tick * 2 + l * 8) % 18), y - 11 + l * 4, 5, 1.5);
      }
    }

    // Coffee Mug
    ctx.fillStyle = '#ef4444';
    ctx.beginPath();
    ctx.arc(x + 24, y + 4, 3.5, 0, Math.PI * 2);
    ctx.fill();

    // Desk Label
    if (label) {
      ctx.fillStyle = '#fef08a';
      ctx.font = 'bold 8px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(label, x, y + 12);
    }

    ctx.restore();
  }

  function drawDirectorExecutiveDesk(xRatio, yRatio) {
    const x = xRatio * width;
    const y = yRatio * height;

    ctx.save();
    // Executive Chair
    ctx.fillStyle = '#eab308';
    ctx.fillRect(x - 22, y - 34, 44, 14);

    // Large Oak Desk
    ctx.fillStyle = '#78350f';
    ctx.strokeStyle = '#451a03';
    ctx.lineWidth = 2;
    ctx.fillRect(x - 52, y - 18, 104, 38);
    ctx.strokeRect(x - 52, y - 18, 104, 38);

    // Laptop & Gold Sign
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(x - 18, y - 16, 36, 18);
    ctx.fillStyle = '#fbbf24';
    ctx.fillRect(x - 16, y - 14, 32, 14);

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('DIRECTOR & APPROVAL', x, y + 14);

    // Glowing Halo if task waiting
    const waiting = (window.snapshot?.tasks || []).filter(t => t.status === 'ready_for_human_approval');
    if (waiting.length > 0) {
      ctx.strokeStyle = '#ec4899';
      ctx.lineWidth = 2.5;
      ctx.shadowColor = '#ec4899';
      ctx.shadowBlur = 14 + Math.sin(tick * 0.2) * 6;
      ctx.strokeRect(x - 56, y - 22, 112, 46);
    }

    ctx.restore();
  }

  // ==============================================================================
  // DRAWING HUMAN-LIKE ANIME AVATARS WITH ANIMATIONS
  // ==============================================================================

  // ==============================================================================
  // PHOTO SPRITES: each character stands in the office as her own portrait.
  // If /assets/cutout/<name>.png exists (transparent background) it is used as-is;
  // otherwise the portrait is cropped to the upper body with feathered edges.
  // ==============================================================================

  const SPRITE_H = 92;
  const SPRITE_FULL_H = 128;
  const spriteCache = {};

  function buildFeatheredSprite(img) {
    const outW = 160, outH = 200;
    const c = document.createElement('canvas');
    c.width = outW;
    c.height = outH;
    const g = c.getContext('2d');

    // crop: full width, upper body (aspect 4:5), top-aligned
    const sh = Math.min(img.naturalHeight, img.naturalWidth * 1.25);
    const sw = sh / 1.25;
    const sx = (img.naturalWidth - sw) / 2;
    g.drawImage(img, sx, 0, sw, sh, 0, 0, outW, outH);

    // feather: soft oval around the head/shoulders, then fade out at the bottom
    g.globalCompositeOperation = 'destination-in';
    g.save();
    g.translate(outW / 2, outH * 0.46);
    g.scale(1, 1.3);
    const rg = g.createRadialGradient(0, 0, outW * 0.26, 0, 0, outW * 0.5);
    rg.addColorStop(0, 'rgba(0,0,0,1)');
    rg.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = rg;
    g.fillRect(-outW, -outH, outW * 2, outH * 2);
    g.restore();
    g.globalCompositeOperation = 'destination-in';
    const lg = g.createLinearGradient(0, outH * 0.7, 0, outH);
    lg.addColorStop(0, 'rgba(0,0,0,1)');
    lg.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = lg;
    g.fillRect(0, 0, outW, outH);
    return c;
  }

  function getPhotoSprite(char) {
    const key = char.photoUrl;
    if (!key) return null;
    let entry = spriteCache[key];
    if (!entry) {
      entry = spriteCache[key] = { full: null, cutout: null, feathered: null };
      const name = key.split('/').pop().replace(/\.[a-z]+$/i, '');
      const full = new Image();
      full.onload = () => { entry.full = full; };
      full.onerror = () => {};
      full.src = `/assets/full/${name}.png`;
      const cut = new Image();
      cut.onload = () => { entry.cutout = cut; };
      cut.onerror = () => {};
      cut.src = `/assets/cutout/${name}.png`;
    }
    if (entry.full) return { img: entry.full, full: true };
    if (entry.cutout) return { img: entry.cutout, cutout: true };
    if (!entry.feathered) {
      const img = char.photoImg;
      if (!img || !img.complete || img.naturalWidth === 0) return null;
      entry.feathered = buildFeatheredSprite(img);
    }
    return { img: entry.feathered, cutout: false };
  }

  function drawPhotoSprite(char, x, y, isSelected, isHovered) {
    const sprite = getPhotoSprite(char);
    if (!sprite) return false;

    const img = sprite.img;
    const iw = img.naturalWidth || img.width;
    const ih = img.naturalHeight || img.height;
    const h = (sprite.full ? SPRITE_FULL_H : SPRITE_H) * (isHovered ? 1.05 : 1);
    const w = h * iw / ih;
    const breathe = Math.sin(tick * 0.06 + char.x * 12) * 1.2;
    const bottom = y + 14;

    ctx.save();

    // ground shadow
    ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
    ctx.beginPath();
    ctx.ellipse(x, bottom, w * 0.34, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    // glow when working or selected
    if (isSelected || char.active) {
      ctx.shadowColor = isSelected ? '#ec4899' : '#10b981';
      ctx.shadowBlur = 14 + Math.sin(tick * 0.12) * 4;
    } else {
      ctx.shadowColor = 'rgba(0, 0, 0, 0.5)';
      ctx.shadowBlur = 8;
      ctx.shadowOffsetY = 3;
    }
    ctx.drawImage(img, x - w / 2, bottom - h + breathe, w, h);
    ctx.restore();
    char._spriteH = h - 4;
    return true;
  }

  function shadeColor(hex, amt) {
    const m = /^#([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return hex;
    const n = parseInt(m[1], 16);
    const ch = (v) => Math.max(0, Math.min(255, Math.round(v + (amt >= 0 ? (255 - v) * amt : v * amt))));
    const r = ch((n >> 16) & 255), g = ch((n >> 8) & 255), bl = ch(n & 255);
    return `rgb(${r}, ${g}, ${bl})`;
  }

  function drawHumanAnimeAvatar(char, x, y) {
    const S = 1.45;
    const bob = Math.sin(tick * 0.18) * (char.state === 'walking' ? 3 : 1.2);
    const legSwing = Math.sin(tick * 0.22) * 4;
    const hair = char.hairColor || '#451a03';
    const hairDark = shadeColor(hair, -0.35);
    const hairLight = shadeColor(hair, 0.45);
    const skin = char.skinTone || '#fed7aa';
    const skinShade = shadeColor(skin, -0.12);
    const dress = char.dressColor || '#ffffff';
    const skirt = char.skirtColor || '#0f172a';
    const isAI = char.zone === 'AI HUB';
    const blink = (tick + Math.floor(char.x * 97)) % 220 < 6;
    const hy = -19 + bob; // head centre

    ctx.save();
    ctx.translate(x, y);
    ctx.scale(S, S);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // Active aura
    if (char.active) {
      const pulse = 0.5 + Math.sin(tick * 0.1) * 0.15;
      const g = ctx.createRadialGradient(0, -6, 4, 0, -6, 30);
      g.addColorStop(0, shadeColor(hair, 0.2));
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.globalAlpha = pulse * 0.55;
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(0, -6, 30, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    // Ground shadow
    ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
    ctx.beginPath();
    ctx.ellipse(0, 16, 12, 4, 0, 0, Math.PI * 2);
    ctx.fill();

    // Back hair (behind body)
    ctx.fillStyle = hairDark;
    if (char.hairStyle === 'twintail') {
      ctx.beginPath();
      ctx.ellipse(-11, -8 + bob * 0.5, 3.6, 11, 0.12, 0, Math.PI * 2);
      ctx.ellipse(11, -8 + bob * 0.5, 3.6, 11, -0.12, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.roundRect(-10, hy - 2, 20, 22, 6);
      ctx.fill();
    }

    // Legs + shoes
    ctx.strokeStyle = skin;
    ctx.lineWidth = 3;
    const lx = char.state === 'walking' ? legSwing : 0;
    ctx.beginPath();
    ctx.moveTo(-3.5, 7); ctx.lineTo(-3.5 - lx, 14.5);
    ctx.moveTo(3.5, 7); ctx.lineTo(3.5 + lx, 14.5);
    ctx.stroke();
    ctx.fillStyle = '#1e1b2e';
    ctx.beginPath();
    ctx.roundRect(-7 - lx, 13.5, 6, 3.4, 1.5);
    ctx.roundRect(1 + lx, 13.5, 6, 3.4, 1.5);
    ctx.fill();

    // Skirt (gradient + pleats)
    const sg = ctx.createLinearGradient(0, -2, 0, 9);
    sg.addColorStop(0, shadeColor(skirt, 0.12));
    sg.addColorStop(1, shadeColor(skirt, -0.18));
    ctx.fillStyle = sg;
    ctx.beginPath();
    ctx.moveTo(-6.5, -2 + bob);
    ctx.lineTo(6.5, -2 + bob);
    ctx.lineTo(10, 9);
    ctx.lineTo(-10, 9);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,0.18)';
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(-2, -1 + bob); ctx.lineTo(-3.5, 9);
    ctx.moveTo(2, -1 + bob); ctx.lineTo(3.5, 9);
    ctx.stroke();

    // Torso with gradient
    const tg = ctx.createLinearGradient(-7, 0, 7, 0);
    tg.addColorStop(0, shadeColor(dress, -0.1));
    tg.addColorStop(0.5, shadeColor(dress, 0.08));
    tg.addColorStop(1, shadeColor(dress, -0.14));
    ctx.fillStyle = tg;
    ctx.beginPath();
    ctx.roundRect(-6.5, -13 + bob, 13, 13, 4);
    ctx.fill();

    // Collar / ribbon in the character's accent colour
    ctx.fillStyle = skin;
    ctx.beginPath();
    ctx.moveTo(-2.6, -13 + bob); ctx.lineTo(0, -8.5 + bob); ctx.lineTo(2.6, -13 + bob);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = shadeColor(hair, 0.1);
    ctx.beginPath();
    ctx.moveTo(0, -8.5 + bob);
    ctx.lineTo(-3.4, -6.5 + bob); ctx.lineTo(-3.4, -9.8 + bob);
    ctx.closePath();
    ctx.moveTo(0, -8.5 + bob);
    ctx.lineTo(3.4, -6.5 + bob); ctx.lineTo(3.4, -9.8 + bob);
    ctx.closePath();
    ctx.fill();

    // Chest emblem for AI providers
    if (isAI) {
      ctx.fillStyle = shadeColor(hair, 0.35);
      ctx.beginPath();
      ctx.arc(4, -4 + bob, 1.6, 0, Math.PI * 2);
      ctx.fill();
    }

    // Arms + hands
    ctx.strokeStyle = shadeColor(dress, -0.05);
    ctx.lineWidth = 3;
    let lh, rh;
    if (char.typing) {
      const th = Math.sin(tick * 0.4) * 2;
      lh = [-11, -2 + th]; rh = [11, -2 - th];
    } else {
      lh = [-8.5, 1 + bob]; rh = [8.5, 1 + bob];
    }
    ctx.beginPath();
    ctx.moveTo(-6.5, -10 + bob); ctx.lineTo(lh[0], lh[1]);
    ctx.moveTo(6.5, -10 + bob); ctx.lineTo(rh[0], rh[1]);
    ctx.stroke();
    ctx.fillStyle = skin;
    ctx.beginPath();
    ctx.arc(lh[0], lh[1] + 0.8, 1.7, 0, Math.PI * 2);
    ctx.arc(rh[0], rh[1] + 0.8, 1.7, 0, Math.PI * 2);
    ctx.fill();

    // Head
    const hg = ctx.createRadialGradient(-2, hy - 2, 1, 0, hy, 9);
    hg.addColorStop(0, shadeColor(skin, 0.25));
    hg.addColorStop(1, skinShade);
    ctx.fillStyle = hg;
    ctx.beginPath();
    ctx.ellipse(0, hy, 8, 8.6, 0, 0, Math.PI * 2);
    ctx.fill();

    // Blush
    ctx.fillStyle = 'rgba(244, 114, 182, 0.4)';
    ctx.beginPath();
    ctx.ellipse(-4.8, hy + 3.2, 2, 1.1, 0, 0, Math.PI * 2);
    ctx.ellipse(4.8, hy + 3.2, 2, 1.1, 0, 0, Math.PI * 2);
    ctx.fill();

    // Eyes (big anime eyes with highlight, blink)
    const iris = shadeColor(hair, 0.25);
    for (const ex of [-3.2, 3.2]) {
      if (blink) {
        ctx.strokeStyle = '#0f172a';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(ex - 2, hy + 0.8); ctx.lineTo(ex + 2, hy + 0.8);
        ctx.stroke();
        continue;
      }
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.ellipse(ex, hy + 0.5, 2.3, 2.9, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = iris;
      ctx.beginPath();
      ctx.ellipse(ex, hy + 0.9, 1.7, 2.3, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#0f172a';
      ctx.beginPath();
      ctx.ellipse(ex, hy + 1, 0.9, 1.4, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(ex - 0.6, hy - 0.2, 0.7, 0, Math.PI * 2);
      ctx.fill();
      // upper lash
      ctx.strokeStyle = '#0f172a';
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.arc(ex, hy + 0.5, 2.4, Math.PI * 1.05, Math.PI * 1.95);
      ctx.stroke();
    }

    // Mouth
    ctx.strokeStyle = '#be123c';
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    if (char.active || char.typing) {
      ctx.fillStyle = '#be123c';
      ctx.ellipse(0, hy + 5.2, 1.3, 0.9 + Math.abs(Math.sin(tick * 0.25)) * 0.5, 0, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.arc(0, hy + 4.2, 1.8, 0.15 * Math.PI, 0.85 * Math.PI);
      ctx.stroke();
    }

    // Glasses
    if (char.glasses) {
      ctx.strokeStyle = shadeColor(hair, -0.1);
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.arc(-3.2, hy + 0.6, 3.1, 0, Math.PI * 2);
      ctx.moveTo(6.3, hy + 0.6);
      ctx.arc(3.2, hy + 0.6, 3.1, 0, Math.PI * 2);
      ctx.moveTo(-0.1, hy + 0.4); ctx.lineTo(0.1, hy + 0.4);
      ctx.stroke();
    }

    // Front hair: cap + bangs + highlight
    const fg = ctx.createLinearGradient(0, hy - 10, 0, hy + 2);
    fg.addColorStop(0, hairLight);
    fg.addColorStop(0.35, hair);
    fg.addColorStop(1, hairDark);
    ctx.fillStyle = fg;
    ctx.beginPath();
    ctx.arc(0, hy - 0.5, 9.2, Math.PI, 0);
    ctx.lineTo(8.6, hy - 2);
    ctx.lineTo(5.5, hy - 5.2);
    ctx.lineTo(2.5, hy - 2.2);
    ctx.lineTo(-0.5, hy - 5.4);
    ctx.lineTo(-3.5, hy - 2.2);
    ctx.lineTo(-6, hy - 5);
    ctx.lineTo(-8.6, hy - 2);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.45)';
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    ctx.arc(0, hy - 0.5, 7.4, Math.PI * 1.2, Math.PI * 1.55);
    ctx.stroke();

    // Style accessories
    if (char.hairStyle === 'bunny') {
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.ellipse(-4, hy - 15, 1.8, 5, -0.15, 0, Math.PI * 2);
      ctx.ellipse(4, hy - 15, 1.8, 5, 0.15, 0, Math.PI * 2);
      ctx.fill();
    } else if (char.hairStyle === 'twintail') {
      ctx.fillStyle = shadeColor(hair, 0.5);
      ctx.beginPath();
      ctx.arc(-9, hy - 1, 1.5, 0, Math.PI * 2);
      ctx.arc(9, hy - 1, 1.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // AI provider headset with glowing mic
    if (isAI) {
      ctx.strokeStyle = '#e2e8f0';
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.arc(0, hy - 0.5, 9.9, Math.PI * 1.02, Math.PI * 1.98);
      ctx.stroke();
      ctx.fillStyle = shadeColor(hair, 0.1);
      ctx.beginPath();
      ctx.roundRect(-11.2, hy - 2, 3.2, 5.6, 1.5);
      ctx.roundRect(8, hy - 2, 3.2, 5.6, 1.5);
      ctx.fill();
      ctx.strokeStyle = '#e2e8f0';
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.moveTo(-9.6, hy + 3.4);
      ctx.quadraticCurveTo(-8.5, hy + 8, -3.5, hy + 7.4);
      ctx.stroke();
      ctx.fillStyle = char.active ? '#34d399' : shadeColor(hair, 0.3);
      ctx.beginPath();
      ctx.arc(-3.2, hy + 7.4, 1.2, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.restore();
  }

  // ==============================================================================
  // FLOATING SOWORK LIVE WEBCAM BUBBLE OVER CHARACTER
  // ==============================================================================

  const ROLE_COLORS = {
    sec: '#f472b6',
    ai: '#60a5fa',
    ops: '#38bdf8',
    worker_lead: '#c084fc',
    worker_dev: '#34d399',
    worker_qa: '#fbbf24',
    worker_review: '#fb7185'
  };

  function charLabels(char) {
    const first = (char.name || '').replace(/^เลขาฯ\s*/, '').split(' ')[0];
    let role;
    let color;
    if (char.id.startsWith('sec_')) {
      role = `PM · ${char.project}`;
      color = ROLE_COLORS.sec;
    } else {
      role = (char.badge || '').replace(/^[^\p{L}\p{N}]+/u, '').replace(/\s*\(.*\)\s*$/, '');
      color = ROLE_COLORS[char.id] ||
        (char.id.startsWith('ai_') ? ROLE_COLORS.ai : char.id.startsWith('ops_') ? ROLE_COLORS.ops : '#cbd5e1');
    }
    return { first, role, color };
  }

  function drawSoWorkBubble(char, x, y, isSelected, isHovered) {
    // Two-line pill above the head: name, then role (coloured by team)
    const { first, role, color } = charLabels(char);
    const nameY = y - (char._spriteH || (char._sprite ? 90 : 62)) - 6;
    ctx.save();
    ctx.font = 'bold 10px monospace';
    const w1 = ctx.measureText(first).width;
    ctx.font = 'bold 9px monospace';
    const w2 = ctx.measureText(role).width;
    const doing = (char.doing || '').length > 30 ? char.doing.slice(0, 29) + '…' : (char.doing || '');
    const line3 = doing || 'ว่าง';
    ctx.font = '9px sans-serif';
    const w3 = ctx.measureText(line3).width;
    const pw = Math.max(w1 + 22, w2 + 14, w3 + 14);
    const ph = 41;
    const top = nameY - 26;

    ctx.fillStyle = 'rgba(15, 23, 42, 0.94)';
    ctx.strokeStyle = (isSelected || isHovered) ? '#ec4899' : color;
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    ctx.roundRect(x - pw / 2, top, pw, ph, 8);
    ctx.fill();
    ctx.stroke();

    // Status dot + name
    ctx.fillStyle = char.active ? '#10b981' : '#64748b';
    ctx.beginPath();
    ctx.arc(x - w1 / 2 - 6, top + 8.5, 3.2, 0, Math.PI * 2);
    ctx.fill();

    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    ctx.font = 'bold 10px monospace';
    ctx.fillStyle = '#ffffff';
    ctx.fillText(first, x + 3, top + 9);

    // Role line
    ctx.font = 'bold 9px monospace';
    ctx.fillStyle = color;
    ctx.fillText(role, x, top + 21);

    // What she is doing right now
    ctx.font = '9px sans-serif';
    ctx.fillStyle = doing ? '#6ee7b7' : '#64748b';
    ctx.fillText(doing ? '▶ ' + line3 : line3, x, top + 33);

    // Activity emoji beside the pill
    if (char.active || isHovered) {
      ctx.font = '12px sans-serif';
      ctx.fillText(char.active ? '💻' : '💖', x + pw / 2 + 10, top + 12);
    }
    ctx.restore();
  }

  function drawParticles() {
    ctx.save();
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.x += p.vx;
      p.y += p.vy;
      p.alpha -= p.decay;

      if (p.alpha <= 0) {
        particles.splice(i, 1);
        continue;
      }

      ctx.globalAlpha = p.alpha;
      ctx.fillStyle = p.color;
      ctx.font = '13px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(p.text, p.x, p.y);
    }
    ctx.restore();
  }

  // ==============================================================================
  // MAIN ANIMATION LOOP
  // ==============================================================================

  function gameLoop() {
    tick++;
    if (tick % 30 === 0) {
      updateGameState();
    }

    ctx.clearRect(0, 0, width, height);

    drawDepartmentZonedOffice();

    // Characters Sorted by Y Depth
    const sorted = Object.values(characters).sort((a, b) => a.y - b.y);
    for (const char of sorted) {
      const isSelected = (selectedEntity === char);
      const isHovered = (hoveredEntity === char);
      const cx = char.x * width;
      const cy = char.y * height;

      char._sprite = drawPhotoSprite(char, cx, cy, isSelected, isHovered);
      if (!char._sprite) drawHumanAnimeAvatar(char, cx, cy);
      drawSoWorkBubble(char, cx, cy, isSelected, isHovered);
    }

    drawParticles();

    animFrameId = requestAnimationFrame(gameLoop);
  }

  window.OfficeGame = {
    init: initGame,
    refresh: updateGameState,
    playCuteSound: playCuteSound,
    selectCharacter: (id) => {
      if (characters[id]) {
        playCuteSound(784, 'triangle', 0.15);
        selectCharacter(characters[id]);
      }
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGame);
  } else {
    setTimeout(initGame, 100);
  }
})();
