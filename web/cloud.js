"use strict";

const conversation = document.getElementById("conversation");
const emptyState = document.getElementById("empty-state");
const composer = document.getElementById("composer");
const messageInput = document.getElementById("message");
const sendButton = document.getElementById("send");
const notice = document.getElementById("notice");
const serviceState = document.getElementById("service-state");
const statusDot = document.getElementById("status-dot");
const orbFrame = document.getElementById("orb-frame");
const uploadFile = document.getElementById("upload-file");
const uploadButton = document.getElementById("upload-btn");
const filesToggle = document.getElementById("files-toggle");
const uploadsPopover = document.getElementById("uploads-popover");
const uploadStatus = document.getElementById("upload-status");
const uploadList = document.getElementById("upload-list");
const uploadCount = document.getElementById("upload-count");
const chatTab = document.getElementById("chat-tab");
const metricsTab = document.getElementById("metrics-tab");
const chatView = document.getElementById("chat-view");
const metricsView = document.getElementById("metrics-view");
const metricsRefresh = document.getElementById("metrics-refresh");
const metricsUpdated = document.getElementById("metrics-updated");
const metricsError = document.getElementById("metrics-error");
const maxUploadBytes = 25 * 1024 * 1024;
let metricsTimer = null;
const sameOriginFetch = { credentials: "same-origin" };
let orbState = "idle";
let orbDetail = "ready when you are";
let orbKnowledge = { memories: 0, skills: 0, uploads: 0, sources: 0, connections: 0 };
let orbLearningTimer = null;

function metricText(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toFixed(digits).replace(/\.0+$/, "");
}

function secondsText(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  return `${metricText(Number(value) * 1000, digits === 0 ? 0 : digits)} ms`;
}

function bytesText(value) {
  if (value === null || value === undefined) return "unknown free";
  return `${metricText(Number(value) / 1024 ** 3, 1)} GiB free`;
}

function renderMetricRows(container, rows) {
  container.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "metrics-empty";
    empty.textContent = "Nothing to report.";
    container.append(empty);
    return;
  }
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "metrics-row";
    const main = document.createElement("div");
    const label = document.createElement("div");
    label.className = "metrics-row-main";
    label.textContent = row.label;
    const detail = document.createElement("div");
    detail.className = "metrics-row-detail";
    detail.textContent = row.detail || "";
    main.append(label, detail);
    const value = document.createElement("span");
    value.className = row.warning ? "metrics-row-value is-warning" : "metrics-row-value";
    value.textContent = row.value;
    item.append(main, value);
    container.append(item);
  }
}

function renderMetrics(data) {
  document.getElementById("metric-web-replicas").textContent = metricText(data.web_replicas, 0);
  document.getElementById("metric-ai-shims").textContent = metricText(data.ai_shims, 0);
  document.getElementById("metric-requests").textContent = metricText(data.requests_per_second, 2);
  document.getElementById("metric-errors").textContent = metricText(data.errors_per_second, 2);
  document.getElementById("metric-latency").textContent = secondsText(data.average_response_seconds, 0);
  document.getElementById("metric-app-latency").textContent = secondsText(data.app_latency_p95_seconds, 0);
  document.getElementById("metric-first-token").textContent = secondsText(data.first_token_p95_seconds, 0);
  document.getElementById("metric-tokens").textContent = metricText(data.tokens_per_second, 1);
  document.getElementById("metric-cpu").textContent = `${metricText(data.cpu_percent, 0)}%`;
  document.getElementById("metric-memory").textContent = `${metricText(data.memory_percent, 0)}%`;
  document.getElementById("metric-containers").textContent = metricText(data.containers_running, 0);
  document.getElementById("metric-rag").textContent = metricText(data.rag_chunks, 0);

  metricsError.hidden = Boolean(data.ok);
  metricsError.textContent = data.ok ? "" : (data.error || "Metrics are unavailable.");
  metricsUpdated.textContent = data.ok
    ? `Updated ${new Date(data.generated_at).toLocaleTimeString()}`
    : "Waiting for Prometheus";

  renderMetricRows(
    document.getElementById("service-list"),
    (data.services || []).map((service) => ({
      label: service.name,
      detail: service.instance,
      value: service.up ? "Up" : "Down",
      warning: !service.up,
    })),
  );
  renderMetricRows(
    document.getElementById("disk-list"),
    (data.disks || []).map((disk) => ({
      label: disk.mountpoint,
      detail: bytesText(disk.available_bytes),
      value: `${metricText(disk.used_percent, 0)}% used`,
      warning: Number(disk.used_percent) >= 80,
    })),
  );
  renderMetricRows(
    document.getElementById("alert-list"),
    (data.alerts || []).map((alert) => ({
      label: alert.name,
      detail: alert.summary,
      value: alert.state,
      warning: true,
    })),
  );
}

