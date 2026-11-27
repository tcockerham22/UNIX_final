"use strict";

const cloudOrbOnly = document.body.dataset.cloudOrbOnly === "true";
const ADA_SERVICE_ORIGIN = location.port === "8765"
  ? ""
  : location.protocol === "file:"
    ? "http://127.0.0.1:8765"
    : `${location.protocol}//${location.hostname || "127.0.0.1"}:8765`;
const adaServiceUrl = (path) => `${ADA_SERVICE_ORIGIN}${path}`;

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

// SIMPLIFY toggles: set any value to false to bring that decorative layer back.
const SIMPLIFY = {
  compactStatus: true,       // #1 two HUD lines; tiers row hidden until hover
  activeNodeLabelOnly: true, // #2 inactive module labels fade out; hover/dbl-click reveals all
  hideGridAndBrackets: false, // #3 grid + corner brackets restored, but softened by FLAIR
  singleOrbitRing: false,     // #4 original ring layer restored, but softened by FLAIR
  minimalParticles: false,    // #5 full particle field restored, but slowed/dimmed by FLAIR
};
// FLAIR: 0 = plain simplified view, 1 = original decoration intensity.
const FLAIR = 0.55;
document.body.dataset.compactStatus = SIMPLIFY.compactStatus ? "1" : "0";

