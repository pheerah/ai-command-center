// ==============================================================================
// AI COMMAND CENTER - 3D ISOMETRIC VIRTUAL OFFICE (Team.AI.id & SoWork Edition)
// Designed by the 3 AI CLI Agents: Claude (3D Engine), Codex (3D Assets), Gemini (Interactions)
// ==============================================================================

(function() {
  'use strict';

  let THREE = null;
  let scene, camera, renderer, controls;
  let animFrameId = null;
  let container = null;
  let width = 0, height = 0;

  // Interaction
  let raycaster = null;
  const mouse = { x: 0, y: 0 };
  let hoveredObject = null;
  let selectedCharacter = null;
  const interactiveObjects = [];

  // Audio Engine
  let audioCtx = null;
  let soundEnabled = true;

  function playSound(freq = 600, type = 'triangle', duration = 0.15) {
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

  // Character Data & Multi-Project Mapping
  const characters = {
    linlin: {
      id: 'linlin',
      project: 'spc-new-erp',
      name: 'เลขาฯ หลินหลิน (Linlin)',
      role: 'Chief Secretary - spc-new-erp',
      badge: '👑 Linlin (spc-new-erp)',
      photoUrl: '/assets/sec_white_blouse.png',
      pos: { x: -5.5, y: 0, z: -1.5 },
      color: 0xffffff,
      skirtColor: 0xf8fafc,
      hairColor: 0x451a03,
      speech: 'ยินดีต้อนรับค่ะท่าน Director~ วันนี้โปรเจกต์ spc-new-erp ให้หลินหลินช่วยดูแลเรื่องไหนดีคะ? 💕',
      active: true,
      dialogues: [
        'ยินดีต้อนรับค่ะท่าน Director~ วันนี้โปรเจกต์ spc-new-erp ให้หลินหลินช่วยดูแลเรื่องไหนดีคะ? 💕',
        'งานใน spc-new-erp หลินหลินช่วยกำกับดูแลใกล้ชิดเลยค่ะ สั่งงานผ่านหลินหลินได้เลยนะคะ ✨',
        'คลิกคุยกับหลินหลิน แล้วพิมพ์คำสั่งด้านขวา หลินหลินส่งงานให้ทันทีเลยค่ะ!'
      ]
    },
    yuki: {
      id: 'yuki',
      project: 'horoscope',
      name: 'เลขาฯ ยูกิ (Yuki)',
      role: 'Chief Secretary - horoscope',
      badge: '💜 Yuki (horoscope)',
      photoUrl: '/assets/sec_purple_hair.png',
      pos: { x: 5.5, y: 0, z: -1.5 },
      color: 0xffffff,
      skirtColor: 0x0f172a,
      hairColor: 0x7c3aed,
      glasses: true,
      speech: 'สวัสดีค่ะท่าน Director~ ดวงและระบบ horoscope วันนี้ยูกิดูแลให้อย่างดีค่ะ 💜',
      active: false,
      dialogues: [
        'สวัสดีค่ะท่าน Director~ ดวงและระบบ horoscope วันนี้ยูกิดูแลให้อย่างดีค่ะ 💜',
        'ระบบ horoscope ทำงานราบรื่นมากค่ะ อยากเพิ่มฟีเจอร์ไหน พิมพ์สั่งยูกิได้ทันทีเลยนะคะ ✨',
        'ยูกิสแตนด์บายรอรับคำสั่งใหม่ของโปรเจกต์ horoscope จากท่าน Director เสมอค่ะ 💋'
      ]
    },
    serena: {
      id: 'serena',
      project: '',
      name: 'เลขาฯ เซเรน่า (Serena)',
      role: 'Executive Head Secretary (All Projects)',
      badge: '👑 Serena (HQ Center)',
      photoUrl: '/assets/sec_double_slit.png',
      pos: { x: 0, y: 0, z: -7.5 },
      color: 0xffffff,
      skirtColor: 0x18181b,
      hairColor: 0x581c87,
      speech: 'เซเรน่าดูแลภาพรวมของทุกโปรเจกต์ให้ท่าน Director ค่ะ 💕',
      active: true,
      dialogues: [
        'ยินดีต้อนรับค่ะท่าน Director~ เซเรน่าคอยคุมภาพรวมของทุกโปรเจกต์ให้ท่านค่ะ 💕',
        'เลขาฯ แต่ละโปรเจกต์ (หลินหลิน และ ยูกิ) พร้อมรับคำสั่งแยกโปรเจกต์ได้เลยนะคะ ✨',
        'ท่าน Director สามารถคลิกที่ตัวละครไหน เพื่อสั่งงานโปรเจกต์นั้นได้ทันทีค่ะ 🥰'
      ]
    },
    emily: {
      id: 'emily',
      project: 'spc-new-erp',
      name: 'เอมิรี่ (Emily Dev)',
      role: 'Lead Full-Stack Architect',
      badge: '⚡ Emily (Dev)',
      photoUrl: '/assets/sec_dark_glasses.jpg',
      pos: { x: -5.5, y: 0, z: 4.5 },
      color: 0xffffff,
      skirtColor: 0x18181b,
      hairColor: 0x1e1b4b,
      glasses: true,
      speech: 'ท่าน Director ขา~ โค้ดโปรเจกต์ spc-new-erp วันนี้ เอมิรี่จัดวางให้คลีนสุดๆ เลยค่ะ 💻',
      active: false,
      dialogues: [
        'ท่าน Director ขา~ สถาปัตยกรรมโค้ดวันนี้ เอมิรี่จัดวางให้คลีนสุดๆ เลยค่ะ 💻',
        'Zero-Waste Token ทุกคำสั่งรันแบบแม่นยำ ไม่เปลืองงบแน่นอนค่ะ!'
      ]
    },
    claire: {
      id: 'claire',
      project: 'horoscope',
      name: 'แคลร์ (Claire QA)',
      role: 'Code Reviewer & Quality Gates',
      badge: '🔎 Claire (QA)',
      photoUrl: '/assets/sec_blonde_suit.png',
      pos: { x: 5.5, y: 0, z: 4.5 },
      color: 0x94a3b8,
      skirtColor: 0x475569,
      hairColor: 0xeab308,
      glasses: true,
      speech: 'รายงานท่าน Director ค่ะ ทุก Patch ผ่านการทดสอบและ Quality Gates ครบถ้วน! 🔎',
      active: false,
      dialogues: [
        'รายงานท่าน Director ค่ะ ทุก Patch ผ่านการทดสอบและ Quality Gates ครบถ้วน! 🔎',
        'ถ้ามีโค้ดส่วนไหนไม่ปลอดภัย แคลร์จะดักจับไว้ให้ทันทีก่อนนำเข้าโปรเจกต์ค่ะ ✨'
      ]
    },
    trio: {
      id: 'trio',
      project: '',
      name: 'สาวๆ คาเฟ่เลานจ์ (Lounge Beauties)',
      role: 'Office Wellbeing & Coffee Lounge',
      badge: '☕ Cafe Beauties',
      photoUrl: '/assets/sec_trio_couch.jpg',
      pos: { x: 10.5, y: 0, z: 8.5 },
      color: 0xffffff,
      skirtColor: 0x0f172a,
      hairColor: 0x78350f,
      speech: 'แวะพักดื่มกาแฟกับพวกเราที่โซฟาคาเฟ่ก่อนได้นะคะท่าน Director~ ☕💕',
      active: true,
      dialogues: [
        'แวะพักดื่มกาแฟกับพวกเราที่โซฟาคาเฟ่ก่อนได้นะคะท่าน Director~ ☕💕',
        'ทำงานเหนื่อยๆ แวะมาคุยกับสาวๆ เติมพลังใจกันได้ตลอดเลยค่ะ 🥰'
      ]
    }
  };

  const characterMeshes = {};
  let targetLookAt = null;
  let currentLookAt = null;

  // ==============================================================================
  // UI BUTTON LISTENERS (ATTACHED IMMEDIATELY BEFORE 3D LOADS)
  // ==============================================================================

  function setupUIButtons() {
    const fsBtn = document.getElementById('btn-fullscreen');
    const resetBtn = document.getElementById('btn-reset-cam');
    const soundBtn = document.getElementById('btn-game-sound');
    const workspace = document.querySelector('.pixel-office-workspace');

    if (resetBtn) {
      resetBtn.onclick = () => {
        playSound(600, 'sine', 0.12);
        if (targetLookAt && camera) {
          targetLookAt.set(0, 1, 0);
          camera.position.set(24, 28, 26);
        }
      };
    }

    if (soundBtn) {
      soundBtn.onclick = () => {
        soundEnabled = !soundEnabled;
        soundBtn.textContent = soundEnabled ? '🔊 เสียงเปิด' : '🔇 เสียงปิด';
        soundBtn.classList.toggle('active', soundEnabled);
        if (soundEnabled) playSound(659, 'triangle', 0.15);
      };
    }

    if (fsBtn && workspace) {
      const toggleFullscreen = () => {
        if (!document.fullscreenElement && !workspace.classList.contains('fake-fullscreen')) {
          if (workspace.requestFullscreen) {
            workspace.requestFullscreen().catch(() => {
              workspace.classList.add('fake-fullscreen');
              fsBtn.innerHTML = '🗗 ย่อหน้าจอ';
              onResize();
            });
          } else {
            workspace.classList.add('fake-fullscreen');
            fsBtn.innerHTML = '🗗 ย่อหน้าจอ';
            onResize();
          }
        } else {
          if (document.fullscreenElement) {
            document.exitFullscreen().catch(() => {});
          }
          workspace.classList.remove('fake-fullscreen');
          fsBtn.innerHTML = '⛶ ขยายเต็มจอ';
          onResize();
        }
      };

      fsBtn.onclick = toggleFullscreen;

      document.addEventListener('fullscreenchange', () => {
        const isFs = !!document.fullscreenElement;
        fsBtn.innerHTML = isFs ? '🗗 ย่อหน้าจอ' : '⛶ ขยายเต็มจอ';
        setTimeout(onResize, 100);
      });

      window.addEventListener('keydown', (e) => {
        if ((e.key === 'f' || e.key === 'F') && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
          e.preventDefault();
          toggleFullscreen();
        }
        if (e.key === 'Escape' && workspace.classList.contains('fake-fullscreen')) {
          workspace.classList.remove('fake-fullscreen');
          fsBtn.innerHTML = '⛶ ขยายเต็มจอ';
          onResize();
        }
      });
    }

    // Sidebar Command Input
    const cmdInput = document.getElementById('sidebar-command-input');
    const cmdSend = document.getElementById('sidebar-command-send');
    if (cmdSend && cmdInput) {
      const handleSend = () => {
        const prompt = cmdInput.value.trim();
        if (!prompt) return;
        cmdInput.value = '';

        const proj = selectedCharacter?.project || document.getElementById('dispatch-project')?.value || 'spc-new-erp';

        playSound(880, 'triangle', 0.2);

        const textEl = document.getElementById('sidebar-bubble-text');
        if (textEl && selectedCharacter) {
          textEl.textContent = `"${selectedCharacter.name.split(' ')[0]} รับคำสั่งงานโปรเจกต์ [${proj}] เรียบร้อยค่ะ: '${prompt}' กำลังส่งให้ AI ลุยทันทีนะคะ 💕"`;
        }

        fetch('/api/dispatch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: proj, prompt: prompt })
        })
        .then(res => res.json())
        .then(data => {
          if (data.ok) {
            playSound(1046, 'sine', 0.25);
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

  // ==============================================================================
  // INITIALIZE 3D ENGINE (Claude's 3D Isometric Viewport)
  // ==============================================================================

  function init3DOffice() {
    if (!window.THREE) {
      console.warn('Waiting for Three.js bundle...');
      return false;
    }
    THREE = window.THREE;

    targetLookAt = new THREE.Vector3(0, 1, 0);
    currentLookAt = new THREE.Vector3(0, 1, 0);
    raycaster = new THREE.Raycaster();

    container = document.getElementById('office-game-container');
    if (!container) return false;

    // Check existing 2D canvas and hide it
    const canvas2d = document.getElementById('office-game-canvas');
    if (canvas2d) canvas2d.style.display = 'none';

    // Create 3D Viewport
    let canvas3d = document.getElementById('office-game-3d-canvas');
    if (!canvas3d) {
      canvas3d = document.createElement('canvas');
      canvas3d.id = 'office-game-3d-canvas';
      container.prepend(canvas3d);
    }
    canvas3d.style.display = 'block';

    const rect = container.getBoundingClientRect();
    width = rect.width || 800;
    const isFs = !!document.fullscreenElement || document.querySelector('.pixel-office-workspace')?.classList.contains('fake-fullscreen');
    height = isFs ? (window.innerHeight - 105) : Math.max(540, rect.height || 540);

    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f172a);
    scene.fog = new THREE.FogExp2(0x0f172a, 0.012);

    // Isometric Orthographic / High-Angle Perspective Camera
    camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 1000);
    camera.position.set(24, 28, 26);
    camera.lookAt(0, 1, 0);

    // Renderer
    renderer = new THREE.WebGLRenderer({
      canvas: canvas3d,
      antialias: true,
      powerPreference: 'high-performance'
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;

    // OrbitControls
    if (THREE.OrbitControls) {
      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.maxPolarAngle = Math.PI / 2.15;
      controls.minDistance = 14;
      controls.maxDistance = 65;
      controls.target.set(0, 1, 0);
    }

    // Preload textures
    const textureLoader = new THREE.TextureLoader();
    for (const char of Object.values(characters)) {
      char.texture = textureLoader.load(char.photoUrl);
    }

    setupLighting();
    buildOfficeEnvironment();
    spawnCharacters();

    window.addEventListener('resize', onResize);
    canvas3d.addEventListener('mousemove', onMouseMove);
    canvas3d.addEventListener('click', onClick);

    selectChar(characters.linlin);

    if (!animFrameId) {
      animFrameId = requestAnimationFrame(animate);
    }

    console.log('🏢 3D AI Virtual Office Initialized Successfully!');
    return true;
  }

  function setupLighting() {
    const ambientLight = new THREE.AmbientLight(0xfef08a, 0.65);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffedd5, 1.2);
    dirLight.position.set(20, 35, 15);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 1024;
    dirLight.shadow.mapSize.height = 1024;
    dirLight.shadow.bias = -0.0005;
    scene.add(dirLight);

    const rimLight = new THREE.DirectionalLight(0x38bdf8, 0.45);
    rimLight.position.set(-20, 15, -20);
    scene.add(rimLight);

    addDeskLight(-5.5, 3.5, -1.5, 0xf43f5e);
    addDeskLight(5.5, 3.5, -1.5, 0x8b5cf6);
    addDeskLight(0, 3.5, -7.5, 0xec4899);
  }

  function addDeskLight(x, y, z, color) {
    const light = new THREE.PointLight(color, 0.8, 8, 2);
    light.position.set(x, y, z);
    scene.add(light);
  }

  function buildOfficeEnvironment() {
    // Floor
    const floorGeo = new THREE.BoxGeometry(32, 0.8, 26);
    const floorMat = new THREE.MeshStandardMaterial({ color: 0x3f2214, roughness: 0.35, metalness: 0.1 });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.position.set(0, -0.4, 0);
    floor.receiveShadow = true;
    scene.add(floor);

    const frameGeo = new THREE.BoxGeometry(32.8, 0.9, 26.8);
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.5 });
    const frame = new THREE.Mesh(frameGeo, frameMat);
    frame.position.set(0, -0.45, 0);
    scene.add(frame);

    // Department Rugs
    createRug(-5.5, 0.02, 1.5, 10, 16, 0xf43f5e, 0.15);
    createRug(5.5, 0.02, 1.5, 10, 16, 0x8b5cf6, 0.15);
    createRug(0, 0.02, -7.5, 12, 6, 0xec4899, 0.2);
    createRug(10.5, 0.02, 8.5, 8, 8, 0xf59e0b, 0.2);

    // Glass Walls
    createGlassWall(0, 2.5, -1, 0.2, 5, 12);
    createGlassWall(-15.8, 3, 0, 0.4, 6, 25.5);
    createGlassWall(0, 3, -12.8, 31.5, 6, 0.4);

    // Workstations
    createWorkstation(-5.5, -1.5, 'spc-new-erp', 0x38bdf8);
    createWorkstation(-5.5, 4.5, 'DEV-1', 0x10b981);
    createWorkstation(5.5, -1.5, 'horoscope', 0xa855f7);
    createWorkstation(5.5, 4.5, 'QA-1', 0xf59e0b);

    createExecutiveDesk(0, -7.5);
    createCafeLounge(10.5, 8.5);

    createWaterCooler(-12.5, 10);
    createPlant(-14, -10.5);
    createPlant(14, -10.5);
    createPlant(-14, 10.5);
    createPlant(14, 10.5);
    createAquarium(-11, -1);
  }

  function createRug(x, y, z, w, d, color, opacity) {
    const geo = new THREE.PlaneGeometry(w, d);
    const mat = new THREE.MeshBasicMaterial({ color: color, transparent: true, opacity: opacity, side: THREE.DoubleSide });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(x, y, z);
    scene.add(mesh);
  }

  function createGlassWall(x, y, z, w, h, d) {
    const geo = new THREE.BoxGeometry(w, h, d);
    const mat = new THREE.MeshPhysicalMaterial({
      color: 0x93c5fd,
      transparent: true,
      opacity: 0.25,
      roughness: 0.1,
      transmission: 0.9,
      thickness: 0.5
    });
    const wall = new THREE.Mesh(geo, mat);
    wall.position.set(x, y, z);
    scene.add(wall);
  }

  function createWorkstation(x, z, label, screenGlowColor) {
    const group = new THREE.Group();
    group.position.set(x, 0, z);

    const deskTop = new THREE.Mesh(new THREE.BoxGeometry(4.2, 0.16, 2.4), new THREE.MeshStandardMaterial({ color: 0xd97706, roughness: 0.4 }));
    deskTop.position.y = 1.6;
    deskTop.castShadow = true;
    group.add(deskTop);

    const legMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, metalness: 0.8 });
    const legL = new THREE.Mesh(new THREE.BoxGeometry(0.12, 1.6, 2.2), legMat);
    legL.position.set(-1.9, 0.8, 0);
    group.add(legL);

    const legR = new THREE.Mesh(new THREE.BoxGeometry(0.12, 1.6, 2.2), legMat);
    legR.position.set(1.9, 0.8, 0);
    group.add(legR);

    // Dual Monitors
    const monMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.3 });
    const screenMat = new THREE.MeshBasicMaterial({ color: screenGlowColor });

    const mon1 = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.0, 0.08), monMat);
    mon1.position.set(-0.85, 2.3, -0.6);
    mon1.rotation.y = 0.15;
    group.add(mon1);

    const scr1 = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.9), screenMat);
    scr1.position.set(-0.85, 2.3, -0.55);
    scr1.rotation.y = 0.15;
    group.add(scr1);

    const mon2 = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.0, 0.08), monMat);
    mon2.position.set(0.85, 2.3, -0.6);
    mon2.rotation.y = -0.15;
    group.add(mon2);

    const scr2 = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.9), screenMat);
    scr2.position.set(0.85, 2.3, -0.55);
    scr2.rotation.y = -0.15;
    group.add(scr2);

    createChair(group, 0, 0, 0.8);
    scene.add(group);
  }

  function createExecutiveDesk(x, z) {
    const group = new THREE.Group();
    group.position.set(x, 0, z);

    const deskTop = new THREE.Mesh(new THREE.BoxGeometry(6.5, 0.2, 3.2), new THREE.MeshStandardMaterial({ color: 0x451a03, roughness: 0.25 }));
    deskTop.position.y = 1.6;
    deskTop.castShadow = true;
    group.add(deskTop);

    const frontPanel = new THREE.Mesh(new THREE.BoxGeometry(6.3, 1.4, 0.1), new THREE.MeshStandardMaterial({ color: 0x1e293b }));
    frontPanel.position.set(0, 0.8, -1.4);
    group.add(frontPanel);

    const laptop = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.05, 0.8), new THREE.MeshStandardMaterial({ color: 0x94a3b8 }));
    laptop.position.set(0, 1.73, 0);
    group.add(laptop);

    createChair(group, 0, 0, 1.0);
    scene.add(group);
  }

  function createChair(parent, x, y, z) {
    const chair = new THREE.Group();
    chair.position.set(x, y, z);

    const seat = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.15, 1.2), new THREE.MeshStandardMaterial({ color: 0x1e293b }));
    seat.position.y = 1.1;
    seat.castShadow = true;
    chair.add(seat);

    const back = new THREE.Mesh(new THREE.BoxGeometry(1.2, 1.2, 0.15), new THREE.MeshStandardMaterial({ color: 0x1e293b }));
    back.position.set(0, 1.7, 0.55);
    back.castShadow = true;
    chair.add(back);

    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 1.0), new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.9 }));
    stem.position.y = 0.55;
    chair.add(stem);

    parent.add(chair);
  }

  function createCafeLounge(x, z) {
    const group = new THREE.Group();
    group.position.set(x, 0, z);

    const sofaBase = new THREE.Mesh(new THREE.BoxGeometry(5.5, 0.6, 2.2), new THREE.MeshStandardMaterial({ color: 0xbe123c, roughness: 0.6 }));
    sofaBase.position.y = 0.5;
    sofaBase.castShadow = true;
    group.add(sofaBase);

    const sofaBack = new THREE.Mesh(new THREE.BoxGeometry(5.5, 1.2, 0.6), new THREE.MeshStandardMaterial({ color: 0x9f1239, roughness: 0.6 }));
    sofaBack.position.set(0, 1.2, 0.8);
    sofaBack.castShadow = true;
    group.add(sofaBack);

    const tableTop = new THREE.Mesh(new THREE.CylinderGeometry(1.4, 1.4, 0.1, 32), new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.2 }));
    tableTop.position.set(0, 0.8, -1.8);
    group.add(tableTop);

    const tableLeg = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.7, 16), new THREE.MeshStandardMaterial({ color: 0x0f172a }));
    tableLeg.position.set(0, 0.4, -1.8);
    group.add(tableLeg);

    scene.add(group);
  }

  function createPlant(x, z) {
    const plant = new THREE.Group();
    plant.position.set(x, 0, z);

    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.5, 1.2, 16), new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.3 }));
    pot.position.y = 0.6;
    pot.castShadow = true;
    plant.add(pot);

    const bush = new THREE.Mesh(new THREE.DodecahedronGeometry(0.9, 1), new THREE.MeshStandardMaterial({ color: 0x15803d, roughness: 0.8 }));
    bush.position.y = 1.7;
    bush.castShadow = true;
    plant.add(bush);

    scene.add(plant);
  }

  function createWaterCooler(x, z) {
    const group = new THREE.Group();
    group.position.set(x, 0, z);

    const base = new THREE.Mesh(new THREE.BoxGeometry(1.0, 2.2, 1.0), new THREE.MeshStandardMaterial({ color: 0xf8fafc }));
    base.position.y = 1.1;
    group.add(base);

    const jug = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 0.9, 16), new THREE.MeshPhysicalMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.7, transmission: 0.8 }));
    jug.position.y = 2.65;
    group.add(jug);

    scene.add(group);
  }

  function createAquarium(x, z) {
    const group = new THREE.Group();
    group.position.set(x, 0, z);

    const stand = new THREE.Mesh(new THREE.BoxGeometry(4.0, 1.2, 1.2), new THREE.MeshStandardMaterial({ color: 0x1e293b }));
    stand.position.y = 0.6;
    group.add(stand);

    const tank = new THREE.Mesh(new THREE.BoxGeometry(3.8, 1.6, 1.0), new THREE.MeshPhysicalMaterial({ color: 0x0284c7, transparent: true, opacity: 0.65, transmission: 0.9 }));
    tank.position.y = 1.9;
    group.add(tank);

    scene.add(group);
  }

  // ==============================================================================
  // 3D SEXY CHARACTERS & FLOATING SOWORK BILLBOARD BUBBLES
  // ==============================================================================

  function spawnCharacters() {
    for (const [key, char] of Object.entries(characters)) {
      const charGroup = new THREE.Group();
      charGroup.position.set(char.pos.x, char.pos.y, char.pos.z);
      charGroup.userData = { charData: char };

      const bodyGroup = new THREE.Group();

      const skirtGeo = new THREE.CylinderGeometry(0.35, 0.55, 0.6, 16);
      const skirtMat = new THREE.MeshStandardMaterial({ color: char.skirtColor });
      const skirt = new THREE.Mesh(skirtGeo, skirtMat);
      skirt.position.y = 1.35;
      skirt.castShadow = true;
      bodyGroup.add(skirt);

      const torsoGeo = new THREE.BoxGeometry(0.75, 0.8, 0.45);
      const torsoMat = new THREE.MeshStandardMaterial({ color: char.color });
      const torso = new THREE.Mesh(torsoGeo, torsoMat);
      torso.position.y = 1.95;
      torso.castShadow = true;
      bodyGroup.add(torso);

      const headGeo = new THREE.SphereGeometry(0.38, 16, 16);
      const headMat = new THREE.MeshStandardMaterial({ color: 0xfed7aa, roughness: 0.5 });
      const head = new THREE.Mesh(headGeo, headMat);
      head.position.y = 2.6;
      head.castShadow = true;
      bodyGroup.add(head);

      const hairGeo = new THREE.SphereGeometry(0.42, 16, 16);
      const hairMat = new THREE.MeshStandardMaterial({ color: char.hairColor, roughness: 0.4 });
      const hair = new THREE.Mesh(hairGeo, hairMat);
      hair.position.set(0, 2.7, -0.05);
      hair.scale.set(1.05, 1.1, 1.15);
      bodyGroup.add(hair);

      charGroup.add(bodyGroup);

      // Billboard Photo
      const billboard = createPhotoBillboard(char);
      billboard.position.y = 4.2;
      charGroup.add(billboard);

      // Selection Ring
      const ringGeo = new THREE.RingGeometry(1.0, 1.25, 32);
      const ringMat = new THREE.MeshBasicMaterial({ color: 0xec4899, side: THREE.DoubleSide, transparent: true, opacity: 0 });
      const ring = new THREE.Mesh(ringGeo, ringMat);
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.04;
      charGroup.add(ring);
      charGroup.userData.ring = ring;
      charGroup.userData.billboard = billboard;

      scene.add(charGroup);
      characterMeshes[key] = charGroup;
      interactiveObjects.push(charGroup);
    }
  }

  function createPhotoBillboard(char) {
    const group = new THREE.Group();

    const frameGeo = new THREE.PlaneGeometry(1.6, 1.9);
    const frameMat = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide });
    const frame = new THREE.Mesh(frameGeo, frameMat);
    group.add(frame);

    const photoGeo = new THREE.PlaneGeometry(1.48, 1.76);
    const photoMat = new THREE.MeshBasicMaterial({ map: char.texture, side: THREE.DoubleSide });
    const photo = new THREE.Mesh(photoGeo, photoMat);
    photo.position.z = 0.01;
    group.add(photo);

    const borderGeo = new THREE.PlaneGeometry(1.68, 1.98);
    const borderMat = new THREE.MeshBasicMaterial({
      color: char.active ? 0x10b981 : 0xec4899,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.8
    });
    const border = new THREE.Mesh(borderGeo, borderMat);
    border.position.z = -0.01;
    group.add(border);

    return group;
  }

  // ==============================================================================
  // INTERACTION & RAYCASTING
  // ==============================================================================

  function onMouseMove(e) {
    if (!renderer || !camera || !raycaster) return;
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    const hits = raycaster.intersectObjects(scene.children, true);

    let foundChar = null;
    for (const hit of hits) {
      let curr = hit.object;
      while (curr && curr !== scene) {
        if (curr.userData?.charData) {
          foundChar = curr;
          break;
        }
        curr = curr.parent;
      }
      if (foundChar) break;
    }

    if (foundChar !== hoveredObject) {
      if (hoveredObject && hoveredObject.userData?.ring) {
        if (hoveredObject.userData.charData !== selectedCharacter) {
          hoveredObject.userData.ring.material.opacity = 0;
        }
      }
      hoveredObject = foundChar;
      if (hoveredObject && hoveredObject.userData?.ring) {
        hoveredObject.userData.ring.material.opacity = 0.7;
        renderer.domElement.style.cursor = 'pointer';
      } else {
        renderer.domElement.style.cursor = 'default';
      }
    }
  }

  function onClick() {
    if (hoveredObject && hoveredObject.userData?.charData) {
      const char = hoveredObject.userData.charData;
      playSound(784, 'triangle', 0.18);
      selectChar(char);
    }
  }

  function selectChar(char) {
    selectedCharacter = char;

    for (const mesh of Object.values(characterMeshes)) {
      if (mesh.userData?.ring) {
        const isThis = (mesh.userData.charData === char);
        mesh.userData.ring.material.opacity = isThis ? 1.0 : 0;
        mesh.userData.ring.material.color.setHex(isThis ? 0xec4899 : 0x38bdf8);
      }
    }

    if (targetLookAt) targetLookAt.set(char.pos.x, 1.5, char.pos.z);

    const photoEl = document.getElementById('sidebar-agent-photo');
    const badgeEl = document.getElementById('sidebar-agent-badge');
    const projChip = document.getElementById('sidebar-project-chip');
    const nameEl = document.getElementById('sidebar-agent-name');
    const statusEl = document.getElementById('sidebar-agent-status');
    const senderEl = document.getElementById('sidebar-bubble-sender');
    const textEl = document.getElementById('sidebar-bubble-text');
    const statusBubbleText = document.getElementById('sidebar-status-text');
    const btnApprove = document.getElementById('sidebar-btn-approve');
    const btnDetails = document.getElementById('sidebar-btn-details');
    const cmdInput = document.getElementById('sidebar-command-input');
    const mainProjSelect = document.getElementById('dispatch-project');

    if (photoEl) photoEl.src = char.photoUrl;
    if (badgeEl) badgeEl.textContent = char.badge;
    if (nameEl) nameEl.textContent = char.name;

    if (char.project) {
      if (projChip) projChip.textContent = `📁 ${char.project}`;
      if (mainProjSelect) mainProjSelect.value = char.project;
      if (cmdInput) cmdInput.placeholder = `💬 สั่งงาน [${char.project}] ผ่าน${char.name.split(' ')[0]} (Enter)...`;
    } else {
      if (projChip) projChip.textContent = '📁 ส่วนกลาง / HQ';
      if (cmdInput) cmdInput.placeholder = '💬 สั่งงานส่วนกลาง หรือ ทักทายสาวๆ (Enter)...';
    }

    if (statusEl) {
      statusEl.textContent = char.active ? '🟢 กำลังปฏิบัติหน้าที่อย่างตั้งใจ' : '🔵 พร้อมรับคำสั่งใหม่ (Idle)';
    }
    if (senderEl) senderEl.textContent = char.name.split(' ')[0] + ':';

    if (char.dialogues && char.dialogues.length) {
      const rand = char.dialogues[Math.floor(Math.random() * char.dialogues.length)];
      char.speech = rand;
    }
    if (textEl) textEl.textContent = `"${char.speech}"`;

    const snap = window.snapshot;
    const allTasks = snap?.tasks || [];
    const projTasks = char.project ? allTasks.filter(t => t.project_id === char.project) : allTasks;

    const waiting = projTasks.filter(t => t.status === 'ready_for_human_approval');
    const running = projTasks.filter(t => t.status === 'running');

    let currentTaskId = null;
    let isApproval = false;

    if (waiting.length > 0) {
      currentTaskId = waiting[0].id;
      isApproval = true;
      if (statusBubbleText) {
        statusBubbleText.textContent = `🎉 มีงาน [${waiting[0].project_id}] ${waiting[0].title} ผ่านการตรวจสอบครบถ้วนแล้ว พร้อมให้ท่าน Director กดอนุมัติค่ะ!`;
      }
    } else if (running.length > 0) {
      currentTaskId = running[0].id;
      if (statusBubbleText) {
        statusBubbleText.textContent = `กำลังลุยงาน [${running[0].project_id}] ${running[0].title} ให้ท่าน Director อยู่นะคะ ✨`;
      }
    } else {
      if (statusBubbleText) {
        statusBubbleText.textContent = char.project 
          ? `โปรเจกต์ ${char.project} พร้อมรับคำสั่งใหม่จากท่าน Director ทันทีค่ะ 💕`
          : 'ทุกระบบพร้อมรับคำสั่งใหม่จากท่าน Director ทันที 💕';
      }
    }

    if (btnApprove) {
      if (isApproval && currentTaskId) {
        btnApprove.style.display = 'block';
        btnApprove.textContent = `✓ กดอนุมัติงาน [${waiting[0].project_id}] ทันที 💕`;
        btnApprove.onclick = () => {
          if (window.approveTask) window.approveTask(currentTaskId);
        };
      } else {
        btnApprove.style.display = 'none';
      }
    }

    if (btnDetails) {
      if (currentTaskId) {
        btnDetails.onclick = () => {
          if (window.details) window.details(currentTaskId);
        };
      } else {
        btnDetails.onclick = () => {
          if (cmdInput) cmdInput.focus();
        };
      }
    }
  }

  function onResize() {
    if (!container || !renderer || !camera) return;
    const rect = container.getBoundingClientRect();
    width = rect.width || 800;
    const isFs = !!document.fullscreenElement || document.querySelector('.pixel-office-workspace')?.classList.contains('fake-fullscreen');
    height = isFs ? (window.innerHeight - 105) : Math.max(540, rect.height || 540);

    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }

  // ==============================================================================
  // 60FPS ANIMATION LOOP
  // ==============================================================================

  let clock = 0;
  function animate() {
    animFrameId = requestAnimationFrame(animate);
    clock += 0.03;

    if (currentLookAt && targetLookAt && controls) {
      currentLookAt.lerp(targetLookAt, 0.06);
      controls.target.copy(currentLookAt);
      controls.update();
    }

    for (const [key, mesh] of Object.entries(characterMeshes)) {
      if (mesh.userData?.billboard && camera) {
        mesh.userData.billboard.quaternion.copy(camera.quaternion);
        mesh.userData.billboard.position.y = 4.2 + Math.sin(clock + mesh.position.x) * 0.12;
      }
    }

    if (renderer && scene && camera) {
      renderer.render(scene, camera);
    }
  }

  window.Office3D = {
    init: init3DOffice,
    onResize: onResize,
    selectCharacter: (id) => {
      if (characters[id]) selectChar(characters[id]);
    },
    resetCamera: () => {
      if (targetLookAt && camera) {
        targetLookAt.set(0, 1, 0);
        camera.position.set(24, 28, 26);
      }
    }
  };

  // Launch on DOM Ready & Retry if Three.js needs a split second
  function launch() {
    setupUIButtons();
    let attempts = 0;
    const checkThree = () => {
      attempts++;
      if (init3DOffice()) {
        console.log('Office3D mounted on attempt', attempts);
      } else if (attempts < 60) {
        setTimeout(checkThree, 50);
      } else {
        console.error('Three.js failed to load within timeout');
      }
    };
    checkThree();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', launch);
  } else {
    setTimeout(launch, 100);
  }

})();
