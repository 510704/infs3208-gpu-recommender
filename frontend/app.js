const el = (id) => document.getElementById(id);

const ui = {
  game: el("game"),
  suggestList: el("suggest-list"),
  slider: el("fps-slider"),
  number: el("fps-number"),
  go: el("go"),
  error: el("error"),
  result: el("result"),
  rRequired: el("r-required"),
  rGpu: el("r-gpu"),
  rType: el("r-type"),
  rMarket: el("r-market"),
  rAvail: el("r-avail"),
  rGen: el("r-gen"),
  rAlt: el("r-alt"),
  rChart: el("r-chart"),
  rSvg: el("r-svg"),
  rScore: el("r-score"),
  allowPro: el("allow-pro"),
  allowLegacy: el("allow-legacy"),
  insightsGrid: el("insights-grid"),
  insightsEmpty: el("insights-empty"),
  lightbox: el("lightbox"),
  lightboxImg: el("lightbox-img"),
  fpsGame: el("fps-game"),
  fpsSuggestList: el("fps-suggest-list"),
  fpsGpu: el("fps-gpu"),
  gpuSuggestList: el("gpu-suggest-list"),
  fpsGo: el("fps-go"),
  fpsError: el("fps-error"),
  fpsResult: el("fps-result"),
  fpsLine: el("fps-line"),
  fpsValue: el("fps-value"),
  fpsFf: el("fps-ff"),
  fpsAvail: el("fps-avail"),
  fpsCurve: el("fps-curve"),
  fpsNote: el("fps-note"),
  rNone: el("r-none"),
  rGameLine: el("r-game-line"),
  badge: el("model-badge"),
  sStatus: el("s-status"),
  sGpus: el("s-gpus"),
  sEmulator: el("s-emulator"),
  refresh: el("refresh"),
};

function formatError(detail, statusText) {
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d === "string" ? d : d.msg)).join("; ");
  }
  return detail || statusText || "request failed";
}

async function refreshStatus() {
  try {
    const health = await fetch("/api/healthz").then((r) => r.json());
    const ready = health.catalog === "classified" && health.curve === "loaded";
    ui.sStatus.textContent = health.status === "ok" ? "ok" : health.status;
    ui.sGpus.textContent = `${health.gpus_loaded.toLocaleString()} GPUs (${health.catalog})`;
    ui.sEmulator.textContent = health.emulator || "none (production GCS)";
    ui.badge.textContent = ready ? "data: ready" : "data: incomplete";
    ui.badge.className = ready ? "badge badge-ok" : "badge badge-muted";
  } catch {
    ui.sStatus.textContent = "unreachable";
    ui.badge.textContent = "data: unreachable";
    ui.badge.className = "badge badge-bad";
  }
}

function clampFps(value) {
  return Math.min(360, Math.max(30, Math.round(Number(value) || 60)));
}

function syncFromSlider() {
  ui.number.value = ui.slider.value;
  markPreset();
}

function syncFromNumber() {
  const fps = clampFps(ui.number.value);
  ui.slider.value = fps;
  ui.number.value = fps;
  markPreset();
}

function markPreset() {
  document.querySelectorAll(".chip[data-fps]").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.fps === ui.slider.value);
  });
}

ui.slider.addEventListener("input", syncFromSlider);
ui.number.addEventListener("change", syncFromNumber);
document.querySelectorAll(".chip[data-fps]").forEach((chip) => {
  chip.addEventListener("click", () => {
    ui.slider.value = chip.dataset.fps;
    syncFromSlider();
  });
});

function makeSuggest(input, list, loadNames) {
  let names = null;
  const hide = () => {
    list.hidden = true;
    list.textContent = "";
  };
  input.addEventListener("focus", async () => {
    if (!names) names = await loadNames();
  }, { once: true });
  input.addEventListener("input", () => {
    if (!names || names.length === 0) return hide();
    const query = input.value.trim().toLowerCase();
    if (query.length < 2) return hide();
    const matches = names.filter((name) => name.toLowerCase().includes(query)).slice(0, 12);
    list.textContent = "";
    for (const name of matches) {
      const li = document.createElement("li");
      li.textContent = name;
      li.addEventListener("mousedown", (event) => {
        event.preventDefault();
        input.value = name;
        hide();
      });
      list.appendChild(li);
    }
    list.hidden = matches.length === 0;
  });
  input.addEventListener("blur", hide);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hide();
  });
}

let gameNames = null;
async function loadGameNames() {
  if (gameNames) return gameNames;
  try {
    gameNames = (await fetch("/api/games").then((r) => r.json())).games || [];
  } catch {
    gameNames = [];
  }
  return gameNames;
}

