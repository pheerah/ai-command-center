// Office module: config (split out of office_game.js; behaviour unchanged).
(function() {
  'use strict';
  const K = (window.OfficeKit = window.OfficeKit || {});
  K.view = { ctx: null, width: 0, height: 0, tick: 0, dpr: 1 };  // canvas state shared with the drawing modules

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
      x: 0.68, y: 0.74,
      baseX: 0.68, baseY: 0.74,
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
      x: 0.76, y: 0.74,
      baseX: 0.76, baseY: 0.74,
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
      x: 0.84, y: 0.74,
      baseX: 0.84, baseY: 0.74,
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
      x: 0.92, y: 0.74,
      baseX: 0.92, baseY: 0.74,
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

  // Active Walking Waypoints for Mia (Messenger Courier running between all zones)
  const miaWaypoints = [
    { x: 0.26, y: 0.26, wait: 50, speech: 'รับโจทย์ใหม่จากเลขาฯ หลินหลิน [spc-new-erp] 💌' },
    { x: 0.12, y: 0.68, wait: 50, speech: 'ส่งต่อไปยัง แผนก Lead Architect เพื่อวางแผน 🧠' },
    { x: 0.26, y: 0.68, wait: 50, speech: 'ส่งต่อให้ แผนก Dev เริ่ม Implement โค้ด! 💻' },
    { x: 0.40, y: 0.68, wait: 50, speech: 'นำ Patch ส่งให้ แผนก QA ตรวจสอบการทำงาน 🔎' },
    { x: 0.54, y: 0.68, wait: 50, speech: 'ส่งเข้า แผนก Review เพื่อตรวจความปลอดภัย 🛡️' },
    { x: 0.82, y: 0.26, wait: 50, speech: 'ส่งขึ้นโต๊ะท่าน Director รอเซ็นอนุมัติ! 👑' }
  ];

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

  const SPRITE_H = 96;

  const ROLE_COLORS = {
    sec: '#f472b6',
    ai: '#60a5fa',
    ops: '#38bdf8',
    worker_lead: '#c084fc',
    worker_dev: '#34d399',
    worker_qa: '#fbbf24',
    worker_review: '#fb7185'
  };

  K.config = { photos, characters, miaWaypoints, SECRETARY_PERSONAS, secretaryIds, SPRITE_H, ROLE_COLORS };
})();