async function loadMetrics() {
  metricsUpdated.textContent = "Loading metrics...";
  try {
    const response = await fetch("/api/metrics", { ...sameOriginFetch, cache: "no-store" });
    renderMetrics(await readJsonResponse(response));
  } catch (error) {
    metricsError.hidden = false;
    metricsError.textContent = error.message || "Metrics could not be loaded.";
    metricsUpdated.textContent = "Metrics unavailable";
  }
}

function setView(view) {
  const showMetrics = view === "metrics";
  chatView.hidden = showMetrics;
  metricsView.hidden = !showMetrics;
  chatTab.classList.toggle("is-active", !showMetrics);
  metricsTab.classList.toggle("is-active", showMetrics);
  chatTab.setAttribute("aria-selected", String(!showMetrics));
  metricsTab.setAttribute("aria-selected", String(showMetrics));
  window.clearInterval(metricsTimer);
  metricsTimer = null;
  if (showMetrics) {
    metricsView.scrollTop = 0;
    loadMetrics();
    metricsTimer = window.setInterval(loadMetrics, 15000);
  } else {
    scrollToBottom();
  }
}

function scrollToBottom() {
  conversation.scrollTop = conversation.scrollHeight;
}

function syncEmptyState() {
  if (!emptyState) return;
  const hasMessages = conversation.querySelector(".message");
  emptyState.hidden = Boolean(hasMessages);
}

function setServiceState(text, dotState) {
  serviceState.textContent = text;
  if (statusDot) {
    if (dotState) statusDot.dataset.state = dotState;
    else delete statusDot.dataset.state;
  }
}

