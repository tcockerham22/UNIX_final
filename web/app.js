"use strict";

const els = {
  canvas: document.getElementById("orb"),
  stateText: document.getElementById("state-text"),
  stateLabel: document.getElementById("state-label"),
  stateDetail: document.getElementById("state-detail"),
  modelText: document.getElementById("model-text"),
  memoryText: document.getElementById("memory-text"),
  linkText: document.getElementById("link-text"),
  eventCount: document.getElementById("event-count"),
  events: document.getElementById("events"),
  messages: document.getElementById("messages"),
  latency: document.getElementById("latency"),
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
  idle: {
    core: "#5ad1ff",
    glow: "rgba(38, 148, 220, 0.18)",
    ring: "rgba(90, 209, 255, 0.42)",
    accent: "#8fe9ff",
  },
  listening: {
    core: "#52ffd2",
    glow: "rgba(40, 220, 170, 0.2)",
    ring: "rgba(82, 255, 210, 0.46)",
    accent: "#b6ffec",
  },
  transcribing: {
    core: "#52ffd2",
    glow: "rgba(40, 220, 170, 0.2)",
    ring: "rgba(82, 255, 210, 0.46)",
    accent: "#b6ffec",
  },
  thinking: {
    core: "#ffc857",
    glow: "rgba(255, 168, 40, 0.2)",
    ring: "rgba(255, 200, 87, 0.46)",
    accent: "#ffe0a0",
  },
  speaking: {
    core: "#7dffab",
    glow: "rgba(70, 230, 140, 0.22)",
    ring: "rgba(125, 255, 171, 0.48)",
    accent: "#c7ffd8",
  },
  warming: {
    core: "#b78cff",
    glow: "rgba(140, 90, 255, 0.2)",
    ring: "rgba(183, 140, 255, 0.46)",
    accent: "#dcc8ff",
  },
  error: {
    core: "#ff5c7a",
    glow: "rgba(255, 60, 100, 0.2)",
    ring: "rgba(255, 92, 122, 0.5)",
    accent: "#ffb0c0",
  },
};

const state = {
  current: "idle",
  detail: "awaiting input",
  voiceActive: 0,
  activeStages: new Set(),
  stageTimers: new Map(),
  assistantBody: null,
  currentAssistant: "",
  lastTokenAt: 0,
  lastUserAt: 0,
  eventCount: 0,
};

const particles = Array.from({ length: 110 }, () => ({
  angle: Math.random() * Math.PI * 2,
  radius: 1.35 + Math.random() * 1.15,
  speed: (Math.random() * 0.45 + 0.1) * (Math.random() < 0.5 ? -1 : 1),
  size: Math.random() * 1.6 + 0.4,
  phase: Math.random() * Math.PI * 2,
  depth: Math.random(),
}));