let gpuNames = null;
async function loadGpuNames() {
  if (gpuNames) return gpuNames;
  try {
    gpuNames = (await fetch("/api/gpus").then((r) => r.json())).gpus || [];
  } catch {
    gpuNames = [];
  }
  return gpuNames;
}

makeSuggest(ui.game, ui.suggestList, loadGameNames);
makeSuggest(ui.fpsGame, ui.fpsSuggestList, loadGameNames);
makeSuggest(ui.fpsGpu, ui.gpuSuggestList, loadGpuNames);

function setChip(node, text, show) {
  node.textContent = text;
  node.hidden = !show;
}

function segmentValue() {
  const checked = document.querySelector('input[name="segment"]:checked');
  return checked ? checked.value : "desktop";
}

function resolutionValue(name) {
  const checked = document.querySelector(`input[name="${name}"]:checked`);
  return checked ? checked.value : "1080p";
}

const curveCache = new Map();

function svgEl(name, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

async function renderCurveFor(data) {
  const resolution = data.resolution || "1080p";
  const key = `${(data.game || "").trim().toLowerCase()}|${resolution}`;
  let curve = curveCache.get(key);
  if (!curve) {
    const res = await fetch(
      `/api/curve?game=${encodeURIComponent(data.game || "")}&resolution=${encodeURIComponent(resolution)}`,
    );
    if (!res.ok) throw new Error("curve unavailable");
    curve = await res.json();
    if (curveCache.size > 40) curveCache.clear();
    curveCache.set(key, curve);
  }
  renderCurve(curve, data.target_fps, data.required_g3d, data.recommended_g3d);
}

function renderCurve(data, targetFps, required, recommendedScore) {
  const svg = ui.rSvg;
  const W = 640;
  const H = 250;
  const left = 56;
  const right = 16;
  const top = 14;
  const bottom = 34;
  const xMin = 30;
  const xMax = 360;
  const muted = "#8892a6";
  const values = data.points.map((p) => p.required).concat([required, recommendedScore || 0]);
  const yMax = Math.max(...values) * 1.08 || 1000;
  const yStep = yMax > 60000 ? 20000 : 10000;
  const sx = (fps) => left + ((fps - xMin) / (xMax - xMin)) * (W - left - right);
  const sy = (value) => H - bottom - (value / yMax) * (H - top - bottom);

  svg.textContent = "";
  ui.rChart.hidden = false;

  for (let value = 0; value <= yMax; value += yStep) {
    svg.appendChild(svgEl("line", {
      x1: left, y1: sy(value), x2: W - right, y2: sy(value),
      stroke: muted, "stroke-opacity": "0.18",
    }));
    const label = svgEl("text", { x: left - 8, y: sy(value) + 4, "text-anchor": "end", "font-size": "11", fill: muted });
    label.textContent = `${Math.round(value / 1000)}k`;
    svg.appendChild(label);
  }
  svg.appendChild(svgEl("line", { x1: left, y1: H - bottom, x2: W - right, y2: H - bottom, stroke: muted }));
  svg.appendChild(svgEl("line", { x1: left, y1: top, x2: left, y2: H - bottom, stroke: muted }));

  for (const fps of [30, 60, 120, 180, 240, 300, 360]) {
    svg.appendChild(svgEl("line", { x1: sx(fps), y1: H - bottom, x2: sx(fps), y2: H - bottom + 4, stroke: muted }));
    const label = svgEl("text", { x: sx(fps), y: H - bottom + 16, "text-anchor": "middle", "font-size": "11", fill: muted });
    label.textContent = fps;
    svg.appendChild(label);
  }
  const xLabel = svgEl("text", {
    x: (left + W - right) / 2, y: H - 4, "text-anchor": "middle", "font-size": "11", fill: muted,
  });
  xLabel.textContent = "Target FPS";
  svg.appendChild(xLabel);

  const path = data.points
    .map((p, i) => `${i ? "L" : "M"}${sx(p.fps).toFixed(1)},${sy(p.required).toFixed(1)}`)
    .join(" ");
  svg.appendChild(svgEl("path", { d: path, fill: "none", stroke: "#4f8cff", "stroke-width": "2" }));

  if (recommendedScore) {
    svg.appendChild(svgEl("line", {
      x1: left, y1: sy(recommendedScore), x2: W - right, y2: sy(recommendedScore),
      stroke: "#3ecf8e", "stroke-dasharray": "4 3", "stroke-width": "1.2",
    }));
    const label = svgEl("text", {
      x: W - right, y: sy(recommendedScore) - 4, "text-anchor": "end", "font-size": "10", fill: "#3ecf8e",
    });
    label.textContent = `pick: ${recommendedScore.toLocaleString()}`;
    svg.appendChild(label);
  }

  svg.appendChild(svgEl("line", {
    x1: sx(targetFps), y1: sy(required), x2: sx(targetFps), y2: H - bottom,
    stroke: "#f6c445", "stroke-dasharray": "3 3", "stroke-width": "1",
  }));
  const dot = svgEl("circle", { cx: sx(targetFps), cy: sy(required), r: 4, fill: "#f6c445" });
  const tip = svgEl("title", {});
  tip.textContent = `${targetFps} FPS -> ${Math.round(required).toLocaleString()}`;
  dot.appendChild(tip);
  svg.appendChild(dot);
  const note = svgEl("text", {
    x: Math.min(sx(targetFps) + 8, W - right - 80), y: sy(required) - 8, "font-size": "11", fill: "#f6c445",
  });
  note.textContent = `${targetFps} FPS → ${Math.round(required).toLocaleString()}`;
  svg.appendChild(note);

  if (data.source === "prior") {
    const badge = svgEl("text", { x: left + 6, y: top + 12, "font-size": "10", fill: muted });
    badge.textContent = "pooled estimate";
    svg.appendChild(badge);
  }

  svg.onclick = (event) => {
    const rect = svg.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * W;
    const fps = clampFps(xMin + ((x - left) / (W - left - right)) * (xMax - xMin));
    ui.slider.value = fps;
    syncFromSlider();
    recommend();
  };
}

async function recommend() {
  ui.error.hidden = true;
  ui.go.disabled = true;
  ui.go.textContent = "Working...";
  try {
    const fps = clampFps(ui.number.value);
    const res = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        game: ui.game.value.trim() || "Custom target",
        target_fps: fps,
        resolution: resolutionValue("resolution"),
        segment: segmentValue(),
        include_workstation: ui.allowPro.checked,
        new_only: !ui.allowLegacy.checked,
      }),
    });
    if (!res.ok) {
      let detail;
      try { detail = (await res.json()).detail; } catch { /* non-JSON body */ }
      throw new Error(formatError(detail, res.statusText));
    }
    const data = await res.json();
    renderResult(data);
  } catch (err) {
    ui.error.textContent = err.message;
    ui.error.hidden = false;
  } finally {
    ui.go.disabled = false;
    ui.go.textContent = "Find my GPU";
  }
}

