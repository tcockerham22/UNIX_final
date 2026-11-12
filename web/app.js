"use strict";

const els = {
  canvas: document.getElementById("orb"),
  stateLabel: document.getElementById("state-label"),
  stateDetail: document.getElementById("state-detail"),
  routeText: document.getElementById("route-text"),
  modelText: document.getElementById("model-text"),
  linkText: document.getElementById("link-text"),
  tiersText: document.getElementById("tiers-text"),
};

const ctx = els.canvas ? els.canvas.getContext("2d") : null;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const STATE_LABELS = {
  idle: "IDLE",
  listening: "LISTENING",
  transcribing: "TRANSCRIBING",
  thinking: "THINKING",
  speaking: "SPEAKING",
  warming: "WARMING",
  error: "FAULT",
};

// Original GitHub orb palettes
const PALETTES = {
  idle: { core: "#8fd9a8", glow: "rgba(90,160,110,0.16)", ring: "rgba(143,217,168,0.34)", accent: "#e7f6d8" },
  listening: { core: "#9fe3b6", glow: "rgba(100,170,120,0.16)", ring: "rgba(159,227,182,0.38)", accent: "#f0ffe8" },
  transcribing: { core: "#9fe3b6", glow: "rgba(100,170,120,0.16)", ring: "rgba(159,227,182,0.38)", accent: "#f0ffe8" },
  thinking: { core: "#ffd89a", glow: "rgba(200,150,70,0.16)", ring: "rgba(255,216,154,0.38)", accent: "#fff3dc" },
  speaking: { core: "#b7efb0", glow: "rgba(120,190,110,0.17)", ring: "rgba(183,239,176,0.40)", accent: "#f4ffe6" },
  warming: { core: "#d8c9a8", glow: "rgba(160,140,100,0.14)", ring: "rgba(216,201,168,0.34)", accent: "#fff4df" },
  error: { core: "#ffab96", glow: "rgba(210,110,80,0.16)", ring: "rgba(255,171,150,0.40)", accent: "#ffe7df" },
};

const state = {
  current: "idle",
  detail: "awaiting input",
  route: "—",
  model: "—",
  lastTokenAt: 0,
  activeStages: new Set(),
  stageTimers: new Map(),
  voiceActive: 0,
  voiceLevel: 0,
  voiceLevelTarget: 0,
  activeSkill: "",
  knownSkills: [],
  tiers: { light: "—", moderate: "—", deep: "—" },
};

const particles = Array.from({ length: 48 }, () => ({
  angle: Math.random() * Math.PI * 2,
  radius: 1.35 + Math.random() * 1.0,
  speed: (Math.random() * 0.28 + 0.08) * (Math.random() < 0.5 ? -1 : 1),
  size: Math.random() * 1.4 + 0.5,
  phase: Math.random() * Math.PI * 2,
  depth: Math.random(),
}));
const ambient = Array.from({ length: 28 }, () => ({
  x: Math.random(),
  y: Math.random(),
  s: Math.random() * 1.6 + 0.4,
  p: Math.random() * Math.PI * 2,
  v: Math.random() * 0.02 + 0.006,
}));
const fireflies = Array.from({ length: 14 }, () => ({
  a: Math.random() * Math.PI * 2,
  r: 1.15 + Math.random() * 1.25,
  s: (0.04 + Math.random() * 0.12) * (Math.random() < 0.5 ? -1 : 1),
  bob: Math.random() * Math.PI * 2,
  tw: Math.random() * Math.PI * 2,
  size: 0.6 + Math.random() * 1.4,
  warm: Math.random(),
}));

function setLink(online) {
  if (!els.linkText) return;
  els.linkText.textContent = online ? "live" : "offline";
  els.linkText.classList.toggle("online", online);
  els.linkText.classList.toggle("offline", !online);
}

function activateStage(stage, ttl = 0) {
  state.activeStages.add(stage);
  const existing = state.stageTimers.get(stage);
  if (existing) clearTimeout(existing);
  if (ttl > 0) {
    state.stageTimers.set(stage, setTimeout(() => {
      state.activeStages.delete(stage);
      state.stageTimers.delete(stage);
    }, ttl));
  } else {
    state.stageTimers.delete(stage);
  }
}

function clearStages() {
  for (const t of state.stageTimers.values()) clearTimeout(t);
  state.stageTimers.clear();
  state.activeStages.clear();
  state.voiceActive = 0;
}