function truncate(value, max = 160) {
  const text = String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function summarizeArgs(args) {
  if (!args || typeof args !== "object") {
    return "";
  }
  return truncate(
    Object.entries(args)
      .map(([key, value]) => {
        const rendered = typeof value === "string" ? value : JSON.stringify(value);
        return `${key}=${rendered}`;
      })
      .join(" "),
    110,
  );
}

function setLink(online) {
  els.linkText.textContent = online ? "LIVE" : "OFFLINE";
  els.linkText.classList.toggle("online", online);
  els.linkText.classList.toggle("offline", !online);
}

function setState(name, detail) {
  const next = name || "idle";
  const nextDetail = detail || "";
  const changed = state.current !== next || state.detail !== nextDetail;
  state.current = next;
  state.detail = nextDetail;
  document.body.dataset.state = next;
  els.stateText.textContent = STATE_LABELS[next] || next.toUpperCase();
  els.stateLabel.textContent = STATE_LABELS[next] || next.toUpperCase();
  els.stateDetail.textContent = nextDetail || "awaiting input";
  if (next === "idle") {
    for (const timer of state.stageTimers.values()) {
      clearTimeout(timer);
    }
    state.stageTimers.clear();
    state.activeStages.clear();
    state.voiceActive = 0;
  }
  return changed;
}

function activateStage(stage, ttl = 0) {
  state.activeStages.add(stage);
  const existing = state.stageTimers.get(stage);
  if (existing) {
    clearTimeout(existing);
    state.stageTimers.delete(stage);
  }
  if (ttl > 0) {
    const timer = setTimeout(() => {
      state.activeStages.delete(stage);
      state.stageTimers.delete(stage);
    }, ttl);
    state.stageTimers.set(stage, timer);
  }
}

function stageActive(stage) {
  if (stage === "model") {
    return state.current === "thinking" || state.current === "warming";
  }
  if (stage === "input") {
    return state.current === "listening" || state.current === "transcribing";
  }
  if (stage === "voice") {
    return state.voiceActive > 0 || state.current === "speaking";
  }
  return state.activeStages.has(stage);
}

function logEvent(type, text, extraClass = "") {
  if (!text) {
    return;
  }
  const row = document.createElement("div");
  row.className = `event ev-${type}${extraClass ? ` ${extraClass}` : ""}`;
  const time = document.createElement("span");
  time.className = "ev-time";
  time.textContent = new Date().toLocaleTimeString([], { hour12: false });
  const kind = document.createElement("span");
  kind.className = "ev-type";
  kind.textContent = type;
  const body = document.createElement("span");
  body.className = "ev-text";
  body.textContent = text;
  row.append(time, kind, body);
  els.events.append(row);
  while (els.events.children.length > 90) {
    els.events.firstElementChild.remove();
  }
  els.events.scrollTop = els.events.scrollHeight;
  state.eventCount += 1;
  els.eventCount.textContent = state.eventCount;
}

function scrollMessages() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

function addMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.className = `message ${role}`;
  const label = document.createElement("div");
  label.className = "msg-label";
  label.textContent = role === "user" ? "YOU" : "ADA";
  const body = document.createElement("div");
  body.className = "msg-body";
  body.textContent = text;
  wrap.append(label, body);
  els.messages.append(wrap);
  while (els.messages.children.length > 40) {
    els.messages.firstElementChild.remove();
  }
  scrollMessages();
  return body;
}

function appendToken(text) {
  if (!text) {
    return;
  }
  if (!state.assistantBody) {
    state.assistantBody = addMessage("ada", "");
    state.assistantBody.parentElement.classList.add("streaming");
    state.currentAssistant = "";
  }
  state.currentAssistant += text;
  state.assistantBody.textContent = state.currentAssistant;
  state.lastTokenAt = performance.now();
  scrollMessages();
}

function finishAssistant(text) {
  if (!state.assistantBody) {
    state.assistantBody = addMessage("ada", "");
  }
  if (text) {
    state.currentAssistant = text;
  }
  state.assistantBody.textContent = state.currentAssistant;
  state.assistantBody.parentElement.classList.remove("streaming");
  scrollMessages();
}

function resetView() {
  for (const timer of state.stageTimers.values()) {
    clearTimeout(timer);
  }
  state.stageTimers.clear();
  state.activeStages.clear();
  state.voiceActive = 0;
  state.assistantBody = null;
  state.currentAssistant = "";
  state.lastTokenAt = 0;
  state.lastUserAt = 0;
  state.eventCount = 0;
  els.events.innerHTML = "";
  els.messages.innerHTML = "";
  els.eventCount.textContent = "0";
  els.latency.textContent = "—";
  els.modelText.textContent = "—";
  els.memoryText.textContent = "—";
  setState("idle", "awaiting input");
}