async function renderResult(data) {
  ui.result.hidden = false;
  const resolution = data.resolution || "1080p";
  const scale = resolution === "1080p" ? "" : `, ${Number(data.resolution_factor).toFixed(2)}x`;
  ui.rGameLine.textContent = data.game
    ? `Required G3D for "${data.game}" at ${data.target_fps} FPS (${resolution}${scale})`
    : `Required G3D score at ${data.target_fps} FPS (${resolution}${scale})`;
  ui.rRequired.textContent = data.required_g3d.toLocaleString();

  if (data.recommended_gpu) {
    ui.rNone.hidden = true;
    ui.rGpu.textContent = data.recommended_gpu;
    ui.rScore.textContent = data.recommended_g3d.toLocaleString();
    const formFactor = { desktop: "Desktop", laptop: "Laptop", integrated: "Integrated (iGPU)" };
    setChip(ui.rType, formFactor[data.gpu_form_factor] || data.gpu_form_factor || "", Boolean(data.gpu_form_factor));
    setChip(ui.rMarket, "Workstation / Pro", data.gpu_market === "workstation");
    const availability = { legacy_secondhand: "Legacy (second-hand)", aging: "Aging stock", current: "Current" };
    setChip(
      ui.rAvail,
      availability[data.gpu_availability] || "",
      data.gpu_availability === "legacy_secondhand" || data.gpu_availability === "aging",
    );
    const generation = data.recommended_generation;
    setChip(
      ui.rGen,
      generation ? `${generation}${data.recommended_year ? ` (${data.recommended_year})` : ""}` : "",
      Boolean(generation),
    );
    if (data.legacy_fallback) {
      ui.rAlt.textContent = "No current-generation card meets this target; showing the lowest-spec older card.";
    } else if (data.cheaper_alternative) {
      const alt = data.cheaper_alternative;
      ui.rAlt.textContent = `Cheaper used option: ${alt.gpu}${alt.year ? ` (${alt.year})` : ""} at ${alt.g3d.toLocaleString()}.`;
    } else {
      ui.rAlt.textContent = "";
    }
    ui.rAlt.hidden = !ui.rAlt.textContent;
    renderCurveFor(data).catch(() => {
      ui.rChart.hidden = true;
      ui.rSvg.textContent = "";
    });
  } else {
    ui.rGpu.textContent = "—";
    ui.rScore.textContent = "—";
    ui.rType.hidden = true;
    ui.rMarket.hidden = true;
    ui.rAvail.hidden = true;
    ui.rGen.hidden = true;
    ui.rAlt.hidden = true;
    ui.rAlt.textContent = "";
    renderCurveFor(data).catch(() => {
      ui.rChart.hidden = true;
      ui.rSvg.textContent = "";
    });
    ui.rNone.hidden = false;
  }
}