function stageActive(stage) {
  if (stage === "model") return state.current === "thinking" || state.current === "warming";
  if (stage === "input") return state.current === "listening" || state.current === "transcribing";
  if (stage === "voice") return state.voiceActive > 0 || state.current === "speaking";
  if (stage === "tools") return state.activeStages.has("tools");
  if (stage === "route") return state.activeStages.has("route");
  if (stage === "skill") return state.activeStages.has("skill");
  if (stage === "memory") return state.activeStages.has("memory");
  return false;
}

function shortModel(m) {
  if (!m) return "—";
  const s = String(m);
  return s.length > 28 ? s.slice(0, 27) + "…" : s;
}

function tierLabel(model) {
  const m = String(model || "").toLowerCase();
  if (m === String(state.tiers.deep || "").toLowerCase() || m.includes("14")) return "deep";
  if (m === String(state.tiers.moderate || "").toLowerCase() || m.includes("7")) return "moderate";
  if (m === String(state.tiers.light || "").toLowerCase() || m.includes("4") || m.includes("3")) return "light";
  return "";
}

function setState(name, detail) {
  const next = name || "idle";
  state.current = next;
  state.detail = detail || (next === "idle" ? "awaiting input" : "");
  document.body.dataset.state = next;
  if (els.stateLabel) els.stateLabel.textContent = STATE_LABELS[next] || next.toUpperCase();
  if (els.stateDetail) els.stateDetail.textContent = state.detail;
  if (next === "idle") clearStages();
}

function setRoute(label, model, tools) {
  state.route = label ? `${label}${tools === false ? " · no tools" : tools ? " · tools" : ""}` : "—";
  if (model) state.model = model;
  if (els.routeText) els.routeText.textContent = `route ${state.route}`;
  if (els.modelText) {
    const t = tierLabel(state.model);
    els.modelText.textContent = t ? `${t} · ${shortModel(state.model)}` : shortModel(state.model);
  }
  if (label) activateStage("route", 2500);
}

function resetView() {
  clearStages();
  setState("idle", "awaiting input");
  setRoute("—", "—");
  state.lastTokenAt = 0;
  state.voiceLevel = 0;
  state.voiceLevelTarget = 0;
}

function handleEvent(event) {
  const data = event.data || {};
  switch (event.type) {
    case "session":
      state.tiers.light = data.light || data.quick || "—";
      state.tiers.moderate = data.moderate || "—";
      state.tiers.deep = data.deep || "—";
      if (els.tiersText) {
        els.tiersText.textContent = `light ${shortModel(state.tiers.light)} · moderate ${shortModel(state.tiers.moderate)} · deep ${shortModel(state.tiers.deep)}`;
      }
      setRoute("—", `${state.tiers.light} / ${state.tiers.moderate} / ${state.tiers.deep}`);
      if (Array.isArray(data.skills_list)) {
        state.knownSkills = data.skills_list.map(s => s.name || s).filter(Boolean).slice(0, 8);
      }
      break;
    case "skill_saved":
      if (data.name && !state.knownSkills.includes(data.name)) state.knownSkills.unshift(data.name);
      if (data.name) state.activeSkill = data.name;
      state.knownSkills = state.knownSkills.slice(0, 8);
      activateStage("skill", 5000);
      break;
    case "memory":
      activateStage("memory", 3500);
      break;
    case "notification":
      break;
    case "action":
      activateStage("tools", 2500);
      break;
    case "user":
      activateStage("input", 1200);
      break;
    case "route":
      setRoute(data.label, data.model, data.tools);
      break;
    case "state":
      setState(data.state, data.detail);
      break;
    case "token":
      state.lastTokenAt = performance.now();
      break;
    case "tool":
      if (data.status === "start") {
        activateStage("tools");
        if (data.name === "read_skill" || data.name === "save_skill") {
          activateStage("skill");
          if (data.args && data.args.name) {
            state.activeSkill = String(data.args.name);
            if (!state.knownSkills.includes(state.activeSkill)) state.knownSkills.unshift(state.activeSkill);
            state.knownSkills = state.knownSkills.slice(0, 8);
          }
        }
        if (data.name === "remember" || data.name === "forget" || data.name === "list_memories") {
          activateStage("memory", 3500);
        }
      } else {
        activateStage("tools", 2500);
        if (data.name === "read_skill" || data.name === "save_skill") {
          activateStage("skill", 4500);
        }
        if (data.name === "remember" || data.name === "forget" || data.name === "list_memories") {
          activateStage("memory", 3500);
        }
      }
      break;
    case "voice":
      if (data.action === "start") state.voiceActive += 1;
      else if (data.action === "end") {
        state.voiceActive = Math.max(0, state.voiceActive - 1);
        state.voiceLevelTarget = 0;
      } else if (data.action === "level") {
        const lvl = Number(data.level || 0);
        state.voiceLevelTarget = Math.max(state.voiceLevelTarget * 0.6, Math.min(1, lvl));
      }
      break;
    case "assistant":
      if (state.current === "thinking") setState("idle", "awaiting input");
      state.activeStages.delete("tools");
      break;
    case "error":
      setState("error", (data.message || "error").slice(0, 120));
      break;
    default:
      break;
  }
}

