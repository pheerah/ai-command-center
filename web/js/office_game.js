// Office module: main (split out of office_game.js; behaviour unchanged).
(function() {
  'use strict';
  const K = (window.OfficeKit = window.OfficeKit || {});
  const { characters } = K.config;
  const playCuteSound = K.sound.play;
  const { isOpen: isModalOpen, close: closeAgentModal, select: selectCharacter, setupPortraitMotion } = K.modal;
  const { addParticle, drawParticles, drawPhotoSprite, drawHumanAnimeAvatar, drawSoWorkBubble } = K.avatar;
  const { drawDepartmentZonedOffice } = K.scene;
  const { updateGameState } = K.sync;

  let canvas, ctx;

  let animFrameId = null;

  let gameContainer = null;

  let width = 0, height = 0;

  let dpr = 1;

  let tick = 0;

  let hoveredEntity = null;

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
    K.view.ctx = ctx;

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
        const on = K.sound.toggle();
        soundBtn.textContent = on ? '🔊 เสียงเปิด' : '🔇 เสียงปิด';
        soundBtn.classList.toggle('active', on);
        if (on) playCuteSound(659, 'triangle', 0.15);
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
    Object.assign(K.view, { width, height, dpr });
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

  function gameLoop() {
    tick++;
    K.view.tick = tick;
    if (tick % 30 === 0) {
      updateGameState();
    }

    ctx.clearRect(0, 0, width, height);

    drawDepartmentZonedOffice();

    // Characters Sorted by Y Depth
    const sorted = Object.values(characters).sort((a, b) => a.y - b.y);
    for (const char of sorted) {
      const isSelected = (K.modal.selected() === char);
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