function autoResizeTextarea() {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 160)}px`;
}

function setOrbState(state, detail, extra = {}) {
  orbState = state;
  orbDetail = detail;
  if (extra.knowledge) orbKnowledge = { ...orbKnowledge, ...extra.knowledge };
  if (orbFrame.contentWindow) {
    orbFrame.contentWindow.postMessage(
      {
        type: "ada-cloud-orb-state",
        state,
        detail,
        knowledge: orbKnowledge,
        learning: extra.learning || null,
      },
      window.location.origin,
    );
  }
}

orbFrame.addEventListener("load", () => setOrbState(orbState, orbDetail));

async function syncOrbKnowledge() {
  try {
    const response = await fetch("/api/knowledge", {
      ...sameOriginFetch,
      cache: "no-store",
    });
    if (!response.ok) return false;
    const data = await readJsonResponse(response);
    const next = {
      memories: Number(data.memories || 0),
      skills: Number(data.skills || 0),
      uploads: Number(data.uploads || 0),
      sources: Number(data.sources || 0),
      connections: Number(data.connections || 0),
    };
    const learned = Math.max(0, next.connections - orbKnowledge.connections);
    orbKnowledge = next;
    if (learned > 0) {
      setOrbState("learning", `${next.connections} connection${next.connections === 1 ? "" : "s"} learned`, {
        knowledge: next,
        learning: { new_connections: learned },
      });
      window.clearTimeout(orbLearningTimer);
      orbLearningTimer = window.setTimeout(() => {
        if (!sendButton.disabled) setOrbState("idle", "ready when you are");
      }, 1800);
      return true;
    }
    setOrbState(orbState, orbDetail, { knowledge: next });
  } catch (_) {
    // The orb keeps its last known state if the knowledge snapshot is unavailable.
  }
  return false;
}

function addMessage(role, text, sources = []) {
  const article = document.createElement("article");
  article.className = "message";
  article.dataset.role = role;

  const label = document.createElement("span");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : role === "error" ? "Notice" : "Ada";

  const content = document.createElement("div");
  content.className = "message-content";
  content.textContent = text;
  article.append(label, content);
  if (sources.length) {
    const sourceList = document.createElement("ul");
    sourceList.className = "message-sources";
    const heading = document.createElement("li");
    heading.className = "sources-heading";
    heading.textContent = "Sources";
    sourceList.append(heading);
    for (const source of sources) {
      const item = document.createElement("li");
      const chunk = Number.isInteger(source.chunk_idx)
        ? ` · chunk ${source.chunk_idx + 1}`
        : "";
      item.textContent = `${source.source}${chunk}`;
      sourceList.append(item);
    }
    article.append(sourceList);
  }
  conversation.append(article);
  syncEmptyState();
  scrollToBottom();
  return { article, content };
}

function renderSources(article, sources) {
  if (!article) return;
  article.querySelector(".message-sources")?.remove();
  if (!sources.length) return;
  const sourceList = document.createElement("ul");
  sourceList.className = "message-sources";
  const heading = document.createElement("li");
  heading.className = "sources-heading";
  heading.textContent = "Sources";
  sourceList.append(heading);
  for (const source of sources) {
    const item = document.createElement("li");
    const chunk = Number.isInteger(source.chunk_idx)
      ? ` · chunk ${source.chunk_idx + 1}`
      : "";
    item.textContent = `${source.source}${chunk}`;
    sourceList.append(item);
  }
  article.append(sourceList);
}

function addThinking() {
  const panel = document.createElement("section");
  panel.className = "thinking-panel";

  const title = document.createElement("div");
  title.className = "thinking-title";
  title.textContent = "Ada is thinking";

  const stages = document.createElement("div");
  stages.className = "thinking-stages";

  const reasoning = document.createElement("div");
  reasoning.className = "thinking-reasoning";
  reasoning.hidden = true;

  panel.append(title, stages, reasoning);
  conversation.append(panel);
  scrollToBottom();
  return { panel, title, stages, reasoning };
}

function setThinkingStage(thinking, data) {
  const key = String(data.key || "step");
  let row = Array.from(thinking.stages.children).find((node) => node.dataset.key === key);
  if (!row) {
    row = document.createElement("div");
    row.className = "thinking-stage";
    row.dataset.key = key;
    const marker = document.createElement("span");
    marker.className = "thinking-stage-marker";
    marker.setAttribute("aria-hidden", "true");
    const text = document.createElement("span");
    text.className = "thinking-stage-text";
    row.append(marker, text);
    thinking.stages.append(row);
  }
  row.dataset.status = data.status || "active";
  const detail = data.detail ? ` — ${data.detail}` : "";
  row.querySelector(".thinking-stage-text").textContent = `${data.label || key}${detail}`;
  scrollToBottom();
}

function finishThinking(thinking, failed = false) {
  for (const row of thinking.stages.children) {
    if (row.dataset.status === "active") {
      row.dataset.status = failed ? "error" : "done";
    }
  }
  thinking.title.textContent = failed ? "Thinking interrupted" : "How Ada worked";
  scrollToBottom();
}

function appendThought(thinking, text) {
  const content = String(text || "");
  if (!content.trim()) return;
  thinking.reasoning.hidden = false;
  if (!thinking.reasoning.querySelector(".thinking-reasoning-label")) {
    const label = document.createElement("span");
    label.className = "thinking-reasoning-label";
    label.textContent = "Model reasoning";
    thinking.reasoning.append(label);
  }
  const paragraph = document.createElement("p");
  paragraph.textContent = content;
  thinking.reasoning.append(paragraph);
  scrollToBottom();
}

async function readJsonResponse(response) {
  let result;
  try {
    result = await response.json();
  } catch {
    const message = response.ok
      ? "The server returned an unreadable response."
      : `The request failed (${response.status}). Please try again.`;
    throw new Error(message);
  }
  if (!result || typeof result !== "object") {
    throw new Error("The server returned an invalid response.");
  }
  if (!response.ok || !result.ok) {
    throw new Error(result.error || `The request failed (${response.status}).`);
  }
  return result;
}

function formatBytes(size) {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

function renderUploads(uploads) {
  uploadList.replaceChildren();
  uploadCount.textContent = String(uploads.length);

  if (!uploads.length) {
    const empty = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = "No documents uploaded yet.";
    empty.append(name);
    uploadList.append(empty);
    uploadStatus.textContent = "No documents uploaded yet.";
    return;
  }

  uploadStatus.textContent = `${uploads.length} document${uploads.length === 1 ? "" : "s"} saved to this chat.`;
  for (const upload of uploads) {
    const row = document.createElement("li");
    const name = document.createElement("span");
    const size = document.createElement("span");
    name.textContent = upload.name;
    name.title = upload.name;
    size.textContent = `${formatBytes(Number(upload.size || 0))} · ${
      upload.readable ? "text ready" : "stored only"
    }`;
    size.title = upload.readable
      ? "Ada can reference this document's extracted text."
      : "This file is stored, but its text format is not supported for chat yet.";
    row.append(name, size);
    uploadList.append(row);
  }
}

async function loadUploads() {
  try {
    const response = await fetch("/api/uploads", {
      ...sameOriginFetch,
      cache: "no-store",
    });
    const result = await readJsonResponse(response);
    renderUploads(result.uploads);
  } catch (error) {
    uploadStatus.textContent = error.message;
  }
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("Could not read the selected file."));
    reader.readAsDataURL(file);
  });
}

async function uploadSelectedFiles() {
  const files = Array.from(uploadFile.files || []);
  if (!files.length) {
    uploadStatus.textContent = "Choose one or more files first.";
    return;
  }
  if (files.some((file) => file.size > maxUploadBytes)) {
    uploadStatus.textContent = "Each file must be 25 MB or smaller.";
    uploadFile.value = "";
    return;
  }

  uploadButton.disabled = true;
  uploadsPopover.hidden = false;
  filesToggle.setAttribute("aria-expanded", "true");
  let uploaded = 0;
  let readableUploads = 0;
  try {
    for (const file of files) {
      uploadStatus.textContent = `Uploading ${file.name}…`;
      const data = await readFileAsDataUrl(file);
      const response = await fetch("/api/upload", {
        ...sameOriginFetch,
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: file.name, data }),
      });
      const result = await readJsonResponse(response);
      uploaded += 1;
      if (result.file?.readable) readableUploads += 1;
    }
    await loadUploads();
    await syncOrbKnowledge();
    uploadStatus.textContent = readableUploads === uploaded
      ? `Saved ${uploaded} file${uploaded === 1 ? "" : "s"}; text is ready for Ada to reference.`
      : `Saved ${uploaded} file${uploaded === 1 ? "" : "s"}. Ada cannot read the contents of some file types yet.`;
  } catch (error) {
    uploadStatus.textContent = uploaded
      ? `Saved ${uploaded} file${uploaded === 1 ? "" : "s"}. ${error.message}`
      : error.message;
    await loadUploads();
  } finally {
    uploadFile.value = "";
    uploadButton.disabled = false;
  }
}

function toggleUploadsPopover(forceOpen) {
  const isOpen = forceOpen ?? uploadsPopover.hidden;
  uploadsPopover.hidden = !isOpen;
  filesToggle.setAttribute("aria-expanded", String(isOpen));
}

chatTab.addEventListener("click", () => setView("chat"));
metricsTab.addEventListener("click", () => setView("metrics"));
metricsRefresh.addEventListener("click", loadMetrics);

uploadButton.addEventListener("click", () => uploadFile.click());
uploadFile.addEventListener("change", uploadSelectedFiles);
filesToggle.addEventListener("click", (event) => {
  event.stopPropagation();
  toggleUploadsPopover();
});

uploadsPopover.addEventListener("click", (event) => event.stopPropagation());

document.addEventListener("click", (event) => {
  if (uploadsPopover.hidden) return;
  if (event.target === filesToggle || filesToggle.contains(event.target)) return;
  if (uploadsPopover.contains(event.target)) return;
  toggleUploadsPopover(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !uploadsPopover.hidden) {
    toggleUploadsPopover(false);
    filesToggle.focus();
  }
});

async function loadHistory() {
  try {
    const response = await fetch("/api/chat/history", {
      ...sameOriginFetch,
      cache: "no-store",
    });
    const result = await readJsonResponse(response);
    for (const message of result.messages) {
      addMessage(message.role, message.content, message.sources || []);
    }
    syncEmptyState();
    setServiceState("Ready", "ready");
    setOrbState("idle", "ready when you are");
    await loadUploads();
    await syncOrbKnowledge();
  } catch (error) {
    setServiceState("Unavailable", "error");
    notice.textContent = error.message;
    setOrbState("error", "chat history unavailable");
  }
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message || sendButton.disabled) return;

  notice.textContent = "";
  addMessage("user", message);
  const thinking = addThinking();
  messageInput.value = "";
  autoResizeTextarea();
  sendButton.disabled = true;
  messageInput.disabled = true;
  setServiceState("Thinking", "thinking");
  setOrbState("thinking", "thinking");

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 120000);

  try {
    const response = await fetch("/api/rag/chat", {
      ...sameOriginFetch,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const error = await readJsonResponse(response);
      throw new Error(error.error || "Ada could not answer right now.");
    }
    if (response.headers.get("content-type")?.includes("application/json")) {
      const result = await readJsonResponse(response);
      finishThinking(thinking);
      addMessage("assistant", result.answer, result.sources || []);
      setServiceState("Ready", "ready");
      const learned = await syncOrbKnowledge();
      if (!learned) setOrbState("speaking", "reply complete");
      return;
    }
    if (!response.body) {
      throw new Error("The browser could not open the streamed response.");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    let answer = "";
    let sources = [];
    let assistantMessage = null;
    let completed = false;

    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value || new Uint8Array(), { stream: !done });
      let boundary = pending.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = pending.slice(0, boundary);
        pending = pending.slice(boundary + 2);
        const eventName = frame.match(/^event:\s*(.+)$/m)?.[1];
        const dataLine = frame.match(/^data:\s*(.+)$/m)?.[1];
        if (eventName && dataLine) {
          const data = JSON.parse(dataLine);
          if (eventName === "sources") {
            sources = data;
            assistantMessage = addMessage("assistant", "", sources);
          } else if (eventName === "stage") {
            setThinkingStage(thinking, data);
            setServiceState(data.label || "Thinking", "thinking");
            setOrbState("thinking", data.detail || data.label || "thinking");
          } else if (eventName === "thought") {
            appendThought(thinking, data.text);
          } else if (eventName === "token") {
            if (!assistantMessage) assistantMessage = addMessage("assistant", "", sources);
            answer += data;
            assistantMessage.content.textContent = answer;
            scrollToBottom();
          } else if (eventName === "done") {
            completed = true;
            finishThinking(thinking);
            renderSources(assistantMessage?.article, data.sources || sources);
          } else if (eventName === "error") {
            throw new Error(data.error || "Ada's AI service is temporarily unavailable.");
          }
        }
        boundary = pending.indexOf("\n\n");
      }
      if (done) break;
    }
    if (!completed) {
      if (answer.trim()) {
        renderSources(assistantMessage?.article, sources);
      } else {
        throw new Error("Ada's response stream ended unexpectedly.");
      }
    }
    setServiceState("Ready", "ready");
    const learned = await syncOrbKnowledge();
    if (!learned) {
      setOrbState("speaking", "reply complete");
      window.setTimeout(() => {
        if (!sendButton.disabled) setOrbState("idle", "ready when you are");
      }, 1400);
    }
  } catch (error) {
    finishThinking(thinking, true);
    const messageText = error?.name === "AbortError"
      ? "Ada took too long to respond. Please try again."
      : (error.message || "Ada's AI service is temporarily unavailable. Please try again shortly.");
    addMessage("error", messageText);
    setServiceState("Unavailable", "error");
    setOrbState("error", "AI service unavailable");
  } finally {
    window.clearTimeout(timeoutId);
    sendButton.disabled = false;
    messageInput.disabled = false;
    messageInput.focus();
  }
});

messageInput.addEventListener("input", autoResizeTextarea);

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

document.querySelectorAll(".suggestion-chip[data-prompt]").forEach((chip) => {
  chip.addEventListener("click", () => {
    const prompt = chip.getAttribute("data-prompt") || "";
    messageInput.value = prompt;
    autoResizeTextarea();
    messageInput.focus();
    // Place cursor at end for prompts that expect completion
    if (prompt.endsWith(" ") || prompt.endsWith(": ")) {
      messageInput.setSelectionRange(prompt.length, prompt.length);
    }
  });
});

autoResizeTextarea();
loadHistory();