function resizeCanvas() {
  if (!els.canvas || !ctx) return;
  const rect = els.canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  els.canvas.width = Math.max(1, Math.round(rect.width * dpr));
  els.canvas.height = Math.max(1, Math.round(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function draw(now) {
  if (!els.canvas || !ctx) { requestAnimationFrame(draw); return; }
  const w = els.canvas.clientWidth;
  const h = els.canvas.clientHeight;
  if (!w || !h) { requestAnimationFrame(draw); return; }

  const t = reduceMotion ? 0 : now / 1000;
  const cx = w / 2;
  const cy = h * 0.43;
  const minDim = Math.min(w, h);
  const base = Math.max(50, minDim * (minDim < 420 ? 0.155 : 0.18));
  const ui = Math.max(0.85, Math.min(1.35, minDim / 520));
  const palette = PALETTES[state.current] || PALETTES.idle;
  const tokenHeat = Math.max(0, 1 - (now - state.lastTokenAt) / 700);
  const flicker = reduceMotion ? 1 : 0.96 + 0.04 * Math.sin(t * 9) * Math.sin(t * 3.7 + 1.3);
  const breath = reduceMotion ? 0.5 : (0.5 + 0.5 * Math.sin(t * 1.1));
  const heartbeat = reduceMotion ? 0 : Math.pow(Math.max(0, Math.sin(t * 1.3)), 8) * 0.12;
  const presence = state.current === "idle" ? (0.08 + breath * 0.06 + heartbeat) : 0;
  const energy =
    (state.current === "thinking" || state.current === "warming" ? 0.7 :
      state.current === "speaking" ? 0.95 :
        state.current === "listening" || state.current === "transcribing" ? 0.55 :
          state.current === "error" ? 0.35 : 0.18) + tokenHeat * 0.2 + presence;

  ctx.clearRect(0, 0, w, h);

  // Grid behind orb: tight asymmetric grid (slants down to the left), fading toward edges
  ctx.save();
  const gridR = Math.max(w, h) * 0.68;
  function gridPass(stepX, stepY, alphaCenter, slant, width = 1) {
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, gridR);
    g.addColorStop(0, `rgba(150,255,215,${alphaCenter})`);
    g.addColorStop(0.35, `rgba(150,255,215,${alphaCenter * 0.5})`);
    g.addColorStop(0.65, `rgba(150,255,215,${alphaCenter * 0.18})`);
    g.addColorStop(1, "rgba(150,255,215,0)");
    ctx.strokeStyle = g;
    ctx.lineWidth = width;
    ctx.beginPath();
    const ox = ((cx % stepX) + stepX) % stepX;
    const oy = ((cy % stepY) + stepY) % stepY;
    // vertical lines (tighter/asymmetric spacing relative to horizontal)
    for (let x = -stepX; x <= w + stepX; x += stepX) {
      const xx = x + ox;
      ctx.moveTo(xx, -4);
      ctx.lineTo(xx, h + 4);
    }
    // horizontal lines slanting downward toward the left (right side higher, left side lower)
    for (let y = -stepY * 3; y <= h + stepY * 3; y += stepY) {
      const yy = y + oy;
      ctx.moveTo(0, yy + slant);
      ctx.lineTo(w, yy);
    }
    ctx.stroke();
  }
  const fineX = Math.max(10, Math.round(minDim / 18));
  const fineY = Math.round(fineX * 1.38);
  const fineSlant = Math.max(4, fineY * 0.42); // down to the left
  gridPass(fineX, fineY, 0.045, fineSlant, 1);
  gridPass(fineX * 3, fineY * 3, 0.06, fineSlant * 3, 1);
  ctx.restore();

  // ambient field (living, softer)
  ctx.save();
  for (const a of ambient) {
    const ax = ((a.x + Math.sin(t * a.v + a.p) * 0.04) % 1) * w;
    const ay = ((a.y + Math.cos(t * a.v * 0.7 + a.p) * 0.03 + (t * a.v * 0.12) % 1)) * h;
    const tw = 0.5 + 0.5 * Math.sin(t * 1.1 + a.p);
    ctx.globalAlpha = 0.02 + tw * 0.045 * (0.7 + energy * 0.35 + presence);
    ctx.fillStyle = a.s > 1.2 ? palette.core : palette.accent;
    ctx.beginPath();
    ctx.arc(ax, ay, a.s, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  const glow = ctx.createRadialGradient(cx, cy, base * 0.2, cx, cy, base * 3.6);
  glow.addColorStop(0, palette.glow);
  glow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = 0.95 * flicker;
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);
  ctx.globalAlpha = 1;

  // hologram base/projection + reflection (original, not stacked)
  ctx.save();
  ctx.translate(cx, cy + base * 1.32);
  ctx.globalAlpha = (0.14 + energy * 0.13) * flicker;
  ctx.strokeStyle = palette.core;
  ctx.lineWidth = Math.max(1, 1.2 * ui);
  for (let i = 0; i < 3; i++) {
    const rx = base * (1.25 + i * 0.4);
    const ry = base * (0.22 + i * 0.06);
    ctx.beginPath();
    ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.globalAlpha *= 0.8;
  ctx.beginPath();
  ctx.moveTo(-base * 0.03, -base * 0.18);
  ctx.lineTo(-base * 0.95, -base * 1.02);
  ctx.moveTo(base * 0.03, -base * 0.18);
  ctx.lineTo(base * 0.95, -base * 1.02);
  ctx.stroke();
  const pool = ctx.createRadialGradient(0, 0, base * 0.1, 0, 0, base * 1.6);
  pool.addColorStop(0, palette.glow);
  pool.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = 0.18 + energy * 0.1;
  ctx.fillStyle = pool;
  ctx.beginPath();
  ctx.ellipse(0, base * 0.06, base * 1.5, base * 0.28, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // orbit rings + hologram ticks (original)
  ctx.save();
  ctx.translate(cx, cy);
  for (let i = 0; i < 2; i++) {
    const rot = t * (0.06 + i * 0.03) * (i % 2 ? 1 : -1);
    const rx = base * (1.72 + i * 0.3);
    const ry = base * (1.22 + i * 0.12);
    ctx.globalAlpha = 0.08 + energy * 0.12;
    ctx.strokeStyle = palette.ring;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.ellipse(0, 0, rx, ry, rot, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 0.12 + energy * 0.16;
    ctx.strokeStyle = palette.core;
    ctx.beginPath();
    ctx.ellipse(0, 0, rx, ry, rot, t * 0.5 + i, t * 0.5 + i + 0.8);
    ctx.stroke();
  }
  const tickR = base * 1.48;
  const tickRot = t * 0.12;
  ctx.strokeStyle = palette.accent;
  ctx.lineWidth = 1;
  for (let i = 0; i < 48; i++) {
    const a = tickRot + (i / 48) * Math.PI * 2;
    const major = i % 6 === 0;
    const len = (major ? base * 0.06 : base * 0.03) * (1 + 0.15 * Math.sin(t * 0.8 + i));
    ctx.globalAlpha = (major ? 0.06 : 0.03) + energy * 0.06;
    ctx.beginPath();
    ctx.moveTo(Math.cos(a) * tickR, Math.sin(a) * tickR * 0.74);
    ctx.lineTo(Math.cos(a) * (tickR + len), Math.sin(a) * (tickR + len) * 0.74);
    ctx.stroke();
  }
  ctx.restore();

  // liquid/audio state (original)
  state.voiceLevel += (state.voiceLevelTarget - state.voiceLevel) * 0.32;
  state.voiceLevelTarget *= 0.88;
  const audio = state.voiceLevel;
  const speakingBoost = (state.current === "speaking" || state.voiceActive > 0) ? 1 : 0;

  // particles (prominent, toned down when speaking)
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  const speakDim = speakingBoost ? 0.55 : 1.0;
  for (const p of particles) {
    const speed = p.speed * (1 + audio * 0.6) * (speakingBoost ? 0.85 : 1.0);
    const a = p.angle + t * speed;
    const r = base * p.radius + Math.sin(t * (1.0 + audio * 0.5) + p.phase) * base * (0.04 + audio * 0.05);
    const x = cx + Math.cos(a) * r;
    const y = cy + Math.sin(a) * r * 0.74;
    ctx.globalAlpha = (0.14 + p.depth * 0.30 * (0.6 + energy * 0.45 + audio * 0.25)) * speakDim;
    ctx.fillStyle = palette.accent;
    ctx.beginPath();
    ctx.arc(x, y, p.size * (1.2 + audio * 0.35) * (speakingBoost ? 0.9 : 1.0), 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  // fireflies (soul/warmth)
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (const f of fireflies) {
    const aa = f.a + t * f.s * (state.current === "thinking" ? 0.7 : state.current === "speaking" ? 1.3 : 1.0);
    const rr = base * f.r + Math.sin(t * 0.7 + f.bob) * base * 0.08;
    const x = cx + Math.cos(aa) * rr;
    const y = cy + Math.sin(aa) * rr * 0.74 + Math.sin(t * 0.9 + f.bob) * base * 0.03;
    const tw = 0.35 + 0.65 * Math.pow(0.5 + 0.5 * Math.sin(t * (1.2 + f.tw) + f.tw), 2);
    const alpha = (0.06 + tw * 0.18) * (0.7 + energy * 0.5) * (speakingBoost ? 0.8 : 1.0);
    const col = f.warm > 0.55 ? palette.accent : (f.warm > 0.25 ? palette.core : "#fff6d8");
    ctx.globalAlpha = alpha;
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.arc(x, y, f.size * (0.9 + tw * 0.8), 0, Math.PI * 2);
    ctx.fill();

  }
  ctx.restore();

  // liquid core: inner orb more stable, outer fluid/waves mode-reactive
  const mode = state.current;
  let timeScale = 1.0;
  let motion = 1.0;
  let radiusMotion = 1.0;
  if (mode === "thinking" || mode === "warming") { timeScale = 0.55; motion = 0.45; radiusMotion = 0.35; }
  else if (mode === "speaking") { timeScale = 1.85; motion = 1.35; radiusMotion = 1.0; }
  else if (mode === "listening" || mode === "transcribing") { timeScale = 1.1; motion = 0.8; radiusMotion = 0.55; }
  else if (mode === "error") { timeScale = 1.5; motion = 1.1; radiusMotion = 0.8; }
  else { timeScale = 0.8; motion = 0.7; radiusMotion = 0.45; } // idle

  const lt = t * timeScale;
  const idleBreath = mode === "idle" ? (Math.sin(t * 0.8) * 0.02 + 0.02) : 0;
  const outerLiquidAmp = (0.08 + energy * 0.05 + audio * 0.30 + speakingBoost * 0.07 + idleBreath) * base * motion;
  const innerLiquidAmp = outerLiquidAmp * 0.38; // inner orb more stable
  const radius = base * (1 + Math.sin(lt * 1.1) * 0.012 * radiusMotion + Math.sin(t * 0.7 + 1.2) * 0.006 * radiusMotion + energy * 0.015 + audio * 0.06 + idleBreath * 0.3);

  const spin = (mode === "thinking" || mode === "warming") ? (t * 0.55) : 0;

  function blobPath(rBase, phase, ampScale = 1, ampOverride = null, spinOffset = 0) {
    const points = 96;
    const amp = (ampOverride != null ? ampOverride : outerLiquidAmp) * ampScale;
    ctx.beginPath();
    for (let i = 0; i <= points; i++) {
      const a = (i / points) * Math.PI * 2 + spin + spinOffset;
      const n =
        Math.sin(a * 2 + lt * 0.9 + phase) * 0.35 +
        Math.sin(a * 3 - lt * 1.1 + phase * 1.3) * 0.30 +
        Math.sin(a * 5 + lt * 0.7 + phase * 0.7) * 0.20 +
        Math.sin(a * 8 - lt * 0.5) * 0.10 +
        Math.sin(lt * 0.35 + phase) * 0.05;
      const wobble = 1 + (n * amp) / Math.max(20, rBase);
      const rr = rBase * wobble;
      const x = cx + Math.cos(a) * rr;
      const y = cy + Math.sin(a) * rr * 0.985;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
  }

  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  // outer fluid shells/waves keep dynamic motion
  const shells = [
    { r: 1.34, phase: 1.4, a: 0.06, amp: 1.25, color: palette.glow },
    { r: 1.22, phase: 0.8, a: 0.10, amp: 1.18, color: palette.glow },
    { r: 1.12, phase: 2.1, a: 0.08, amp: 1.10, color: palette.core },
  ];
  for (const s of shells) {
    ctx.globalAlpha = (s.a + audio * 0.05) * flicker;
    ctx.fillStyle = s.color;
    blobPath(radius * (s.r + audio * 0.04), s.phase + lt * 0.15, s.amp + audio * 0.25, outerLiquidAmp);
    ctx.fill();
  }
  ctx.globalAlpha = (0.13 + audio * 0.07) * flicker;
  ctx.fillStyle = palette.core;
  blobPath(radius * (1.04 + audio * 0.03), 0.0, 1.05 + audio * 0.25, outerLiquidAmp);
  ctx.fill();
  ctx.globalAlpha = (0.10 + audio * 0.06) * flicker;
  ctx.fillStyle = "#9ffcff";
  blobPath(radius * (1.00 + audio * 0.02), 1.7, 0.95 + audio * 0.22, outerLiquidAmp);
  ctx.fill();
  ctx.globalAlpha = (0.07 + audio * 0.04) * flicker;
  ctx.fillStyle = palette.accent;
  blobPath(radius * 0.96, 3.1, 0.9 + audio * 0.2, outerLiquidAmp * 0.9);
  ctx.fill();

  // inner orb body more stable
  const core = ctx.createRadialGradient(cx - radius * 0.28, cy - radius * 0.35, radius * 0.05, cx, cy, radius * 1.18);
  core.addColorStop(0, "rgba(245,255,255,0.90)");
  core.addColorStop(0.18, palette.core);
  core.addColorStop(0.55, palette.core);
  core.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = (0.72 + audio * 0.08) * flicker;
  ctx.fillStyle = core;
  blobPath(radius, 0.4, 1.0 + audio * 0.2, innerLiquidAmp);
  ctx.fill();

  ctx.globalCompositeOperation = "screen";
  const inner = ctx.createRadialGradient(cx - radius * 0.15, cy - radius * 0.1, radius * 0.02, cx, cy, radius * 0.95);
  inner.addColorStop(0, "rgba(255,255,255,0.35)");
  inner.addColorStop(0.45, "rgba(180,245,255,0.10)");
  inner.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = (0.28 + audio * 0.12) * flicker;
  ctx.fillStyle = inner;
  blobPath(radius * 0.86, 2.4, 0.85 + audio * 0.12, innerLiquidAmp);
  ctx.fill();

  ctx.globalAlpha = (0.14 + audio * 0.08) * flicker;
  ctx.strokeStyle = "rgba(220,255,255,0.55)";
  ctx.lineWidth = Math.max(1, ui * 0.9);
  blobPath(radius * 0.72, 5.0, 0.75 + audio * 0.12, innerLiquidAmp * 0.9);
  ctx.stroke();
  blobPath(radius * 0.56, 4.1, 0.7 + audio * 0.1, innerLiquidAmp * 0.8);
  ctx.stroke();

  // internal fluid highlights (mode-dependent, alive)
  ctx.globalAlpha = 0.14 + energy * 0.10 + audio * 0.14 + presence * 0.2;
  ctx.strokeStyle = "rgba(235,255,255,0.65)";
  ctx.lineWidth = Math.max(1, ui);
  let ripples = 3, rippleSpeed = 1.2, rippleAmp = 3 + audio * 8, rippleLift = 5 + audio * 12;
  if (mode === "thinking" || mode === "warming") { ripples = 3; rippleSpeed = 0.65; rippleAmp = 2 + audio * 3; rippleLift = 4 + audio * 5; }
  else if (mode === "speaking") { ripples = 6; rippleSpeed = 2.8; rippleAmp = 5 + audio * 16; rippleLift = 9 + audio * 22; }
  else if (mode === "listening" || mode === "transcribing") { ripples = 4; rippleSpeed = 1.5; rippleAmp = 3 + audio * 7; rippleLift = 5 + audio * 9; }
  else if (mode === "error") { ripples = 5; rippleSpeed = 2.4; rippleAmp = 4 + audio * 8; rippleLift = 7 + audio * 12; }
  else { ripples = 3; rippleSpeed = 0.9; rippleAmp = 2.5 + breath * 2; rippleLift = 4 + breath * 3; }
  for (let k = 0; k < ripples; k++) {
    const yy = cy - radius * 0.5 + k * radius * (0.95 / Math.max(1, ripples)) + Math.sin(lt * rippleSpeed + k) * rippleAmp;
    const half = Math.max(6, radius * (0.82 - Math.abs(k - (ripples - 1) / 2) * 0.1));
    ctx.beginPath();
    ctx.moveTo(cx - half, yy);
    ctx.quadraticCurveTo(cx + Math.sin(lt * (rippleSpeed + 0.7) + k) * radius * (0.16 + audio * 0.10), yy - rippleLift, cx + half, yy);
    ctx.stroke();
  }

  ctx.globalAlpha = 0.30 + audio * 0.15;
  ctx.fillStyle = "rgba(255,255,255,0.80)";
  ctx.beginPath();
  ctx.ellipse(cx - radius * 0.22, cy - radius * 0.28, radius * 0.22, radius * 0.12, -0.6, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 0.12 + audio * 0.08;
  ctx.beginPath();
  ctx.ellipse(cx + radius * 0.18, cy + radius * 0.05, radius * 0.12, radius * 0.07, 0.4, 0, Math.PI * 2);
  ctx.fill();


  ctx.restore();

  // listening ripples (original)
  if (state.current === "listening" || state.current === "transcribing") {
    ctx.save();
    ctx.translate(cx, cy);
    for (let i = 0; i < 3; i++) {
      const p = ((t * 0.45) + i / 3) % 1;
      const rr = base * (1.25 + p * 0.9);
      ctx.globalAlpha = (1 - p) * (0.12 + energy * 0.08);
      ctx.strokeStyle = palette.ring;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.ellipse(0, 0, rr, rr * 0.74, 0, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  // voice waveform ring when speaking (original)
  if (speakingBoost || audio > 0.02) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.globalAlpha = 0.12 + audio * 0.25;
    ctx.strokeStyle = palette.accent;
    ctx.lineWidth = Math.max(1, ui);
    ctx.beginPath();
    const bars = 64;
    for (let i = 0; i <= bars; i++) {
      const a = (i / bars) * Math.PI * 2;
      const wave = Math.sin(a * 8 - t * 6) * Math.sin(a * 3 + t * 2);
      const r = base * 1.55 + (wave * 0.5 + 0.5) * base * (0.06 + audio * 0.18);
      const x = Math.cos(a) * r;
      const y = Math.sin(a) * r * 0.74;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.stroke();
    ctx.restore();
  }

  // stage ring (original + memory) - shows where AI is currently working
  const stages = [
    { key: "input", label: "Input" },
    { key: "route", label: "Route" },
    { key: "tools", label: "Tools" },
    { key: "skill", label: "Skill" },
    { key: "memory", label: "Memory" },
    { key: "model", label: "Model" },
    { key: "voice", label: "Voice" },
  ];
  const orbit = base * 2.12;
  const labelFont = Math.round(11 * ui);
  for (let i = 0; i < stages.length; i++) {
    const st = stages[i];
    const angle = -Math.PI / 2 + i * ((Math.PI * 2) / stages.length);
    const x = cx + Math.cos(angle) * orbit;
    const y = cy + Math.sin(angle) * orbit * 0.74;
    const active = stageActive(st.key);
    const dotR = (active ? 4.2 : 3) * ui;

    const ix = cx + Math.cos(angle) * base * 1.15;
    const iy = cy + Math.sin(angle) * base * 1.15 * 0.74;
    ctx.save();
    ctx.globalAlpha = active ? 0.55 : 0.1;
    ctx.strokeStyle = active ? palette.core : palette.ring;
    ctx.lineWidth = Math.max(1, 1.1 * ui);
    ctx.beginPath();
    ctx.moveTo(ix, iy);
    ctx.lineTo(x, y);
    ctx.stroke();

    if (active) {
      const flow = (t * (0.35 + energy * 0.25) + i * 0.17) % 1;
      const px = ix + (x - ix) * flow;
      const py = iy + (y - iy) * flow;
      ctx.globalAlpha = 0.9;
      ctx.fillStyle = palette.accent;
      ctx.beginPath();
      ctx.arc(px, py, 2.2 * ui, 0, Math.PI * 2);
      ctx.fill();

      const g = ctx.createRadialGradient(x, y, 0, x, y, 18 * ui);
      g.addColorStop(0, palette.glow);
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, 18 * ui, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalAlpha = active ? 0.98 : 0.4;
    ctx.fillStyle = active ? palette.core : "rgba(130,175,195,0.55)";
    ctx.beginPath();
    ctx.arc(x, y, dotR, 0, Math.PI * 2);
    ctx.fill();

    const lx = cx + Math.cos(angle) * (orbit + 16 * ui);
    const ly = cy + Math.sin(angle) * (orbit * 0.74 + 16 * ui);
    ctx.textAlign = Math.abs(Math.cos(angle)) < 0.2 ? "center" : (Math.cos(angle) > 0 ? "left" : "right");
    ctx.textBaseline = "middle";
    ctx.fillStyle = active ? palette.core : "rgba(150,195,210,0.5)";
    ctx.font = `${active ? 600 : 500} ${labelFont}px Inter, "Segoe UI", system-ui, sans-serif`;
    ctx.fillText(st.label, lx, ly);

    // dynamic skill branches
    if (st.key === "skill" && state.knownSkills.length) {
      const dir = Math.cos(angle) >= 0 ? 1 : -1;
      const baseAng = angle + (dir * 0.18);
      const spread = 0.22;
      const list = state.knownSkills.slice(0, 5);
      for (let j = 0; j < list.length; j++) {
        const name = list[j];
        const isActive = active && state.activeSkill === name;
        const a2 = baseAng + (j - (list.length - 1) / 2) * spread * 0.55 * (dir || 1);
        const len = (26 + j * 10) * ui;
        const sx = x + Math.cos(a2) * len;
        const sy = y + Math.sin(a2) * len * 0.9;
        ctx.globalAlpha = isActive ? 0.55 : 0.18;
        ctx.strokeStyle = isActive ? palette.core : palette.ring;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.quadraticCurveTo(x + Math.cos(a2) * len * 0.45, y + Math.sin(a2) * len * 0.45, sx, sy);
        ctx.stroke();
        ctx.globalAlpha = isActive ? 0.95 : 0.35;
        ctx.fillStyle = isActive ? palette.accent : "rgba(150,195,210,0.55)";
        ctx.beginPath();
        ctx.arc(sx, sy, isActive ? 2.6 * ui : 1.8 * ui, 0, Math.PI * 2);
        ctx.fill();
        if (isActive || (active && j === 0)) {
          const tx = sx + dir * 6 * ui;
          const ty = sy - 2 * ui;
          ctx.font = `${isActive ? 500 : 400} ${Math.max(8, labelFont - 2)}px Inter, "Segoe UI", system-ui, sans-serif`;
          ctx.textAlign = dir > 0 ? "left" : "right";
          ctx.globalAlpha = isActive ? 0.9 : 0.45;
          ctx.fillStyle = isActive ? palette.accent : "rgba(170,210,225,0.6)";
          const txt = name.length > 18 ? name.slice(0, 17) + "…" : name;
          ctx.fillText(txt, tx, ty);
        }
      }
    }
    ctx.restore();
  }

  requestAnimationFrame(draw);
}

function connect() {
  if (!window.EventSource) {
    setLink(false);
    setState("error", "EventSource not supported");
    return;
  }
  const source = new EventSource("/events");
  source.onopen = () => { resetView(); setLink(true); };
  source.onmessage = (msg) => {
    try { handleEvent(JSON.parse(msg.data)); } catch (_) { }
  };
  source.onerror = () => setLink(false);
}

if (window.ResizeObserver && els.canvas) new ResizeObserver(resizeCanvas).observe(els.canvas);
window.addEventListener("resize", resizeCanvas);
function applyDisplayMode() {
  const params = new URLSearchParams(window.location.search);
  const bg = (params.get("bg") || "").toLowerCase();
  const transparent = params.get("transparent");
  const isTransparent = bg === "transparent" || transparent === "1" || transparent === "true";
  if (isTransparent) document.body.style.background = "transparent";
}
applyDisplayMode();
resizeCanvas();
resetView();
requestAnimationFrame(draw);
connect();