function handleEvent(event) {
  const data = event.data || {};
  switch (event.type) {
    case "session": {
      els.modelText.textContent = `${data.quick} / ${data.deep}`;
      els.memoryText.textContent = data.memories ?? "—";
      logEvent(
        "session",
        `${data.user || "session"} · ${data.input} · tools ${
          data.tools ? "on" : "off"
        } · mem ${data.memories} · skills ${data.skills}`,
      );
      break;
    }
    case "user": {
      addMessage("user", data.text);
      state.assistantBody = null;
      state.currentAssistant = "";
      state.lastUserAt = performance.now();
      els.latency.textContent = "—";
      logEvent("user", truncate(data.text, 140));
      break;
    }
    case "route": {
      els.modelText.textContent = `${data.label}: ${data.model}`;
      activateStage("route", 2200);
      logEvent(
        "route",
        `${data.label} · ${data.model} · tools ${data.tools ? "on" : "off"}`,
      );
      break;
    }
    case "state": {
      const changed = setState(data.state, data.detail);
      if (changed) {
        logEvent(
          "state",
          `${data.state}${data.detail ? ` · ${data.detail}` : ""}`,
        );
      }
      break;
    }
    case "token": {
      appendToken(data.text);
      break;
    }
    case "tool": {
      if (data.status === "start") {
        activateStage("tools");
        logEvent("tool", `${data.name} ${summarizeArgs(data.args)}`);
      } else if (data.status === "done") {
        activateStage("tools", 2500);
        logEvent("tool", `${data.name} → ${truncate(data.result, 150)}`);
      } else {
        logEvent("error", `${data.name} failed: ${truncate(data.result, 150)}`);
      }
      break;
    }
    case "memory": {
      if (typeof data.count === "number") {
        els.memoryText.textContent = data.count;
      }
      const detail =
        data.action === "add"
          ? `+ ${truncate(data.fact, 150)}`
          : `− ${truncate((data.facts || []).join("; "), 150)}`;
      logEvent("memory", detail);
      break;
    }
    case "assistant": {
      finishAssistant(data.text);
      logEvent("reply", truncate(data.text, 150));
      if (state.lastUserAt) {
        els.latency.textContent = `${(
          (performance.now() - state.lastUserAt) /
          1000
        ).toFixed(1)}s`;
      }
      break;
    }
    case "voice": {
      if (data.action === "start") {
        state.voiceActive += 1;
        logEvent("voice", `speak: ${truncate(data.text, 110)}`);
      } else if (data.action === "end") {
        state.voiceActive = Math.max(0, state.voiceActive - 1);
      }
      break;
    }
    case "error": {
      logEvent("error", truncate(data.message || "unknown error", 200));
      break;
    }
    default: {
      logEvent(event.type, truncate(JSON.stringify(data), 160));
    }
  }
}

