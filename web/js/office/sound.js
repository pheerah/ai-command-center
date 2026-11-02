// Office module: sound (split out of office_game.js; behaviour unchanged).
(function() {
  'use strict';
  const K = (window.OfficeKit = window.OfficeKit || {});

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

  K.sound = {
    play: playCuteSound,
    toggle() { soundEnabled = !soundEnabled; return soundEnabled; },
    isEnabled() { return soundEnabled; },
  };
})();