const STATE_LABELS = {
  idle: "IDLE",
  listening: "LISTENING",
  transcribing: "TRANSCRIBING",
  thinking: "THINKING",
  learning: "LEARNING",
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
  learning: { core: "#7ff5d8", glow: "rgba(110,235,200,0.12)", ring: "rgba(127,245,216,0.48)", accent: "#f2fff9" },
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
  activeAgents: 0,
  agentRuns: 0,
  toolCalls: 0,
  inputMode: "text",
  voiceName: "",
  tiers: { light: "—", moderate: "—", deep: "—" },
  knowledge: { memories: 0, skills: 0, uploads: 0, sources: 0, connections: 0 },
  ripples: [],
  lastRippleAt: 0,
  lastEventId: 0,   // ignore replayed events after an SSE reconnect
  // SIMPLIFY #2: per-node label fade state and reveal controls
  lastActiveStage: null,
  labelAlpha: {},
  revealAllLabels: false,
  pointer: { x: -1, y: -1, inside: false },
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

// SIMPLIFY #5: work from small, slow subsets without touching the source arrays.
const particleDots = SIMPLIFY.minimalParticles ? particles.slice(0, 6) : particles;
const fireflyDots = SIMPLIFY.minimalParticles ? fireflies.slice(0, 4) : fireflies;

function setLink(online) {
  if (!els.linkText) return;
  els.linkText.textContent = online ? "live" : "offline";
  els.linkText.classList.toggle("online", online);
  els.linkText.classList.toggle("offline", !online);
}

function activateStage(stage, ttl = 0) {
  state.activeStages.add(stage);
  state.lastActiveStage = { key: stage, at: Date.now() };
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
  if (stage === "memory") return state.activeStages.has("memory") || state.current === "learning";
  if (stage === "agents") return state.activeStages.has("agents");
  return false;
}

function roundedRect(x, y, w, h, r) {
  const rr = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

function stageValue(key) {
  switch (key) {
    case "input": return state.inputMode || "text";
    case "route": return (state.route || "—").split(" · ")[0];
    case "tools": return state.toolCalls
      ? `${state.toolCalls} call${state.toolCalls === 1 ? "" : "s"}` : "ready";
    case "skill": return state.knownSkills.length
      ? `${state.knowledge.skills || state.knownSkills.length} saved` : "none";
    case "memory": {
      const count = state.knowledge.memories || 0;
      return `${count} fact${count === 1 ? "" : "s"}`;
    }
    case "agents": return state.activeAgents
      ? `${state.activeAgents} active`
      : state.agentRuns ? `${state.agentRuns} run${state.agentRuns === 1 ? "" : "s"}` : "idle";
    case "model": return `${tierLabel(state.model) || "model"} · ${shortModel(state.model)}`;
    case "voice": return state.voiceActive ? "speaking"
      : state.voiceName ? shortModel(state.voiceName) : "—";
    default: return "";
  }
}

function knowledgeKind(index, k) {
  const skills = Number(k.skills || 0);
  const memories = Number(k.memories || 0);
  const uploads = Number(k.uploads || 0);
  if (index < skills) return "skill";
  if (index < skills + memories) return "memory";
  if (index < skills + memories + uploads) return "upload";
  return "source";
}

function knowledgeBand(kind) {
  if (kind === "skill") return 2.02;
  if (kind === "memory") return 2.28;
  if (kind === "upload") return 2.52;
  return 2.72;
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
    else if (next === "learning") spawnRipple("learn", 1.2);
    else if (next === "speaking") spawnRipple("voice", 1.05);
    else if (next === "error") spawnRipple("error", 0.8);
  }
}

// The cloud chat page controls this same renderer across its iframe boundary.
window.addEventListener("message", (event) => {
  if (!cloudOrbOnly || event.origin !== location.origin || event.source !== window.parent) return;
  const message = event.data;
  if (!message || message.type !== "ada-cloud-orb-state") return;
  if (message.knowledge) {
    state.knowledge = { ...state.knowledge, ...message.knowledge };
    const learned = Number(message.learning?.new_connections || 0);
    if (learned > 0) {
      activateStage("memory", 3500);
      spawnRipple("learn", Math.min(1.4, 0.85 + learned * 0.15));
    }
  }
  setState(message.state, message.detail);
});

function setRoute(label, model, tools) {
  state.route = label ? `${label}${tools === false ? " · no tools" : tools ? " · tools" : ""}` : "—";
  if (model) state.model = model;
  // SIMPLIFY #1: compact line reads "<tier> · <model> · live"; state.route is untouched.
  if (els.routeText) {
    els.routeText.textContent = SIMPLIFY.compactStatus
      ? (tierLabel(model) || label || "—")
      : `route ${state.route}`;
  }
  if (els.modelText) {
    const t = tierLabel(state.model);
    // SIMPLIFY #1: tier already sits in the first slot, so avoid repeating it here.
    els.modelText.textContent = SIMPLIFY.compactStatus
      ? shortModel(state.model)
      : (t ? `${t} · ${shortModel(state.model)}` : shortModel(state.model));
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
  // SSE replays history after a reconnect. Never let an older event overwrite
  // a newer live state (e.g. an old IDLE event arriving during a long THINK).
  if (event.id && event.id <= state.lastEventId) return;
  if (event.id) state.lastEventId = event.id;
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
      if (data.input) state.inputMode = String(data.input);
      if (data.voice) state.voiceName = String(data.voice);
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
    case "image":
      activateStage("tools", 2500);
      spawnRipple("learn", 0.9);
      break;
    case "agent":
      if (data.status === "start") {
        state.activeAgents += 1;
        state.agentRuns += 1;
        activateStage("agents");
        spawnRipple("learn", 0.85);
      } else {
        state.activeAgents = Math.max(0, state.activeAgents - 1);
        activateStage("agents", 2500);
      }
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
        state.toolCalls += 1;
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
      // Only the final reply for this turn may leave THINKING. Progress notes,
      // reminders and other untagged assistant events must not do it.
      if (state.current === "thinking" && data.final && !data.source) setState("idle", "awaiting input");
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

  // SIMPLIFY #3: background grid (and corner brackets below) are off by default.
  if (!SIMPLIFY.hideGridAndBrackets) {
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
  gridPass(fineX, fineY, 0.045 * FLAIR, fineSlant, 1);
  gridPass(fineX * 3, fineY * 3, 0.06 * FLAIR, fineSlant * 3, 1);
  ctx.restore();
  }

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

  // SIMPLIFY #3: corner brackets / reticle marks (part of the framing layer)
  if (!SIMPLIFY.hideGridAndBrackets) {
  // subtle minimal framing / anchor
  ctx.save();
  const frameR = Math.min(w, h) * 0.46;
  const frameA = (0.06 + energy * 0.04) * FLAIR;
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
  }

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

  // SIMPLIFY #4: one faint ring (mostly while thinking) outside the orb's bright core.
  ctx.save();
  ctx.translate(cx, cy);
  if (!SIMPLIFY.singleOrbitRing) {
    for (let i = 0; i < 2; i++) {
      const rot = t * (0.06 + i * 0.03) * (i % 2 ? 1 : -1);
      const rx = base * (1.72 + i * 0.3);
      const ry = base * (1.22 + i * 0.12);
      ctx.globalAlpha = (0.08 + energy * 0.12) * FLAIR;
      ctx.strokeStyle = palette.ring;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.ellipse(0, 0, rx, ry, rot, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = (0.12 + energy * 0.16) * FLAIR;
      ctx.strokeStyle = palette.core;
      ctx.beginPath();
      ctx.ellipse(0, 0, rx, ry, rot, t * 0.5 + i, t * 0.5 + i + 0.8);
      ctx.stroke();
    }
  } else {
    const thinking = state.current === "thinking" || state.current === "warming";
    ctx.globalAlpha = thinking ? 0.10 + energy * 0.04 : 0.02;
    ctx.strokeStyle = palette.ring;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.ellipse(0, 0, base * 1.78, base * 1.32, 0, 0, Math.PI * 2);
    ctx.stroke();
  }

  // memory/knowledge presence: faint orbiting fragments/constellations
  const k = state.knowledge || { memories: 0, skills: 0, uploads: 0, sources: 0 };
  const kCount = Math.min(32, Math.max(0,
    (k.skills || 0) + (k.memories || 0) + (k.uploads || 0) + (k.sources || 0)));
  if (kCount > 0) {
    ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < kCount; i++) {
      const kind = knowledgeKind(i, k);
      const band = knowledgeBand(kind);
      const a = (i * 2.399963) + t * (0.03 + (i % 5) * 0.004) * (i % 2 ? 1 : -1);
      const wob = Math.sin(t * 0.7 + i * 1.7) * base * 0.03;
      const rx = base * band + wob;
      const ry = base * (band * 0.74) + wob * 0.5;
      const x = Math.cos(a) * rx;
      const y = Math.sin(a) * ry;
      const tw = 0.55 + 0.45 * Math.sin(t * 1.2 + i * 0.9);
      ctx.globalAlpha = (0.05 + tw * 0.08) * (0.7 + energy * 0.4);
      ctx.fillStyle = kind === "upload" ? palette.accent
        : (kind === "source" ? palette.core : (kind === "skill" ? palette.core : "rgba(210,240,255,0.9)"));
      const sz = kind === "upload" ? 1.8 : (kind === "source" ? 1.6 : 1.4);
      ctx.beginPath();
      ctx.arc(x, y, sz * ui * (0.8 + tw * 0.4), 0, Math.PI * 2);
      ctx.fill();
      const learningNow = state.current === "learning" || state.activeStages.has("memory");
      if (i % (learningNow ? 2 : 3) === 0) {
        const j = (i + 2) % kCount;
        const a2 = (j * 2.399963) + t * (0.03 + (j % 5) * 0.004) * (j % 2 ? 1 : -1);
        const band2 = knowledgeBand(knowledgeKind(j, k));
        const x2 = Math.cos(a2) * base * band2;
        const y2 = Math.sin(a2) * base * band2 * 0.74;
        const d = Math.hypot(x2 - x, y2 - y);
        if (d < base * 0.9) {
          ctx.strokeStyle = palette.ring;
          ctx.globalAlpha = (learningNow ? 0.10 : 0.03) + tw * 0.03;
          ctx.lineWidth = learningNow ? 1.4 : 1;
          ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x2, y2); ctx.stroke();
        }
      }
    }
    ctx.globalCompositeOperation = "source-over";
  }
  // SIMPLIFY #4: hologram tick marks belong to the original ring layer.
  if (!SIMPLIFY.singleOrbitRing) {
    const tickR = base * 1.48;
    const tickRot = t * 0.12;
    ctx.strokeStyle = palette.accent;
    ctx.lineWidth = 1;
    for (let i = 0; i < 48; i++) {
      const a = tickRot + (i / 48) * Math.PI * 2;
      const major = i % 6 === 0;
      const len = (major ? base * 0.06 : base * 0.03) * (1 + 0.15 * Math.sin(t * 0.8 + i));
      ctx.globalAlpha = ((major ? 0.05 : 0.025) + energy * 0.05) * FLAIR;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * tickR, Math.sin(a) * tickR * 0.74);
      ctx.lineTo(Math.cos(a) * (tickR + len), Math.sin(a) * (tickR + len) * 0.74);
      ctx.stroke();
    }
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

  // SIMPLIFY #5: fewer dots, slower motion, much dimmer; original array kept intact.
  const particleDim = SIMPLIFY.minimalParticles ? 0.35 : (0.55 + 0.45 * FLAIR);
  const particleRate = SIMPLIFY.minimalParticles ? 0.4 : (0.7 + 0.3 * FLAIR);
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  const speakDim = speakingBoost ? 0.55 : 1.0;
  for (const p of particleDots) {
    const speed = p.speed * particleRate * (1 + audio * 0.6) * (speakingBoost ? 0.85 : 1.0);
    const a = p.angle + t * speed;
    const r = base * p.radius + Math.sin(t * (1.0 + audio * 0.5) + p.phase) * base * (0.04 + audio * 0.05);
    const x = cx + Math.cos(a) * r;
    const y = cy + Math.sin(a) * r * 0.74;
    ctx.globalAlpha = (0.14 + p.depth * 0.30 * (0.6 + energy * 0.45 + audio * 0.25)) * speakDim * particleDim;
    ctx.fillStyle = palette.accent;
    ctx.beginPath();
    ctx.arc(x, y, p.size * (1.2 + audio * 0.35) * (speakingBoost ? 0.9 : 1.0), 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  // SIMPLIFY #5: same treatment for the warm firefly dots.
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (const f of fireflyDots) {
    const aa = f.a + t * f.s * particleRate * (state.current === "thinking" ? 0.7 : state.current === "speaking" ? 1.3 : 1.0);
    const rr = base * f.r + Math.sin(t * 0.7 + f.bob) * base * 0.08;
    const x = cx + Math.cos(aa) * rr;
    const y = cy + Math.sin(aa) * rr * 0.74 + Math.sin(t * 0.9 + f.bob) * base * 0.03;
    const tw = 0.35 + 0.65 * Math.pow(0.5 + 0.5 * Math.sin(t * (1.2 + f.tw) + f.tw), 2);
    const alpha = (0.06 + tw * 0.18) * (0.7 + energy * 0.5) * (speakingBoost ? 0.8 : 1.0) * particleDim;
    const col = f.warm > 0.55 ? palette.accent : (f.warm > 0.25 ? palette.core : "#fff6d8");
    ctx.globalAlpha = alpha;
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.arc(x, y, f.size * (0.9 + tw * 0.8), 0, Math.PI * 2);
    ctx.fill();

  }
  ctx.restore();

  function drawOrbitalTracks(front) {
    const tracks = [
      { rx: base * 1.52, ry: base * 0.62, tilt: 0.72, rotation: -0.48, phase: 0.4, speed: 0.22, color: "rgba(255,207,130,0.78)" },
      { rx: base * 1.34, ry: base * 0.82, tilt: 0.96, rotation: 0.58, phase: 2.2, speed: -0.16, color: palette.core },
      { rx: base * 1.78, ry: base * 0.48, tilt: 0.54, rotation: 0.08, phase: 4.1, speed: 0.13, color: palette.accent },
    ];
    ctx.save();
    ctx.translate(cx, cy);
    ctx.globalCompositeOperation = "lighter";
    for (const track of tracks) {
      ctx.save();
      const trackRotation = track.rotation + Math.sin(t * 0.12 + track.phase) * 0.035;
      ctx.rotate(trackRotation);
      const start = front ? 0 : Math.PI;
      const end = front ? Math.PI : Math.PI * 2;
      ctx.beginPath();
      for (let i = 0; i <= 56; i++) {
        const angle = start + (end - start) * i / 56;
        const x = Math.cos(angle) * track.rx;
        const y = Math.sin(angle) * track.ry * Math.cos(track.tilt);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.globalAlpha = front ? 0.38 + energy * 0.08 : 0.13 + energy * 0.04;
      ctx.strokeStyle = track.color;
      ctx.lineWidth = Math.max(0.8, (front ? 1.25 : 0.9) * ui);
      ctx.stroke();

      const angle = ((t * track.speed + track.phase) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2);
      if (front && Math.sin(angle) > 0) {
        const x = Math.cos(angle) * track.rx;
        const y = Math.sin(angle) * track.ry * Math.cos(track.tilt);
        const rotatedX = x * Math.cos(trackRotation) - y * Math.sin(trackRotation);
        const rotatedY = x * Math.sin(trackRotation) + y * Math.cos(trackRotation);
        ctx.globalAlpha = 0.82;
        ctx.shadowBlur = 9 * ui;
        ctx.shadowColor = track.color;
        ctx.fillStyle = palette.accent;
        ctx.beginPath();
        ctx.arc(rotatedX, rotatedY, 2.1 * ui, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }
    ctx.restore();
  }

  drawOrbitalTracks(false);

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
  const reactorPulse = reduceMotion ? 1 : 0.94 + Math.sin(t * 1.7) * 0.06;

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

  ctx.globalCompositeOperation = "source-over";
  ctx.save();
  blobPath(radius, 0.4, 1.0 + audio * 0.2, innerLiquidAmp);
  ctx.clip();
  const scanAngle = reduceMotion ? -Math.PI * 0.62 : t * 0.32;
  const scanGlow = ctx.createLinearGradient(
    cx + Math.cos(scanAngle - 0.7) * radius,
    cy + Math.sin(scanAngle - 0.7) * radius,
    cx + Math.cos(scanAngle + 0.7) * radius,
    cy + Math.sin(scanAngle + 0.7) * radius
  );
  scanGlow.addColorStop(0, "rgba(255,255,255,0)");
  scanGlow.addColorStop(0.5, "rgba(255,255,255,0.07)");
  scanGlow.addColorStop(1, "rgba(255,255,255,0)");
  ctx.globalAlpha = 0.7;
  ctx.fillStyle = scanGlow;
  ctx.fillRect(cx - radius, cy - radius, radius * 2, radius * 2);

  const sphereShade = ctx.createRadialGradient(
    cx - radius * 0.34, cy - radius * 0.4, radius * 0.06,
    cx + radius * 0.12, cy + radius * 0.12, radius * 1.18
  );
  sphereShade.addColorStop(0, "rgba(255,255,255,0)");
  sphereShade.addColorStop(0.58, "rgba(4,12,24,0.04)");
  sphereShade.addColorStop(1, "rgba(2,7,18,0.62)");
  ctx.globalAlpha = 0.72;
  ctx.fillStyle = sphereShade;
  ctx.fillRect(cx - radius * 1.2, cy - radius * 1.2, radius * 2.4, radius * 2.4);
  ctx.restore();

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

  ctx.globalCompositeOperation = "lighter";
  const flare = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * 0.42);
  flare.addColorStop(0, "rgba(255,255,255,0.95)");
  flare.addColorStop(0.08, palette.accent);
  flare.addColorStop(0.32, palette.core);
  flare.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = (0.18 + energy * 0.14 + audio * 0.08) * flicker;
  ctx.fillStyle = flare;
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.42 * reactorPulse, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 0.76;
  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.arc(cx, cy, Math.max(1.2, radius * 0.025), 0, Math.PI * 2);
  ctx.fill();

  ctx.restore();

  drawOrbitalTracks(true);

  // Fine segmented hardware rings add a restrained instrument-panel finish.
  ctx.save();
  ctx.translate(cx, cy);
  ctx.globalCompositeOperation = "lighter";
  for (let ring = 0; ring < 2; ring++) {
    const rr = radius * (ring === 0 ? 1.13 : 1.24);
    const segments = ring === 0 ? 32 : 16;
    const rotation = (ring === 0 ? 1 : -1) * t * (ring === 0 ? 0.08 : 0.045);
    ctx.strokeStyle = ring === 0 ? palette.ring : palette.accent;
    ctx.lineWidth = Math.max(0.7, ui * (ring === 0 ? 0.8 : 1));
    ctx.globalAlpha = ring === 0 ? 0.22 + energy * 0.08 : 0.13 + energy * 0.05;
    for (let i = 0; i < segments; i++) {
      if (ring === 0 && i % 4 === 3) continue;
      const start = rotation + i * Math.PI * 2 / segments;
      const span = (Math.PI * 2 / segments) * (ring === 0 ? 0.58 : 0.42);
      ctx.beginPath();
      ctx.arc(0, 0, rr, start, start + span);
      ctx.stroke();
    }
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

  // Cloud preview stays simple: skip the tendril/node layer there.
  if (!cloudOrbOnly) {
    // Smart module nodes: curved traces from the orb to live status chips.
    const stages = [
      { key: "input", label: "Input" },
      { key: "route", label: "Route" },
      { key: "tools", label: "Tools" },
      { key: "skill", label: "Skill" },
      { key: "memory", label: "Memory" },
      { key: "agents", label: "Agents" },
      { key: "model", label: "Model" },
      { key: "voice", label: "Voice" },
    ];
    const orbit = base * 2.2;
    const labelFont = Math.round(10.5 * ui);
    const valueFont = Math.max(8, Math.round(8.5 * ui));
    const nodeCount = stages.length;
    // SIMPLIFY #2: if several stages are active, only the newest one keeps its label.
    const activeKeys = stages.filter((s) => stageActive(s.key)).map((s) => s.key);
    const primaryLabelKey = state.lastActiveStage && activeKeys.includes(state.lastActiveStage.key)
      ? state.lastActiveStage.key
      : (activeKeys.includes("model") ? "model" : activeKeys[activeKeys.length - 1] || null);

    // faint dashed bus tying the modules together
    ctx.save();
    ctx.setLineDash([2 * ui, 6 * ui]);
    ctx.globalAlpha = 0.10 + energy * 0.05;
    ctx.strokeStyle = palette.ring;
    ctx.lineWidth = Math.max(0.8, ui);
    ctx.beginPath();
    ctx.ellipse(cx, cy, orbit, orbit * 0.74, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();

    for (let i = 0; i < nodeCount; i++) {
      const st = stages[i];
      const angle = -Math.PI / 2 + i * (Math.PI * 2 / nodeCount);
      const dirX = Math.cos(angle);
      const dirY = Math.sin(angle);
      const x = cx + dirX * orbit;
      const y = cy + dirY * orbit * 0.74;
      const ix = cx + dirX * base * 1.18;
      const iy = cy + dirY * base * 1.18 * 0.74;
      const active = stageActive(st.key);
      const value = stageValue(st.key);
      // SIMPLIFY #2: inactive labels fade to zero; hover or double-click reveals every label.
      const revealAll = !SIMPLIFY.activeNodeLabelOnly || state.revealAllLabels || state.pointer.inside;
      const showLabel = revealAll || st.key === primaryLabelKey;
      const prevAlpha = state.labelAlpha[st.key] ?? 0;
      const labelAlpha = prevAlpha + ((showLabel ? 1 : 0) - prevAlpha) * (reduceMotion ? 1 : 0.14);
      state.labelAlpha[st.key] = labelAlpha;

      // gentle alternating bend so the traces read as circuitry, not spokes
      const dx = x - ix;
      const dy = y - iy;
      const seg = Math.hypot(dx, dy) || 1;
      const bend = (i % 2 === 0 ? 1 : -1) * base * 0.16;
      const cxp = ix + dx * 0.5 - (dy / seg) * bend;
      const cyp = iy + dy * 0.5 + (dx / seg) * bend;

      ctx.save();
      ctx.lineCap = "round";
      ctx.globalAlpha = active ? 0.5 + energy * 0.12 : 0.08;
      ctx.strokeStyle = active ? palette.core : palette.ring;
      ctx.lineWidth = Math.max(0.9, (active ? 1.4 : 1) * ui);
      ctx.beginPath();
      ctx.moveTo(ix, iy);
      ctx.quadraticCurveTo(cxp, cyp, x, y);
      ctx.stroke();

      if (active) {
        const flow = (t * (0.28 + energy * 0.22) + i * 0.13) % 1;
        const inv = 1 - flow;
        const px = inv * inv * ix + 2 * inv * flow * cxp + flow * flow * x;
        const py = inv * inv * iy + 2 * inv * flow * cyp + flow * flow * y;
        ctx.globalAlpha = 0.95;
        ctx.fillStyle = palette.accent;
        ctx.beginPath();
        ctx.arc(px, py, 2 * ui, 0, Math.PI * 2);
        ctx.fill();

        const g = ctx.createRadialGradient(x, y, 0, x, y, 20 * ui);
        g.addColorStop(0, palette.glow);
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.globalAlpha = 0.9;
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, 20 * ui, 0, Math.PI * 2);
        ctx.fill();
      }

      const dotR = (active ? 4.4 : 2.8) * ui;
      ctx.globalAlpha = active ? 1 : 0.45;
      ctx.fillStyle = active ? palette.core : "rgba(130,175,195,0.6)";
      ctx.beginPath();
      ctx.arc(x, y, dotR, 0, Math.PI * 2);
      ctx.fill();
      if (active) {
        ctx.globalAlpha = 0.9;
        ctx.fillStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(x, y, Math.max(1, 1.5 * ui), 0, Math.PI * 2);
        ctx.fill();
      }

      // skill branches fan sideways so they don't sit under the status chip
      if (st.key === "skill" && state.knownSkills.length) {
        const dir = Math.cos(angle) >= 0 ? 1 : -1;
        const baseAng = angle - dir * 0.65;
        const list = state.knownSkills.slice(0, 5);
        for (let j = 0; j < list.length; j++) {
          const name = list[j];
          const isActive = active && state.activeSkill === name;
          const a2 = baseAng + (j - (list.length - 1) / 2) * 0.16 * dir;
          const len = (20 + j * 8) * ui;
          const sx = x + Math.cos(a2) * len;
          const sy = y + Math.sin(a2) * len * 0.9;
          ctx.globalAlpha = isActive ? 0.55 : 0.16;
          ctx.strokeStyle = isActive ? palette.core : palette.ring;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(x, y);
          ctx.quadraticCurveTo(x + Math.cos(a2) * len * 0.5, y + Math.sin(a2) * len * 0.45, sx, sy);
          ctx.stroke();
          ctx.globalAlpha = isActive ? 0.95 : 0.32;
          ctx.fillStyle = isActive ? palette.accent : "rgba(150,195,210,0.55)";
          ctx.beginPath();
          ctx.arc(sx, sy, isActive ? 2.6 * ui : 1.8 * ui, 0, Math.PI * 2);
          ctx.fill();
          if (isActive || (active && j === 0)) {
            const bx = sx + dir * 6 * ui;
            const by = sy - 2 * ui;
            ctx.font = `${isActive ? 500 : 400} ${Math.max(8, labelFont - 2)}px Inter, "Segoe UI", system-ui, sans-serif`;
            ctx.textAlign = dir > 0 ? "left" : "right";
            ctx.globalAlpha = isActive ? 0.9 : 0.42;
            ctx.fillStyle = isActive ? palette.accent : "rgba(170,210,225,0.6)";
            const txt = name.length > 18 ? name.slice(0, 17) + "…" : name;
            ctx.fillText(txt, bx, by);
          }
        }
      }

      // SIMPLIFY #2: compact status chip, drawn only while its fade alpha is visible.
      if (labelAlpha > 0.02) {
        ctx.font = `600 ${labelFont}px Inter, "Segoe UI", system-ui, sans-serif`;
        const wLabel = ctx.measureText(st.label).width;
        ctx.font = `400 ${valueFont}px Inter, "Segoe UI", system-ui, sans-serif`;
        const wValue = ctx.measureText(value).width;
        const pw = Math.max(wLabel, wValue) + 14 * ui;
        const ph = 28 * ui;
        const align = Math.abs(dirX) < 0.25 ? "center" : (dirX > 0 ? "left" : "right");
        const lx = x + dirX * 13 * ui;
        const ly = y + dirY * 13 * ui;
        const px = align === "center" ? lx - pw / 2 : align === "left" ? lx - 3 * ui : lx - pw + 3 * ui;
        const py = ly - ph / 2;
        roundedRect(px, py, pw, ph, 5 * ui);
        ctx.globalAlpha = (active ? 0.82 : 0.38) * labelAlpha;
        ctx.fillStyle = active ? "rgba(10,20,24,0.88)" : "rgba(10,18,22,0.55)";
        ctx.fill();
        ctx.globalAlpha = (active ? 0.45 : 0.12) * labelAlpha;
        ctx.strokeStyle = active ? palette.core : palette.ring;
        ctx.lineWidth = Math.max(0.8, ui);
        ctx.stroke();

        const tx = align === "center" ? lx : align === "left" ? px + 7 * ui : px + pw - 7 * ui;
        ctx.textAlign = align;
        ctx.textBaseline = "middle";
        ctx.globalAlpha = (active ? 1 : 0.55) * labelAlpha;
        ctx.fillStyle = active ? palette.core : "rgba(150,195,210,0.6)";
        ctx.font = `600 ${labelFont}px Inter, "Segoe UI", system-ui, sans-serif`;
        ctx.fillText(st.label, tx, ly - 6 * ui);
        ctx.globalAlpha = (active ? 0.85 : 0.4) * labelAlpha;
        ctx.fillStyle = active ? palette.accent : "rgba(150,195,210,0.5)";
        ctx.font = `400 ${valueFont}px Inter, "Segoe UI", system-ui, sans-serif`;
        ctx.fillText(value, tx, ly + 6 * ui);
      }

      ctx.restore();
    }
  }

  requestAnimationFrame(draw);
}

function connect() {
  if (!window.EventSource) {
    setLink(false);
    setState("error", "EventSource not supported");
    return;
  }
  const source = new EventSource(adaServiceUrl("/events"));
  // Do NOT reset the view on reconnect: a dropped SSE connection during a long
  // task would otherwise flip the orb back to IDLE. resetView() is called once
  // at startup below.
  source.onopen = () => { setLink(true); loadUploads(); loadKnowledge(); };
  source.onmessage = (msg) => {
    try { handleEvent(JSON.parse(msg.data)); } catch (_) { }
  };
  source.onerror = () => setLink(false);
}

async function loadKnowledge() {
  try {
    const res = await fetch(adaServiceUrl("/api/knowledge"), { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    state.knowledge.memories = Number(data.memories || 0);
    state.knowledge.skills = Number(data.skills || 0);
    state.knowledge.uploads = Number(data.uploads || 0);
    state.knowledge.sources = Number(data.sources || 0);
    state.knowledge.connections = Number(data.connections || 0)
      || state.knowledge.memories + state.knowledge.skills + state.knowledge.uploads + state.knowledge.sources;
  } catch (_) { }
}

async function loadUploads() {
  if (!els.uploadList) return;
  try {
    const res = await fetch(adaServiceUrl("/api/uploads"), { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const items = Array.isArray(data.uploads) ? data.uploads : [];
    state.knowledge.uploads = items.length;
    state.knowledge.connections = state.knowledge.memories + state.knowledge.skills
      + state.knowledge.uploads + state.knowledge.sources;
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
      const res = await fetch(adaServiceUrl("/api/upload"), {
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

// SIMPLIFY #2: hover reveals all node labels; double-click keeps them revealed.
if (els.canvas) {
  els.canvas.addEventListener("mousemove", (event) => {
    const rect = els.canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    state.pointer.x = x;
    state.pointer.y = y;
    // Only the outer node band counts as "hovering the labels", not the whole canvas.
    const minDim = Math.min(rect.width, rect.height);
    const base = Math.max(50, minDim * (minDim < 420 ? 0.155 : 0.18));
    const distance = Math.hypot(x - rect.width / 2, (y - rect.height * 0.43) / 0.74);
    state.pointer.inside = distance > base * 1.45 && distance < base * 2.9;
  });
  els.canvas.addEventListener("mouseleave", () => { state.pointer.inside = false; });
  els.canvas.addEventListener("dblclick", () => { state.revealAllLabels = !state.revealAllLabels; });
}
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
requestAnimationFrame(draw);
if (!cloudOrbOnly) {
  setupUploads();
  loadUploads();
  loadKnowledge();
  connect();
}
