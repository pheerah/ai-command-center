// Office module: avatar (split out of office_game.js; behaviour unchanged).
(function() {
  'use strict';
  const K = (window.OfficeKit = window.OfficeKit || {});
  const { SPRITE_H, ROLE_COLORS } = K.config;

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

  // Which optional sprite tiers exist on disk; loaded once from the server so no request targets a missing file.
  let availableSprites = null;
  fetch('/api/sprites')
    .then(res => res.json())
    .then(list => { availableSprites = { cutout: new Set(list.cutout || []), full: new Set(list.full || []) }; })
    .catch(() => { availableSprites = { cutout: new Set(), full: new Set() }; });

  function loadSpriteTier(entry, tier, name) {
    const img = new Image();
    img.onload = () => { entry[tier] = img; };
    img.src = `/assets/${tier}/${name}.png`;
  }

  function getPhotoSprite(char) {
    const key = char.photoUrl;
    if (!key || !availableSprites) return null;
    let entry = spriteCache[key];
    if (!entry) {
      entry = spriteCache[key] = { full: null, cutout: null, feathered: null };
      const name = key.split('/').pop().replace(/\.[a-z]+$/i, '');
      for (const tier of ['full', 'cutout']) {
        if (availableSprites[tier].has(name)) loadSpriteTier(entry, tier, name);
      }
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
    const { ctx, height, tick } = K.view;
    const sprite = getPhotoSprite(char);
    if (!sprite) return false;

    const img = sprite.img;
    const iw = img.naturalWidth || img.width;
    const ih = img.naturalHeight || img.height;
    const base = Math.max(60, Math.min(SPRITE_H, height * 0.15));
    const h = (sprite.full ? base * 1.4 : base) * (isHovered ? 1.05 : 1);
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
    const { ctx, tick } = K.view;
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
    const { ctx } = K.view;
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
    const top = Math.max(2, nameY - 26);

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
    const { ctx } = K.view;
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

  K.avatar = { addParticle, drawParticles, drawPhotoSprite, drawHumanAnimeAvatar, drawSoWorkBubble };
})();
