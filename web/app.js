"use strict";

const els = {
  canvas: document.getElementById("orb"),
  stateLabel: document.getElementById("state-label"),
  stateDetail: document.getElementById("state-detail"),
  routeText: document.getElementById("route-text"),
  modelText: document.getElementById("model-text"),
  linkText: document.getElementById("link-text"),
  messages: document.getElementById("messages"),
};

const ctx = els.canvas.getContext("2d");
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
  assistantBody: null,
  currentAssistant: "",
};

const particles = Array.from({ length: 48 }, () => ({
  angle: Math.random() * Math.PI * 2,
  radius: 1.35 + Math.random() * 1.0,
  speed: (Math.random() * 0.28 + 0.08) * (Math.random() < 0.5 ? -1 : 1),
  size: Math.random() * 1.1 + 0.3,
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

function setLink(online) {
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
  return false;
}

function setState(name, detail) {
  const next = name || "idle";
  state.current = next;
  state.detail = detail || (next === "idle" ? "awaiting input" : "");
  document.body.dataset.state = next;
  els.stateLabel.textContent = STATE_LABELS[next] || next.toUpperCase();
  els.stateDetail.textContent = state.detail;
  if (next === "idle") clearStages();
}

function setRoute(label, model, tools) {
  state.route = label ? `${label}${tools === false ? " · no tools" : tools ? " · tools" : ""}` : "—";
  if (model) state.model = model;
  els.routeText.textContent = `route ${state.route}`;
  els.modelText.textContent = state.model;
  if (label) activateStage("route", 2500);
}

function scrollMessages() {
  if (els.messages) els.messages.scrollTop = els.messages.scrollHeight;
}

function addMessage(role, text) {
  if (!els.messages) return null;
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const label = document.createElement("div");
  label.className = "msg-role";
  label.textContent = role === "user" ? "You" : "Ada";
  const body = document.createElement("div");
  body.className = "msg-body";
  body.textContent = text || "";
  wrap.append(label, body);
  els.messages.append(wrap);
  while (els.messages.children.length > 80) els.messages.firstElementChild.remove();
  scrollMessages();
  return body;
}

function appendToken(text) {
  if (!text) return;
  if (!state.assistantBody) {
    state.assistantBody = addMessage("ada", "");
    if (state.assistantBody && state.assistantBody.parentElement) state.assistantBody.parentElement.classList.add("streaming");
    state.currentAssistant = "";
  }
  state.currentAssistant += text;
  if (state.assistantBody) state.assistantBody.textContent = state.currentAssistant;
  scrollMessages();
}

function finishAssistant(text) {
  if (!state.assistantBody) state.assistantBody = addMessage("ada", "");
  if (text) state.currentAssistant = text;
  if (state.assistantBody) {
    state.assistantBody.textContent = state.currentAssistant;
    if (state.assistantBody.parentElement) state.assistantBody.parentElement.classList.remove("streaming");
  }
  scrollMessages();
}

function resetView() {
  clearStages();
  setState("idle", "awaiting input");
  setRoute("—", "—");
  state.lastTokenAt = 0;
  state.voiceLevel = 0;
  state.voiceLevelTarget = 0;
  state.assistantBody = null;
  state.currentAssistant = "";
  if (els.messages) els.messages.innerHTML = "";
}

function handleEvent(event) {
  const data = event.data || {};
  switch (event.type) {
    case "session":
      setRoute("—", `${data.quick} / ${data.deep}`);
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
    case "notification":
    case "action":
      // observability events (shown via console/stages as applicable)
      if (event.type === "action") activateStage("tools", 2500);
      break;
    case "user":
      addMessage("user", data.text || "");
      state.assistantBody = null;
      state.currentAssistant = "";
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
      appendToken(data.text || "");
      break;
    case "tool":
      if (data.status === "start") {
        activateStage("tools");
        if (data.name === "read_skill" || data.name === "save_skill") {
          activateStage("skill");
          if (data.args && data.args.name) {
            state.activeSkill = String(data.args.name);
            if (!state.knownSkills.includes(state.activeSkill)) state.knownSkills.unshift(state.activeSkill);
            state.knownSkills = state.knownSkills.slice(0, 6);
          }
        }
      } else if (data.status === "done") {
        activateStage("tools", 2500);
        if (data.name === "read_skill" || data.name === "save_skill") {
          activateStage("skill", 4500);
          if (data.args && data.args.name) {
            state.activeSkill = String(data.args.name);
            if (!state.knownSkills.includes(state.activeSkill)) state.knownSkills.unshift(state.activeSkill);
            state.knownSkills = state.knownSkills.slice(0, 6);
          }
        }
      } else {
        activateStage("tools", 2500);
        if (data.name === "read_skill" || data.name === "save_skill") {
          activateStage("skill", 4500);
          if (data.args && data.args.name) {
            state.activeSkill = String(data.args.name);
            if (!state.knownSkills.includes(state.activeSkill)) state.knownSkills.unshift(state.activeSkill);
            state.knownSkills = state.knownSkills.slice(0, 6);
          }
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
      finishAssistant(data.text || "");
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
  const rect = els.canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  els.canvas.width = Math.max(1, Math.round(rect.width * dpr));
  els.canvas.height = Math.max(1, Math.round(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function draw(now) {
  const w = els.canvas.clientWidth;
  const h = els.canvas.clientHeight;
  if (!w || !h) { requestAnimationFrame(draw); return; }

  const t = reduceMotion ? 0 : now / 1000;
  const cx = w / 2;
  const cy = h * 0.43;
  const minDim = Math.min(w, h);
  const base = Math.max(60, minDim * (minDim < 520 ? 0.16 : 0.185));
  const ui = Math.max(0.9, Math.min(1.35, minDim / 520));
  const palette = PALETTES[state.current] || PALETTES.idle;
  const tokenHeat = Math.max(0, 1 - (now - state.lastTokenAt) / 700);
  const flicker = reduceMotion ? 1 : 0.94 + 0.06 * Math.sin(t * 18) * Math.sin(t * 5.7 + 1.3);
  const energy =
    (state.current === "thinking" || state.current === "warming" ? 0.7 :
      state.current === "speaking" ? 0.95 :
        state.current === "listening" || state.current === "transcribing" ? 0.55 :
          state.current === "error" ? 0.35 : 0.18) + tokenHeat * 0.2;

  ctx.clearRect(0, 0, w, h);

  // ambient field
  ctx.save();
  for (const a of ambient) {
    const ax = ((a.x + Math.sin(t * a.v + a.p) * 0.03) % 1) * w;
    const ay = ((a.y + (t * a.v * 0.15) % 1)) * h;
    const tw = 0.5 + 0.5 * Math.sin(t * 1.2 + a.p);
    ctx.globalAlpha = 0.03 + tw * 0.05 * (0.6 + energy * 0.4);
    ctx.fillStyle = palette.accent;
    ctx.beginPath();
    ctx.arc(ax, ay, a.s, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  const glow = ctx.createRadialGradient(cx, cy, base * 0.2, cx, cy, base * 3.8);
  glow.addColorStop(0, palette.glow);
  glow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = 0.95 * flicker;
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);
  ctx.globalAlpha = 1;

  // hologram base/projection + reflection
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
  // subtle reflection pool
  const pool = ctx.createRadialGradient(0, 0, base * 0.1, 0, 0, base * 1.6);
  pool.addColorStop(0, palette.glow);
  pool.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = 0.18 + energy * 0.1;
  ctx.fillStyle = pool;
  ctx.beginPath();
  ctx.ellipse(0, base * 0.06, base * 1.5, base * 0.28, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // scan beam removed for transparent displays

  // orbit rings + hologram ticks (softer)
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
  // subtle organic ticks
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

  // liquid/audio state
  state.voiceLevel += (state.voiceLevelTarget - state.voiceLevel) * 0.32;
  state.voiceLevelTarget *= 0.88;
  const audio = state.voiceLevel;
  const speakingBoost = (state.current === "speaking" || state.voiceActive > 0) ? 1 : 0;

  // particles (float around liquid)
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (const p of particles) {
    const speed = p.speed * (1 + audio * 1.2 + speakingBoost * 0.25);
    const a = p.angle + t * speed;
    const r = base * p.radius + Math.sin(t * (1.2 + audio) + p.phase) * base * (0.04 + audio * 0.1 + speakingBoost * 0.03);
    const x = cx + Math.cos(a) * r;
    const y = cy + Math.sin(a) * r * 0.74;
    ctx.globalAlpha = 0.08 + p.depth * 0.22 * (0.6 + energy * 0.4 + audio * 0.5);
    ctx.fillStyle = palette.accent;
    ctx.beginPath();
    ctx.arc(x, y, p.size * (1 + audio * 0.7 + speakingBoost * 0.15), 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  // liquid core (audio-reactive, organic)
  const idleBreath = state.current === "idle" ? (Math.sin(t * 0.8) * 0.025 + 0.025) : 0;
  const liquidAmp = (0.08 + energy * 0.05 + audio * 0.30 + speakingBoost * 0.07 + idleBreath) * base;
  const radius = base * (1 + Math.sin(t * 1.3) * 0.025 + Math.sin(t * 0.7 + 1.2) * 0.012 + energy * 0.03 + audio * 0.11 + idleBreath * 0.6);

  function blobPath(rBase, phase, ampScale = 1) {
    const points = 96;
    ctx.beginPath();
    for (let i = 0; i <= points; i++) {
      const a = (i / points) * Math.PI * 2;
      const n =
        Math.sin(a * 2 + t * 0.9 + phase) * 0.35 +
        Math.sin(a * 3 - t * 1.1 + phase * 1.3) * 0.30 +
        Math.sin(a * 5 + t * 0.7 + phase * 0.7) * 0.20 +
        Math.sin(a * 8 - t * 0.5) * 0.10 +
        Math.sin(t * 0.35 + phase) * 0.05;
      const wobble = 1 + (n * liquidAmp * ampScale) / Math.max(20, rBase);
      const rr = rBase * wobble;
      const x = cx + Math.cos(a) * rr;
      const y = cy + Math.sin(a) * rr * 0.985;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
  }

  ctx.save();
  ctx.globalCompositeOperation = "lighter";

  // translucent outer shells
  const shells = [
    { r: 1.34, phase: 1.4, a: 0.06, amp: 1.25, color: palette.glow },
    { r: 1.22, phase: 0.8, a: 0.10, amp: 1.18, color: palette.glow },
    { r: 1.12, phase: 2.1, a: 0.08, amp: 1.10, color: palette.core },
  ];
  for (const s of shells) {
    ctx.globalAlpha = (s.a + audio * 0.05) * flicker;
    ctx.fillStyle = s.color;
    blobPath(radius * (s.r + audio * 0.04), s.phase + t * 0.15, s.amp + audio * 0.25);
    ctx.fill();
  }

  // color split liquid layers
  ctx.globalAlpha = (0.13 + audio * 0.07) * flicker;
  ctx.fillStyle = palette.core;
  blobPath(radius * (1.04 + audio * 0.03), 0.0, 1.05 + audio * 0.25);
  ctx.fill();
  ctx.globalAlpha = (0.10 + audio * 0.06) * flicker;
  ctx.fillStyle = "#9ffcff";
  blobPath(radius * (1.00 + audio * 0.02), 1.7, 0.95 + audio * 0.22);
  ctx.fill();
  ctx.globalAlpha = (0.07 + audio * 0.04) * flicker;
  ctx.fillStyle = palette.accent;
  blobPath(radius * 0.96, 3.1, 0.9 + audio * 0.2);
  ctx.fill();

  // main liquid body (semi-transparent gradient)
  const core = ctx.createRadialGradient(cx - radius * 0.28, cy - radius * 0.35, radius * 0.05, cx, cy, radius * 1.18);
  core.addColorStop(0, "rgba(245,255,255,0.90)");
  core.addColorStop(0.18, palette.core);
  core.addColorStop(0.55, palette.core);
  core.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = (0.72 + audio * 0.08) * flicker;
  ctx.fillStyle = core;
  blobPath(radius, 0.4, 1.0 + audio * 0.35);
  ctx.fill();

  // inner translucent layers
  ctx.globalCompositeOperation = "screen";
  const inner = ctx.createRadialGradient(cx - radius * 0.15, cy - radius * 0.1, radius * 0.02, cx, cy, radius * 0.95);
  inner.addColorStop(0, "rgba(255,255,255,0.35)");
  inner.addColorStop(0.45, "rgba(180,245,255,0.10)");
  inner.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = (0.28 + audio * 0.12) * flicker;
  ctx.fillStyle = inner;
  blobPath(radius * 0.86, 2.4, 0.85 + audio * 0.2);
  ctx.fill();

  ctx.globalAlpha = (0.14 + audio * 0.08) * flicker;
  ctx.strokeStyle = "rgba(220,255,255,0.55)";
  ctx.lineWidth = Math.max(1, ui * 0.9);
  blobPath(radius * 0.72, 5.0, 0.75 + audio * 0.18);
  ctx.stroke();
  blobPath(radius * 0.56, 4.1, 0.7 + audio * 0.15);
  ctx.stroke();

  // internal fluid highlights
  ctx.globalAlpha = 0.18 + energy * 0.12 + audio * 0.18;
  ctx.strokeStyle = "rgba(235,255,255,0.75)";
  ctx.lineWidth = Math.max(1, ui);
  const ripples = 4 + (speakingBoost ? 2 : 0);
  for (let k = 0; k < ripples; k++) {
    const yy = cy - radius * 0.5 + k * radius * (0.95 / ripples) + Math.sin(t * 2.2 + k) * (3 + audio * 14 + speakingBoost * 4);
    const half = Math.max(6, radius * (0.82 - Math.abs(k - (ripples - 1) / 2) * 0.1));
    ctx.beginPath();
    ctx.moveTo(cx - half, yy);
    ctx.quadraticCurveTo(cx + Math.sin(t * 3.2 + k) * radius * (0.22 + audio * 0.12), yy - (8 + audio * 22 + speakingBoost * 6), cx + half, yy);
    ctx.stroke();
  }

  // specular highlights
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

  // subtle mark
  ctx.save();
  ctx.globalAlpha = 0.07 + energy * 0.05;
  ctx.fillStyle = palette.accent;
  ctx.font = `${500} ${Math.round(10 * ui)}px Inter, "Segoe UI", system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("HOPE · ADA", cx, cy + base * 1.94);
  ctx.restore();

  // listening ripples
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

  // voice waveform ring when speaking
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

  // stage ring
  const stages = [
    { key: "input", label: "Input" },
    { key: "route", label: "Route" },
    { key: "tools", label: "Tools" },
    { key: "skill", label: "Skill" },
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
      // data pulse flowing along connector
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

if (window.ResizeObserver) new ResizeObserver(resizeCanvas).observe(els.canvas);
window.addEventListener("resize", resizeCanvas);
function applyDisplayMode() {
  const params = new URLSearchParams(window.location.search);
  const bg = (params.get("bg") || "").toLowerCase();
  const transparent = params.get("transparent");
  const isTransparent = bg === "transparent" || transparent === "1" || transparent === "true" || (params.has("transparent") && transparent !== "0" && transparent !== "false");
  const isDark = bg === "dark" || transparent === "0" || transparent === "false";
  document.body.classList.toggle("transparent-bg", isTransparent && !isDark);
  document.body.classList.toggle("dark-bg", !isTransparent || isDark);

  const chat = (params.get("chat") || "").toLowerCase();
  const showChat = !(chat === "0" || chat === "false" || chat === "off" || chat === "hide");
  document.body.classList.toggle("no-chat", !showChat);
}

applyDisplayMode();
resizeCanvas();
resetView();
requestAnimationFrame(draw);
connect();