async function estimateFps() {
  ui.fpsError.hidden = true;
  const game = ui.fpsGame.value.trim();
  const gpu = ui.fpsGpu.value.trim();
  if (!game || !gpu) {
    ui.fpsError.textContent = "Pick a game and a GPU first.";
    ui.fpsError.hidden = false;
    return;
  }
  ui.fpsGo.disabled = true;
  ui.fpsGo.textContent = "Working...";
  try {
    const res = await fetch("/api/fps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game, gpu, resolution: resolutionValue("fps-resolution") }),
    });
    if (!res.ok) {
      let detail;
      try { detail = (await res.json()).detail; } catch { /* non-JSON body */ }
      throw new Error(formatError(detail, res.statusText));
    }
    const data = await res.json();
    ui.fpsResult.hidden = false;
    const fpsResolution = data.resolution || "1080p";
    const fpsScale = fpsResolution === "1080p" ? "" : `, ${Number(data.resolution_factor).toFixed(2)}x`;
    ui.fpsLine.textContent = `${data.gpu} in "${data.game}" (${fpsResolution}${fpsScale})`;
    ui.fpsValue.textContent = `${data.predicted_fps} FPS`;
    const formFactor = { desktop: "Desktop", laptop: "Laptop", integrated: "Integrated (iGPU)" };
    setChip(ui.fpsFf, formFactor[data.gpu_form_factor] || data.gpu_form_factor || "", Boolean(data.gpu_form_factor));
    const availability = { legacy_secondhand: "Legacy (second-hand)", aging: "Aging stock", current: "Current" };
    setChip(
      ui.fpsAvail,
      availability[data.gpu_availability] || "",
      data.gpu_availability === "legacy_secondhand" || data.gpu_availability === "aging",
    );
    const r2 = data.fit_r2 === null || data.fit_r2 === undefined ? "" : ` \u00b7 fit r\u00b2=${data.fit_r2.toFixed(2)}`;
    setChip(ui.fpsCurve, `curve: ${data.curve_source}${r2}`, true);
    ui.fpsNote.textContent = "Outside the card range this game was measured on - treat as an extrapolation.";
    ui.fpsNote.hidden = !data.extrapolated;
  } catch (err) {
    ui.fpsError.textContent = err.message;
    ui.fpsError.hidden = false;
  } finally {
    ui.fpsGo.disabled = false;
    ui.fpsGo.textContent = "Estimate FPS";
  }
}

ui.fpsGo.addEventListener("click", estimateFps);
ui.go.addEventListener("click", recommend);
ui.refresh.addEventListener("click", refreshStatus);

let insightsLoaded = false;

function openLightbox(src) {
  ui.lightboxImg.src = src;
  ui.lightbox.hidden = false;
}

function closeLightbox() {
  ui.lightbox.hidden = true;
  ui.lightboxImg.removeAttribute("src");
}

async function loadInsights() {
  if (insightsLoaded) return;
  insightsLoaded = true;
  try {
    const data = await fetch("/api/figures").then((r) => r.json());
    ui.insightsGrid.textContent = "";
    if (!data.figures || data.figures.length === 0) {
      ui.insightsEmpty.hidden = false;
      return;
    }
    ui.insightsEmpty.hidden = true;
    for (const entry of data.figures) {
      const card = document.createElement("figure");
      card.className = "insight-card";
      card.dataset.span = String(Math.min(2, Math.max(1, Number(entry.span) || 1)));
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = `/api/figures/${entry.name}`;
      img.alt = entry.title || entry.name;
      img.addEventListener("click", () => openLightbox(img.src));
      const caption = document.createElement("figcaption");
      const title = document.createElement("strong");
      title.textContent = entry.title || entry.name;
      const text = document.createElement("span");
      text.textContent = entry.caption || "";
      caption.append(title, text);
      if (entry.explanation) {
        const explain = document.createElement("span");
        explain.className = "explain";
        explain.textContent = entry.explanation;
        caption.append(explain);
      }
      card.append(img, caption);
      ui.insightsGrid.append(card);
    }
  } catch {
    ui.insightsEmpty.hidden = false;
  }
}

ui.lightbox.addEventListener("click", closeLightbox);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeLightbox();
});

const tabs = Array.from(document.querySelectorAll(".tab"));

function showTab(name) {
  tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.hidden = panel.id !== `tab-${name}`;
  });
  if (name === "status") refreshStatus();
  if (name === "insights") loadInsights();
}

tabs.forEach((tab) => tab.addEventListener("click", () => showTab(tab.dataset.tab)));
showTab("find");

refreshStatus();