function resizeCanvas() {
  const rect = els.canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  els.canvas.width = Math.max(1, Math.round(rect.width * dpr));
  els.canvas.height = Math.max(1, Math.round(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function drawOrb(now) {
  const width = els.canvas.clientWidth;
  const height = els.canvas.clientHeight;
  if (!width || !height) {
    requestAnimationFrame(drawOrb);
    return;
  }

  const t = reduceMotion ? 0 : now / 1000;
  const min = Math.min(width, height);
  const cx = width / 2;
  const cy = height / 2;
  const base = min * 0.17;
  const palette = PALETTES[state.current] || PALETTES.idle;
  const tokenHeat = Math.max(0, 1 - (now - state.lastTokenAt) / 700);
  const energy =
    (state.current === "thinking" || state.current === "warming"
      ? 0.68
      : state.current === "speaking"
        ? 0.82
        : state.current === "listening" || state.current === "transcribing"
          ? 0.55
          : state.current === "error"
            ? 0.34
            : state.voiceActive > 0
              ? 0.7
              : 0.18) +
    tokenHeat * 0.18;

  ctx.clearRect(0, 0, width, height);

  const glow = ctx.createRadialGradient(cx, cy, base * 0.2, cx, cy, base * 3.4);
  glow.addColorStop(0, palette.glow);
  glow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, width, height);

  ctx.save();
  ctx.translate(cx, cy);
  ctx.globalAlpha = 0.28 + energy * 0.26;
  ctx.strokeStyle = palette.ring;
  ctx.lineWidth = 1;
  for (let index = 0; index < 3; index += 1) {
    const rotation = t * (0.12 + index * 0.05) * (index % 2 ? 1 : -1);
    const radiusX = base * (1.6 + index * 0.22);
    const radiusY = base * (1.16 + index * 0.1);
    ctx.beginPath();
    ctx.ellipse(0, 0, radiusX, radiusY, rotation, 0, Math.PI * 2);
    ctx.setLineDash([2 + index, 8 + index * 3]);
    ctx.stroke();
    ctx.beginPath();
    ctx.ellipse(
      0,
      0,
      radiusX,
      radiusY,
      rotation,
      t * 0.7 + index,
      t * 0.7 + index + 0.9,
    );
    ctx.strokeStyle = palette.core;
    ctx.globalAlpha = 0.18 + energy * 0.2;
    ctx.stroke();
    ctx.strokeStyle = palette.ring;
    ctx.globalAlpha = 0.28 + energy * 0.26;
  }
  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (const particle of particles) {
    const angle = particle.angle + t * particle.speed;
    const radius =
      base * particle.radius +
      Math.sin(t * 0.9 + particle.phase) * base * 0.04;
    const x = cx + Math.cos(angle) * radius;
    const y = cy + Math.sin(angle) * radius * 0.74;
    ctx.globalAlpha = 0.14 + particle.depth * 0.42 * (0.6 + energy * 0.4);
    ctx.fillStyle = palette.accent;
    ctx.beginPath();
    ctx.arc(x, y, particle.size, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  const radius = base * (1 + Math.sin(t * 2.2) * 0.014 + energy * 0.025);
  const core = ctx.createRadialGradient(
    cx - radius * 0.28,
    cy - radius * 0.3,
    radius * 0.06,
    cx,
    cy,
    radius * 1.08,
  );
  core.addColorStop(0, "rgba(255,255,255,1)");
  core.addColorStop(0.16, palette.core);
  core.addColorStop(0.62, palette.core);
  core.addColorStop(1, "rgba(0,0,0,0)");
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  ctx.save();
  ctx.globalAlpha = 0.38 + energy * 0.2;
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.78, t * 0.3, t * 0.3 + 2.4);
  ctx.stroke();
  ctx.restore();

  if (state.voiceActive > 0 || state.current === "speaking") {
    const amplitude = base * (0.07 + energy * 0.045);
    ctx.save();
    ctx.globalAlpha = 0.72;
    ctx.strokeStyle = PALETTES.speaking.accent;
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    const samples = 80;
    for (let index = 0; index <= samples; index += 1) {
      const progress = index / samples;
      const x = cx - base * 1.55 + progress * base * 3.1;
      const y =
        cy +
        Math.sin(progress * Math.PI * 10 + t * 7) *
          amplitude *
          Math.sin(progress * Math.PI);
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
    ctx.restore();
  }

  const stages = [
    { key: "input", label: "INPUT" },
    { key: "route", label: "ROUTE" },
    { key: "tools", label: "TOOLS" },
    { key: "model", label: "MODEL" },
    { key: "voice", label: "VOICE" },
  ];
  const orbit = base * 2.25;

  for (let index = 0; index < stages.length; index += 1) {
    const stage = stages[index];
    const angle = -Math.PI / 2 + index * ((Math.PI * 2) / stages.length);
    const x = cx + Math.cos(angle) * orbit;
    const y = cy + Math.sin(angle) * orbit * 0.74;
    const active = stageActive(stage.key);

    ctx.save();
    ctx.globalAlpha = active ? 0.75 : 0.16;
    ctx.strokeStyle = active ? palette.core : palette.ring;
    ctx.lineWidth = active ? 1.2 : 1;
    ctx.beginPath();
    ctx.moveTo(
      cx + Math.cos(angle) * base * 1.1,
      cy + Math.sin(angle) * base * 1.1 * 0.74,
    );
    ctx.lineTo(x, y);
    ctx.stroke();

    if (active) {
      const nodeGlow = ctx.createRadialGradient(x, y, 0, x, y, 18);
      nodeGlow.addColorStop(0, palette.glow);
      nodeGlow.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = nodeGlow;
      ctx.beginPath();
      ctx.arc(x, y, 18, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalAlpha = active ? 1 : 0.55;
    ctx.fillStyle = active ? palette.core : "rgba(120,170,200,0.55)";
    ctx.beginPath();
    ctx.arc(x, y, active ? 4.5 : 3, 0, Math.PI * 2);
    ctx.fill();

    const labelX = cx + Math.cos(angle) * (orbit + 18);
    const labelY = cy + Math.sin(angle) * (orbit * 0.74 + 16);
    ctx.textAlign =
      Math.abs(Math.cos(angle)) < 0.2
        ? "center"
        : Math.cos(angle) > 0
          ? "left"
          : "right";
    ctx.textBaseline = "middle";
    ctx.fillStyle = active ? palette.core : "rgba(130,175,195,0.55)";
    ctx.font = `${active ? 700 : 600} 10px ui-monospace, monospace`;
    ctx.fillText(stage.label, labelX, labelY);
    ctx.restore();
  }

  requestAnimationFrame(drawOrb);
}

function connect() {
  if (!window.EventSource) {
    setLink(false);
    logEvent("error", "EventSource is not supported by this browser.");
    return;
  }
  const source = new EventSource("/events");
  source.onopen = () => {
    resetView();
    setLink(true);
  };
  source.onmessage = (message) => {
    try {
      handleEvent(JSON.parse(message.data));
    } catch (error) {
      logEvent("error", `bad event: ${error.message}`);
    }
  };
  source.onerror = () => {
    setLink(false);
  };
}

if (window.ResizeObserver) {
  new ResizeObserver(resizeCanvas).observe(els.canvas);
}
window.addEventListener("resize", resizeCanvas);
resizeCanvas();
resetView();
requestAnimationFrame(drawOrb);
connect();
