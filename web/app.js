"use strict";

const els = {
  canvas: document.getElementById("orb"),
  stateLabel: document.getElementById("state-label"),
  stateDetail: document.getElementById("state-detail"),
  routeText: document.getElementById("route-text"),
  modelText: document.getElementById("model-text"),
  linkText: document.getElementById("link-text"),
  tiersText: document.getElementById("tiers-text"),
  uploadPanel: document.getElementById("upload-panel"),
  uploadToggle: document.getElementById("upload-toggle"),
  uploadFile: document.getElementById("upload-file"),
  uploadBtn: document.getElementById("upload-btn"),
  uploadStatus: document.getElementById("upload-status"),
  uploadList: document.getElementById("upload-list"),
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

// Palettes inspired by MIO: Memories in Orbit (lighter, vivid tones)
const PALETTES = {
  idle: { core: "#8fd3ff", glow: "rgba(120, 190, 255, 0.10)", ring: "rgba(143,211,255,0.42)", accent: "#eef8ff" },
  listening: { core: "#7ff5d8", glow: "rgba(110,235,200,0.10)", ring: "rgba(127,245,216,0.44)", accent: "#f2fff9" },
  transcribing: { core: "#7ff5d8", glow: "rgba(110, 235, 200, 0.10)", ring: "rgba(127,245,216,0.44)", accent: "#f2fff9" },
  thinking: { core: "#ffc86a", glow: "rgba(255,185,90,0.10)", ring: "rgba(255,200,106,0.44)", accent: "#fff4de" },
  speaking: { core: "#c79bff", glow: "rgba(185, 140, 255, 0.10)", ring: "rgba(199,155,255,0.46)", accent: "#f7efff" },
  warming: { core: "#ffd59a", glow: "rgba(245,190,120,0.10)", ring: "rgba(255,213,154,0.40)", accent: "#fff6e8" },
  error: { core: "#ff8f87", glow: "rgba(255,120,110,0.10)", ring: "rgba(255,143,135,0.44)", accent: "#ffeceb" },
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
  knowledge: { memories: 0, skills: 0, uploads: 0 },
  ripples: [],
  lastRippleAt: 0,
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

function spawnRipple(kind = "state", strength = 1) {
  if (reduceMotion) return;
  const now = performance.now();
  if (now - state.lastRippleAt < 120 && state.ripples.length > 6) return;
  state.lastRippleAt = now;
  state.ripples.push({
    kind,
    t: now,
    strength: Math.max(0.4, Math.min(1.4, strength)),
    dur: kind === "learn" ? 1800 : kind === "memory" ? 1500 : 1200,
  });
  if (state.ripples.length > 10) state.ripples.splice(0, state.ripples.length - 10);
}

function setState(name, detail) {
  const prev = state.current;
  const next = name || "idle";
  state.current = next;
  state.detail = detail || (next === "idle" ? "awaiting input" : "");
  document.body.dataset.state = next;
  if (els.stateLabel) els.stateLabel.textContent = STATE_LABELS[next] || next.toUpperCase();
  if (els.stateDetail) els.stateDetail.textContent = state.detail;
  if (next === "idle") clearStages();
  if (prev !== next) {
    if (next === "listening" || next === "transcribing") spawnRipple("hear", 0.9);
    else if (next === "thinking" || next === "warming") spawnRipple("think", 1.0);
    else if (next === "speaking") spawnRipple("voice", 1.05);
    else if (next === "error") spawnRipple("error", 0.8);
  }
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
      spawnRipple("learn", 1.0);
      loadKnowledge();
      break;
    case "memory":
      activateStage("memory", 3500);
      spawnRipple(data.action === "upload" ? "learn" : "memory", data.action === "ingest_skill" ? 1.15 : 0.9);
      if (data.action === "upload" || data.action === "ingest_skill") loadKnowledge();
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
          if (data.status === "end" && data.ok !== false) { spawnRipple("learn", 0.95); loadKnowledge(); }
        }
        if (data.name === "remember" || data.name === "forget" || data.name === "list_memories") {
          activateStage("memory", 3500);
          if (data.status === "end" && data.ok !== false && (data.name === "remember" || data.name === "forget")) { spawnRipple("memory", 0.9); loadKnowledge(); }
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
  const gridR = Math.max(w, h) * 0.62;
  function gridPass(stepX, stepY, alphaCenter, slant, width = 1) {
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, gridR);
    g.addColorStop(0, `rgba(150,255,215,${alphaCenter})`);
    g.addColorStop(0.22, `rgba(150,255,215,${alphaCenter * 0.45})`);
    g.addColorStop(0.45, `rgba(150,255,215,${alphaCenter * 0.14})`);
    g.addColorStop(0.7, `rgba(150,255,215,${alphaCenter * 0.04})`);
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

  // ambient field (living, softer, painterly motes)
  ctx.save();
  for (const a of ambient) {
    const ax = ((a.x + Math.sin(t * a.v + a.p) * 0.04) % 1) * w;
    const ay = ((a.y + Math.cos(t * a.v * 0.7 + a.p) * 0.03 + (t * a.v * 0.12) % 1)) * h;
    const tw = 0.5 + 0.5 * Math.sin(t * 1.05 + a.p);
    ctx.globalAlpha = 0.015 + tw * 0.035 * (0.7 + energy * 0.3 + presence);
    ctx.fillStyle = a.s > 1.2 ? palette.core : palette.accent;
    ctx.beginPath();
    ctx.arc(ax, ay, a.s * 1.15, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  // subtle vignette (MIO-inspired atmosphere)
  ctx.save();
  const vg = ctx.createRadialGradient(cx, cy, minDim * 0.15, cx, cy, Math.max(w, h) * 0.75);
  vg.addColorStop(0, "rgba(0,0,0,0)");
  vg.addColorStop(1, "rgba(8,12,14,0.22)");
  ctx.fillStyle = vg;
  ctx.fillRect(0, 0, w, h);
  ctx.restore();

  // subtle minimal framing / anchor
  ctx.save();
  const frameR = Math.min(w, h) * 0.46;
  const frameA = 0.06 + energy * 0.04;
  ctx.strokeStyle = palette.ring;
  ctx.globalAlpha = frameA;
  ctx.lineWidth = Math.max(1, ui * 0.9);
  const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
  for (const [sx, sy] of corners) {
    const fx = cx + sx * frameR * 0.82;
    const fy = cy + sy * frameR * 0.62;
    const len = Math.max(14, minDim * 0.03);
    ctx.beginPath();
    ctx.moveTo(fx - sx * len, fy);
    ctx.lineTo(fx, fy);
    ctx.lineTo(fx, fy - sy * len);
    ctx.stroke();
  }
  // faint reticle arcs
  ctx.globalAlpha = frameA * 0.7;
  ctx.beginPath(); ctx.arc(cx, cy, frameR * 0.92, -Math.PI * 0.78, -Math.PI * 0.58); ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, frameR * 0.92, -Math.PI * 0.42, -Math.PI * 0.22); ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, frameR * 0.92, Math.PI * 0.22, Math.PI * 0.42); ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, frameR * 0.92, Math.PI * 0.58, Math.PI * 0.78); ctx.stroke();
  ctx.globalAlpha = frameA * 0.45;
  const tickL = Math.max(6, minDim * 0.012);
  for (let i = 0; i < 4; i++) {
    const a = i * Math.PI / 2;
    const x1 = cx + Math.cos(a) * frameR * 0.985;
    const y1 = cy + Math.sin(a) * frameR * 0.985;
    const x2 = cx + Math.cos(a) * (frameR * 0.985 - tickL);
    const y2 = cy + Math.sin(a) * (frameR * 0.985 - tickL);
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  }
  ctx.restore();


  const glow = ctx.createRadialGradient(cx, cy, base * 0.15, cx, cy, base * 3.0);
  glow.addColorStop(0, palette.core);
  glow.addColorStop(0.18, palette.glow);
  glow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = 0.38 * flicker;
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);
  ctx.globalAlpha = 1;

  // hairpin wire strands (top, MIO-inspired)
  ctx.save();
  ctx.translate(cx, cy - base * 1.12);
  ctx.lineCap = "round";
  for (let i = 0; i < 8; i++) {
    const side = i < 4 ? -1 : 1;
    const idx = i % 4;
    const sx = side * base * (0.04 + idx * 0.18);
    const sy = 0;
    const reach = base * (0.22 + idx * 0.12);
    const sway = Math.sin(t * (0.45 + idx * 0.08) + i + 1.2) * base * 0.045;
    const ex = sx + side * base * (0.08 + idx * 0.1) + sway;
    const ey = -reach;
    const alpha = 0.12 + energy * 0.06;
    ctx.strokeStyle = palette.core;
    ctx.globalAlpha = alpha;
    ctx.lineWidth = Math.max(0.8, (1.3 - idx * 0.12) * ui);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.bezierCurveTo(sx + side * base * 0.05, sy - reach * 0.35, sx + side * base * 0.08 + sway * 0.6, sy - reach * 0.7, ex, ey);
    ctx.stroke();
    // hairpin hook tip
    const tipAng = Math.atan2(ey - (sy - reach * 0.7), ex - (sx + side * base * 0.08 + sway * 0.6));
    const hookDir = side > 0 ? -1 : 1;
    const hx = ex + Math.cos(tipAng + hookDir * 1.2) * base * 0.045;
    const hy = ey + Math.sin(tipAng + hookDir * 1.2) * base * 0.045;
    ctx.strokeStyle = palette.accent;
    ctx.lineWidth = Math.max(0.7, (1.0 - idx * 0.1) * ui);
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.quadraticCurveTo(ex + Math.cos(tipAng + hookDir * 0.6) * base * 0.04, ey + Math.sin(tipAng + hookDir * 0.6) * base * 0.04, hx, hy);
    ctx.stroke();
    // glowing tip
    ctx.save();
    ctx.shadowBlur = 8 * ui;
    ctx.shadowColor = palette.accent;
    ctx.fillStyle = palette.accent;
    ctx.globalAlpha = alpha + 0.1;
    ctx.beginPath();
    ctx.arc(ex, ey, Math.max(1.0, 1.8 * ui - idx * 0.15), 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
  ctx.restore();

  // hologram base/projection + reflection (no rings)
  ctx.save();
  ctx.translate(cx, cy + base * 1.32);
  ctx.globalAlpha = (0.14 + energy * 0.13) * flicker;
  ctx.strokeStyle = palette.core;
  ctx.lineWidth = Math.max(1, 1.2 * ui);
  ctx.beginPath();
  ctx.moveTo(-base * 0.03, -base * 0.18);
  ctx.lineTo(-base * 0.95, -base * 1.02);
  ctx.moveTo(base * 0.03, -base * 0.18);
  ctx.lineTo(base * 0.95, -base * 1.02);
  ctx.stroke();
  const pool = ctx.createRadialGradient(0, 0, base * 0.1, 0, 0, base * 1.6);
  pool.addColorStop(0, palette.glow);
  pool.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = 0.08 + energy * 0.05;
  ctx.fillStyle = pool;
  ctx.beginPath();
  ctx.ellipse(0, base * 0.06, base * 1.5, base * 0.28, 0, 0, Math.PI * 2);
  ctx.fill();

  // hairpin wire strands (bottom, MIO-inspired)
  ctx.lineCap = "round";
  for (let i = 0; i < 8; i++) {
    const side = i < 4 ? -1 : 1;
    const idx = i % 4;
    const sx = side * base * (0.04 + idx * 0.2);
    const sy = base * 0.02;
    const reach = base * (0.3 + idx * 0.14);
    const sway = Math.sin(t * (0.42 + idx * 0.08) + i) * base * 0.05;
    const ex = sx + side * base * (0.12 + idx * 0.14) + sway;
    const ey = sy + reach;
    const alpha = 0.14 + energy * 0.07;
    ctx.strokeStyle = palette.core;
    ctx.globalAlpha = alpha;
    ctx.lineWidth = Math.max(0.9, (1.5 - idx * 0.14) * ui);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.bezierCurveTo(sx + side * base * 0.08, sy + reach * 0.35, sx + side * base * 0.11 + sway * 0.6, sy + reach * 0.7, ex, ey);
    ctx.stroke();
    // hairpin hook tip
    const tipAng = Math.atan2(ey - (sy + reach * 0.7), ex - (sx + side * base * 0.11 + sway * 0.6));
    const hookDir = side > 0 ? 1 : -1;
    const hx = ex + Math.cos(tipAng + hookDir * 1.2) * base * 0.045;
    const hy = ey + Math.sin(tipAng + hookDir * 1.2) * base * 0.045;
    ctx.strokeStyle = palette.accent;
    ctx.lineWidth = Math.max(0.8, (1.1 - idx * 0.1) * ui);
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.quadraticCurveTo(ex + Math.cos(tipAng + hookDir * 0.6) * base * 0.04, ey + Math.sin(tipAng + hookDir * 0.6) * base * 0.04, hx, hy);
    ctx.stroke();
    // glowing tip
    ctx.save();
    ctx.shadowBlur = 8 * ui;
    ctx.shadowColor = palette.accent;
    ctx.fillStyle = palette.accent;
    ctx.globalAlpha = alpha + 0.1;
    ctx.beginPath();
    ctx.arc(ex, ey, Math.max(1.0, 1.9 * ui - idx * 0.15), 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
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

  // memory/knowledge presence: faint orbiting fragments/constellations
  const k = state.knowledge || { memories: 0, skills: 0, uploads: 0 };
  const kCount = Math.min(24, Math.max(0, (k.skills || 0) + (k.memories || 0) + (k.uploads || 0)));
  if (kCount > 0) {
    ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < kCount; i++) {
      const kind = i < (k.skills || 0) ? "skill" : (i < (k.skills || 0) + (k.memories || 0) ? "memory" : "upload");
      const band = kind === "skill" ? 2.02 : (kind === "memory" ? 2.28 : 2.52);
      const a = (i * 2.399963) + t * (0.03 + (i % 5) * 0.004) * (i % 2 ? 1 : -1);
      const wob = Math.sin(t * 0.7 + i * 1.7) * base * 0.03;
      const rx = base * band + wob;
      const ry = base * (band * 0.74) + wob * 0.5;
      const x = Math.cos(a) * rx;
      const y = Math.sin(a) * ry;
      const tw = 0.55 + 0.45 * Math.sin(t * 1.2 + i * 0.9);
      ctx.globalAlpha = (0.05 + tw * 0.08) * (0.7 + energy * 0.4);
      ctx.fillStyle = kind === "upload" ? palette.accent : (kind === "skill" ? palette.core : "rgba(210,240,255,0.9)");
      const sz = kind === "upload" ? 1.8 : 1.4;
      ctx.beginPath();
      ctx.arc(x, y, sz * ui * (0.8 + tw * 0.4), 0, Math.PI * 2);
      ctx.fill();
      if (i % 3 === 0) {
        const j = (i + 2) % kCount;
        const a2 = (j * 2.399963) + t * (0.03 + (j % 5) * 0.004) * (j % 2 ? 1 : -1);
        const band2 = j < (k.skills || 0) ? 2.02 : (j < (k.skills || 0) + (k.memories || 0) ? 2.28 : 2.52);
        const x2 = Math.cos(a2) * base * band2;
        const y2 = Math.sin(a2) * base * band2 * 0.74;
        const d = Math.hypot(x2 - x, y2 - y);
        if (d < base * 0.9) {
          ctx.strokeStyle = palette.ring;
          ctx.globalAlpha = 0.03 + tw * 0.03;
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x2, y2); ctx.stroke();
        }
      }
    }
    ctx.globalCompositeOperation = "source-over";
  }
  const tickR = base * 1.48;
  const tickRot = t * 0.12;
  ctx.strokeStyle = palette.accent;
  ctx.lineWidth = 1;
  for (let i = 0; i < 48; i++) {
    const a = tickRot + (i / 48) * Math.PI * 2;
    const major = i % 6 === 0;
    const len = (major ? base * 0.06 : base * 0.03) * (1 + 0.15 * Math.sin(t * 0.8 + i));
    ctx.globalAlpha = (major ? 0.05 : 0.025) + energy * 0.05;
    ctx.beginPath();
    ctx.moveTo(Math.cos(a) * tickR, Math.sin(a) * tickR * 0.74);
    ctx.lineTo(Math.cos(a) * (tickR + len), Math.sin(a) * (tickR + len) * 0.74);
    ctx.stroke();
  }

  // organic Vessel/memory linework
  function sketchArc(radiusX, radiusY, start, end, wobble, steps = 48, alpha = 0.08, lw = 1, color = palette.ring) {
    ctx.strokeStyle = color;
    ctx.lineWidth = lw;
    ctx.globalAlpha = alpha;
    ctx.beginPath();
    for (let i = 0; i <= steps; i++) {
      const p = i / steps;
      const a = start + (end - start) * p;
      const j = (Math.sin(a * 7 + t * 0.7 + wobble) * 0.5 + Math.sin(a * 13 - t * 0.4 + wobble * 1.7) * 0.5) * wobble;
      const rx = radiusX + j;
      const ry = radiusY + j * 0.55;
      const x = Math.cos(a) * rx;
      const y = Math.sin(a) * ry * 0.74;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  const memRot = t * 0.045;
  sketchArc(base * 1.95, base * 1.38, memRot + 0.2, memRot + 1.9, base * 0.012, 56, 0.07 + energy * 0.04, 1, palette.ring);
  sketchArc(base * 2.08, base * 1.48, -memRot + 2.4, -memRot + 4.1, base * 0.01, 56, 0.05 + energy * 0.03, 0.9, palette.accent);
  sketchArc(base * 1.62, base * 1.18, memRot * 1.2 + 4.0, memRot * 1.2 + 5.4, base * 0.008, 40, 0.045 + energy * 0.03, 0.9, palette.core);
  for (let i = 0; i < 10; i++) {
    const a = memRot * (i % 2 ? -1 : 1) + (i / 10) * Math.PI * 2;
    const rr = base * (1.58 + (i % 3) * 0.22);
    const x = Math.cos(a) * rr;
    const y = Math.sin(a) * rr * 0.74;
    const len = base * (0.03 + (i % 4) * 0.012);
    const ta = a + Math.PI / 2 + Math.sin(t * 0.6 + i) * 0.12;
    ctx.globalAlpha = 0.05 + energy * 0.05;
    ctx.strokeStyle = i % 2 ? palette.accent : palette.ring;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x - Math.cos(ta) * len, y - Math.sin(ta) * len * 0.74);
    ctx.lineTo(x + Math.cos(ta) * len, y + Math.sin(ta) * len * 0.74);
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
  ctx.fillStyle = "#d8fff0";
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

  // expressive inner voice waveform/aura
  if (speakingBoost || audio > 0.03) {
    ctx.globalCompositeOperation = "lighter";
    const va = 0.10 + audio * 0.22;
    for (let wv = 0; wv < 2; wv++) {
      const yOff = (wv - 0.5) * radius * 0.18;
      ctx.globalAlpha = va * (1 - wv * 0.25);
      ctx.strokeStyle = wv === 0 ? "rgba(255,245,255,0.85)" : palette.accent;
      ctx.lineWidth = Math.max(1, (1.4 - wv * 0.3) * ui);
      ctx.beginPath();
      const segs = 42;
      const span = radius * 0.62;
      for (let i = 0; i <= segs; i++) {
        const px = (i / segs) * 2 - 1;
        const x = cx + px * span;
        const env = Math.cos(px * Math.PI * 0.5);
        const wave = Math.sin(px * 10 + t * (7 + wv * 2)) * 0.55 + Math.sin(px * 18 - t * 5.5) * 0.45;
        const y = cy + yOff + wave * env * radius * (0.08 + audio * 0.18);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 0.05 + audio * 0.12;
    const ia = ctx.createRadialGradient(cx, cy, radius * 0.05, cx, cy, radius * 0.9);
    ia.addColorStop(0, "rgba(255,255,255,0.35)");
    ia.addColorStop(0.5, palette.accent);
    ia.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = ia;
    ctx.beginPath();
    ctx.ellipse(cx, cy, radius * (0.55 + audio * 0.15), radius * (0.38 + audio * 0.12), 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalCompositeOperation = "source-over";
  }

  ctx.restore();

  // feedback micro-transition ripples/pulses
  if (state.ripples.length) {
    const nowMs = performance.now();
    ctx.save();
    ctx.translate(cx, cy);
    state.ripples = state.ripples.filter(r => (nowMs - r.t) < r.dur);
    for (const r of state.ripples) {
      const p = (nowMs - r.t) / r.dur;
      if (p < 0 || p > 1) continue;
      const ease = 1 - Math.pow(1 - p, 2);
      const fade = (1 - p);
      const baseR = r.kind === "memory" || r.kind === "learn" ? 1.05 : 1.15;
      const rr = base * (baseR + ease * (r.kind === "hear" ? 0.85 : 1.05)) * r.strength;
      ctx.globalAlpha = fade * (r.kind === "learn" ? 0.22 : 0.16) * r.strength;
      ctx.strokeStyle = r.kind === "memory" || r.kind === "learn" ? palette.accent : palette.core;
      ctx.lineWidth = Math.max(1, (1.6 - p * 0.8) * ui);
      ctx.beginPath();
      ctx.ellipse(0, 0, rr, rr * 0.78, 0, 0, Math.PI * 2);
      ctx.stroke();
      if (r.kind === "memory" || r.kind === "learn") {
        ctx.globalAlpha = fade * 0.08;
        ctx.beginPath();
        ctx.ellipse(0, 0, rr * 0.88, rr * 0.88 * 0.78, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

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

  // voice waveform ring + expressive aura when speaking
  if (speakingBoost || audio > 0.02) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.globalCompositeOperation = "lighter";
    const aBase = 0.10 + audio * 0.28 + speakingBoost * 0.08;
    for (let layer = 0; layer < 3; layer++) {
      const rBase = base * (1.48 + layer * 0.07);
      const bars = 72;
      ctx.globalAlpha = (aBase - layer * 0.03) * (1 - layer * 0.18);
      ctx.strokeStyle = layer === 1 ? palette.core : palette.accent;
      ctx.lineWidth = Math.max(1, (1.2 - layer * 0.2) * ui);
      ctx.beginPath();
      for (let i = 0; i <= bars; i++) {
        const a = (i / bars) * Math.PI * 2;
        const wave = Math.sin(a * (7 + layer * 2) - t * (5.5 + layer)) * Math.sin(a * 3 + t * (2.2 - layer * 0.3));
        const wave2 = Math.sin(a * 11 + t * 3.5 + layer) * 0.35;
        const amp = (0.05 + audio * 0.22 + speakingBoost * 0.05) * (1 - layer * 0.18);
        const r = rBase + (wave * 0.7 + wave2 * 0.3 + 0.5) * base * amp;
        const x = Math.cos(a) * r;
        const y = Math.sin(a) * r * 0.74;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.stroke();
    }
    // inner voice aura
    ctx.globalAlpha = 0.06 + audio * 0.18;
    const aura = ctx.createRadialGradient(0, 0, base * 0.2, 0, 0, base * 1.25);
    aura.addColorStop(0, palette.accent);
    aura.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = aura;
    ctx.beginPath();
    ctx.ellipse(0, 0, base * (1.05 + audio * 0.12), base * (0.82 + audio * 0.1), 0, 0, Math.PI * 2);
    ctx.fill();
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
  source.onopen = () => { resetView(); setLink(true); loadUploads(); loadKnowledge(); };
  source.onmessage = (msg) => {
    try { handleEvent(JSON.parse(msg.data)); } catch (_) { }
  };
  source.onerror = () => setLink(false);
}

async function loadKnowledge() {
  try {
    const res = await fetch("/api/knowledge", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    state.knowledge.memories = Number(data.memories || 0);
    state.knowledge.skills = Number(data.skills || 0);
    state.knowledge.uploads = Number(data.uploads || 0);
  } catch (_) { }
}

async function loadUploads() {
  if (!els.uploadList) return;
  try {
    const res = await fetch("/api/uploads", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const items = Array.isArray(data.uploads) ? data.uploads : [];
    state.knowledge.uploads = items.length;
    if (!items.length) {
      els.uploadList.innerHTML = '<div class="upload-item"><div>No uploads yet</div><div class="meta">Upload documents for Ada to read and learn from.</div></div>';
      return;
    }
    els.uploadList.innerHTML = items.map((it) => {
      const name = String(it.name || "");
      const size = Number(it.size || 0);
      const kb = size >= 1024 ? (size / 1024).toFixed(1) + " KB" : size + " B";
      const ext = it.extracted ? "text extracted" : "saved";
      return `<div class="upload-item"><div>${name.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}</div><div class="meta">${kb} • ${ext}</div></div>`;
    }).join("");
  } catch (_) {
    if (els.uploadStatus) els.uploadStatus.textContent = "Could not load uploads.";
  }
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

async function uploadSelectedFiles() {
  if (!els.uploadFile || !els.uploadFile.files || !els.uploadFile.files.length) {
    if (els.uploadStatus) els.uploadStatus.textContent = "Choose one or more files first.";
    return;
  }
  const files = Array.from(els.uploadFile.files);
  if (els.uploadBtn) els.uploadBtn.disabled = true;
  let ok = 0, fail = 0;
  for (const file of files) {
    try {
      if (els.uploadStatus) els.uploadStatus.textContent = `Uploading ${file.name}…`;
      const data = await readFileAsBase64(file);
      const res = await fetch("/api/upload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: file.name, data })
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok || !out.ok) throw new Error(out.error || ("HTTP " + res.status));
      ok++;
    } catch (e) {
      fail++;
      console.error("upload failed", e);
    }
  }
  if (els.uploadBtn) els.uploadBtn.disabled = false;
  if (els.uploadFile) els.uploadFile.value = "";
  if (els.uploadStatus) {
    els.uploadStatus.textContent = fail
      ? `Uploaded ${ok} file(s), ${fail} failed.`
      : `Uploaded ${ok} file(s). Ada is reading and learning from them in the background.`;
  }
  loadUploads();
}

function setupUploads() {
  if (els.uploadToggle && els.uploadPanel) {
    els.uploadToggle.addEventListener("click", () => {
      els.uploadPanel.classList.toggle("collapsed");
    });
  }
  if (els.uploadBtn) {
    els.uploadBtn.addEventListener("click", uploadSelectedFiles);
  }
}

if (window.ResizeObserver && els.canvas) new ResizeObserver(resizeCanvas).observe(els.canvas);
window.addEventListener("resize", resizeCanvas);
function applyDisplayMode() {
  const params = new URLSearchParams(window.location.search);
  const bg = (params.get("bg") || "").toLowerCase();
  const transparent = params.get("transparent");
  const isTransparent = bg === "transparent" || transparent === "1" || transparent === "true";
  if (isTransparent) document.body.style.background = "transparent";
  const chrome = (params.get("chrome") || params.get("hud") || "").toLowerCase();
  if (chrome === "0" || chrome === "false" || chrome === "none") {
    document.body.classList.add("no-chrome");
  }
}
applyDisplayMode();
resizeCanvas();
resetView();
setupUploads();
loadUploads();
loadKnowledge();
requestAnimationFrame(draw);
connect();
