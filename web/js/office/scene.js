// Office module: scene (split out of office_game.js; behaviour unchanged).
(function() {
  'use strict';
  const K = (window.OfficeKit = window.OfficeKit || {});
  const { characters, secretaryIds } = K.config;

  function drawDepartmentZonedOffice() {
    const { ctx, width, height } = K.view;
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
    const { ctx } = K.view;
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
    const { ctx, width, height, tick } = K.view;
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
    const { ctx } = K.view;
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
    const { ctx, width, height, tick } = K.view;
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
    const { ctx, width, height, tick } = K.view;
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

  K.scene = { drawDepartmentZonedOffice };
})();
