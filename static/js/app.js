/* ALBATROSS frontend */
"use strict";

const $ = (sel) => document.querySelector(sel);

const State = {
  configured: false,
  fields: [],
  selected: null,        // field object
  scenes: [],            // scenes of selected field
  fieldLayers: {},       // field_id -> leaflet layer
  overlay: null,         // active L.imageOverlay
  overlayKey: null,      // `${sceneId}:${kind}`
  scanning: false,
};

let MAP;

/* ------------------------------------------------------------------ api */

async function api(path, options = {}) {
  const opts = { ...options };
  if (opts.json !== undefined) {
    opts.method = opts.method || "POST";
    opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const resp = await fetch(path, opts);
  let body = null;
  try { body = await resp.json(); } catch (_) { /* non-JSON */ }
  if (!resp.ok) {
    const msg = body && body.detail ? body.detail : `Request failed (${resp.status})`;
    throw new Error(msg);
  }
  return body;
}

/* ---------------------------------------------------------------- toasts */

function toast(message, type = "ok", ms = 4200) {
  const el = document.createElement("div");
  el.className = "toast" + (type === "err" ? " toast-err" : type === "warn" ? " toast-warn" : "");
  el.textContent = message;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 450); }, ms);
}

/* ------------------------------------------------------------ formatting */

const MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
function fmtDate(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d} ${MONTHS[+m - 1]} ${y}`;
}
function fmtNum(v, digits = 2) {
  return (v === null || v === undefined) ? "—" : Number(v).toFixed(digits);
}

/* NDVI color ramp — mirrors the backend evalscript */
const RAMP_POS = [-0.5, 0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9];
const RAMP_COL = [
  [64,78,90],[173,129,96],[214,178,102],[227,223,112],
  [158,199,84],[95,168,62],[42,126,45],[14,84,34],
];
function ndviColor(v) {
  if (v === null || v === undefined) return "#5c5c62";
  if (v <= RAMP_POS[0]) return `rgb(${RAMP_COL[0]})`;
  for (let i = 1; i < RAMP_POS.length; i++) {
    if (v <= RAMP_POS[i]) {
      const t = (v - RAMP_POS[i-1]) / (RAMP_POS[i] - RAMP_POS[i-1]);
      const c0 = RAMP_COL[i-1], c1 = RAMP_COL[i];
      const c = c0.map((a, k) => Math.round(a + (c1[k] - a) * t));
      return `rgb(${c})`;
    }
  }
  return `rgb(${RAMP_COL[RAMP_COL.length-1]})`;
}

/* ------------------------------------------------------------------- map */

function geoBounds(geometry) {
  let minLat = 90, maxLat = -90, minLng = 180, maxLng = -180;
  (function walk(coords) {
    if (typeof coords[0] === "number") {
      minLng = Math.min(minLng, coords[0]); maxLng = Math.max(maxLng, coords[0]);
      minLat = Math.min(minLat, coords[1]); maxLat = Math.max(maxLat, coords[1]);
    } else {
      coords.forEach(walk);
    }
  })(geometry.coordinates);
  return L.latLngBounds([minLat, minLng], [maxLat, maxLng]);
}

function initMap() {
  MAP = L.map("map", { zoomControl: true, attributionControl: true })
    .setView([53.5, -110], 4);
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "Imagery © Esri — basemap · Data © Copernicus Sentinel-2" }
  ).addTo(MAP);
}

function fieldStyle(selected) {
  return {
    color: selected ? "#ccff00" : "#e8e8ee",
    weight: selected ? 2.4 : 1.4,
    fillColor: selected ? "#ccff00" : "#e8e8ee",
    fillOpacity: selected ? 0.10 : 0.04,
    dashArray: selected ? null : "5 4",
  };
}

function renderFieldLayers() {
  Object.values(State.fieldLayers).forEach((layer) => MAP.removeLayer(layer));
  State.fieldLayers = {};
  State.fields.forEach((field) => {
    const layer = L.geoJSON(field.geometry, {
      style: fieldStyle(State.selected && State.selected.id === field.id),
    });
    layer.on("click", () => selectField(field.id));
    layer.addTo(MAP);
    State.fieldLayers[field.id] = layer;
  });
}

function fitAllFields() {
  const ids = Object.keys(State.fieldLayers);
  if (!ids.length) return;
  let bounds = null;
  ids.forEach((id) => {
    const b = State.fieldLayers[id].getBounds();
    bounds = bounds ? bounds.extend(b) : L.latLngBounds(b.getSouthWest(), b.getNorthEast());
  });
  MAP.fitBounds(bounds.pad(0.25));
}

/* --------------------------------------------------------------- overlays */

function clearOverlay() {
  if (State.overlay) { MAP.removeLayer(State.overlay); State.overlay = null; }
  State.overlayKey = null;
  document.querySelectorAll(".seg .btn").forEach((b) => b.classList.remove("active"));
}

function showOverlay(scene, kind) {
  const key = `${scene.id}:${kind}`;
  if (State.overlayKey === key) { clearOverlay(); return; }
  clearOverlay();
  if (kind === "off" || !State.selected) return;
  const bounds = geoBounds(State.selected.geometry);
  State.overlay = L.imageOverlay(`/api/scenes/${scene.id}/files/${kind}`, bounds, {
    opacity: (+$("#overlayOpacity").value) / 100,
    className: "overlay-pixelated",
    interactive: false,
  }).addTo(MAP);
  State.overlayKey = key;
  const btn = document.querySelector(`.seg .btn[data-ov="${key}"]`);
  if (btn) btn.classList.add("active");
  MAP.fitBounds(bounds.pad(0.2));
}

/* ----------------------------------------------------------------- fields */

async function loadFields({ fit = false } = {}) {
  const body = await api("/api/fields");
  State.fields = body.fields;
  renderFieldList();
  renderFieldLayers();
  $("#mapEmpty").classList.toggle("hidden", State.fields.length > 0);
  if (fit) fitAllFields();
}

function renderFieldList() {
  const list = $("#fieldList");
  list.innerHTML = "";
  $("#fieldCount").textContent = State.fields.length ? String(State.fields.length).padStart(2, "0") : "";
  if (!State.fields.length) {
    list.innerHTML = `<div class="side-empty">no fields tracked yet<br>&mdash; upload boundaries above &mdash;</div>`;
    return;
  }
  State.fields.forEach((field, i) => {
    const card = document.createElement("div");
    card.className = "field-card" + (State.selected && State.selected.id === field.id ? " selected" : "");
    card.style.animationDelay = `${i * 40}ms`;
    card.innerHTML = `
      <div class="fc-row1">
        <span class="fc-name">${escapeHtml(field.name)}</span>
        <span class="fc-area">${fmtNum(field.area_ha, 1)} ha</span>
      </div>
      <div class="fc-row2">
        <span>${field.latest_date ? "LAST PASS " + fmtDate(field.latest_date) : "NO PASSES YET"}</span>
        ${field.new_count > 0
          ? `<span class="badge-new">${field.new_count} NEW</span>`
          : (field.latest_ndvi !== null && field.latest_ndvi !== undefined
              ? `<span class="fc-ndvi">NDVI ${fmtNum(field.latest_ndvi)}</span>` : "")}
      </div>`;
    card.addEventListener("click", () => selectField(field.id));
    list.appendChild(card);
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function selectField(fieldId) {
  const field = State.fields.find((f) => f.id === fieldId);
  if (!field) return;
  State.selected = field;
  clearOverlay();
  renderFieldList();
  renderFieldLayers();

  $("#passPanel").classList.remove("hidden");
  $("#lookbackSelect").value = "";
  MAP.invalidateSize();
  MAP.fitBounds(geoBounds(field.geometry).pad(0.25));

  $("#panelFieldName").textContent = field.name;
  $("#panelFieldMeta").textContent =
    `${fmtNum(field.area_ha, 1)} HA · ${field.scene_count || 0} PASSES ON RECORD`;

  await refreshScenes();
  await refreshChart();

  if (field.new_count > 0) {
    api(`/api/fields/${fieldId}/seen`, { method: "POST" }).then(() => {
      field.new_count = 0;
      renderFieldList();
    }).catch(() => {});
  }
}

function closePanel() {
  State.selected = null;
  clearOverlay();
  $("#passPanel").classList.add("hidden");
  renderFieldList();
  renderFieldLayers();
  MAP.invalidateSize();
}

async function deleteSelectedField() {
  if (!State.selected) return;
  const name = State.selected.name;
  if (!confirm(`Remove field "${name}" and all downloaded imagery?`)) return;
  await api(`/api/fields/${State.selected.id}`, { method: "DELETE" });
  toast(`FIELD REMOVED // ${name.toUpperCase()}`, "warn");
  closePanel();
  await loadFields({ fit: State.fields.length > 1 });
}

/* ----------------------------------------------------------------- scenes */

async function refreshScenes() {
  if (!State.selected) return;
  const body = await api(`/api/fields/${State.selected.id}/scenes`);
  State.scenes = body.scenes;
  renderScenes();
}

function renderScenes() {
  const list = $("#sceneList");
  list.innerHTML = "";
  if (!State.scenes.length) {
    list.innerHTML = `<div class="scene-empty">no acquisitions on record<br>&mdash; hit SCAN to query copernicus &mdash;</div>`;
    return;
  }
  State.scenes.forEach((scene) => list.appendChild(sceneCard(scene)));
}

function sceneCard(scene) {
  const card = document.createElement("div");
  card.className = "scene-card" + (scene.status === "new" ? " is-new" : "");
  card.dataset.sceneId = scene.id;

  const cloud = scene.cloud_cover === null || scene.cloud_cover === undefined
    ? null : Math.round(scene.cloud_cover);
  const processed = scene.status === "processed";
  const excluded = !!scene.trend_excluded;
  if (processed && excluded) card.classList.add("sc-excluded");

  let chips = "";
  if (scene.status === "new") chips += `<span class="chip chip-new">NEW</span>`;
  if (processed && excluded) chips += `<span class="chip chip-off">OFF TREND</span>`;
  if (processed) chips += `<span class="chip chip-ok">ACQUIRED</span>`;
  else chips += `<span class="chip">CATALOG</span>`;

  let html = `
    <div class="sc-row1">
      <span class="sc-date">${fmtDate(scene.date)}</span>
      <span class="sc-chips">${chips}</span>
    </div>
    <div class="sc-cloud">
      <span>CLOUD</span>
      <span class="cloud-meter"><i style="width:${cloud === null ? 0 : cloud}%"></i></span>
      <span>${cloud === null ? "—" : cloud + "%"}</span>
    </div>`;

  if (!processed) {
    html += `
      <div class="sc-actions">
        <button class="btn btn-accent sc-process">&#9678; ACQUIRE &amp; ANALYZE</button>
      </div>`;
  } else {
    const meanColor = ndviColor(scene.ndvi_mean);
    html += `
      <div class="sc-result">
        <img class="sc-thumb" src="/api/scenes/${scene.id}/files/ndvi" alt="NDVI thumbnail" loading="lazy">
        <div class="sc-stats">
          <div class="sc-ndvi-label">MEAN NDVI</div>
          <div class="sc-ndvi-big" style="color:${meanColor}">${fmtNum(scene.ndvi_mean)}</div>
          <div class="sc-minmax">
            min <b>${fmtNum(scene.ndvi_min)}</b> · max <b>${fmtNum(scene.ndvi_max)}</b> · σ <b>${fmtNum(scene.ndvi_std)}</b><br>
            clear <b>${fmtNum(scene.clear_pct, 0)}%</b> · cloud in field <b>${fmtNum(scene.cloud_pct, 0)}%</b>
          </div>
        </div>
      </div>
      <div class="sc-trend">
        <button class="btn btn-tiny sc-trend-btn ${excluded ? "" : "active"}"
                title="${excluded ? "This pass is excluded from the NDVI trend graph — click to add it back" : "This pass counts toward the NDVI trend graph — click to exclude it (e.g. too cloudy)"}">
          ${excluded ? "&#9675; ADD TO TREND" : "&#10003; IN NDVI TREND"}
        </button>
      </div>
      <div class="sc-footer">
        <span class="sc-footer-label">OVERLAY</span>
        <div class="seg">
          <button class="btn btn-tiny" data-ov="${scene.id}:ndvi">NDVI</button>
          <button class="btn btn-tiny" data-ov="${scene.id}:truecolor">RGB</button>
        </div>
      </div>
      <div class="sc-downloads">
        <span class="dl-label">&#10515; DOWNLOAD</span>
        <a class="dl-pill" href="/api/scenes/${scene.id}/files/ndvi_raw?download=1" title="NDVI as float32 GeoTIFF">NDVI<em>.tif</em></a>
        <a class="dl-pill" href="/api/scenes/${scene.id}/files/ndvi?download=1" title="NDVI color map PNG">NDVI<em>.png</em></a>
        <a class="dl-pill" href="/api/scenes/${scene.id}/files/truecolor?download=1" title="True-color PNG">RGB<em>.png</em></a>
        <a class="dl-pill" href="/api/scenes/${scene.id}/files/scl?download=1" title="Scene classification TIFF">SCL<em>.tif</em></a>
      </div>`;
  }

  card.innerHTML = html;

  const processBtn = card.querySelector(".sc-process");
  if (processBtn) processBtn.addEventListener("click", () => processScene(scene, processBtn));

  card.querySelectorAll("[data-ov]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const kind = btn.dataset.ov.split(":")[1];
      showOverlay(scene, kind);
    });
  });
  const thumb = card.querySelector(".sc-thumb");
  if (thumb) thumb.addEventListener("click", () => showOverlay(scene, "ndvi"));

  const trendBtn = card.querySelector(".sc-trend-btn");
  if (trendBtn) trendBtn.addEventListener("click", () => toggleTrend(scene, trendBtn));

  return card;
}

async function toggleTrend(scene, btn) {
  const nextExcluded = !scene.trend_excluded;
  btn.disabled = true;
  try {
    const body = await api(`/api/scenes/${scene.id}/trend?excluded=${nextExcluded}`, { method: "POST" });
    const updated = body.scene;
    const idx = State.scenes.findIndex((s) => s.id === updated.id);
    if (idx >= 0) State.scenes[idx] = updated;
    renderScenes();
    await refreshChart();
    await loadFields();
    toast(nextExcluded
      ? `${fmtDate(updated.date)} REMOVED FROM TREND`
      : `${fmtDate(updated.date)} ADDED TO TREND`, nextExcluded ? "warn" : "ok");
  } catch (err) {
    toast(err.message, "err", 7000);
    btn.disabled = false;
  }
}

async function processScene(scene, btn) {
  btn.disabled = true;
  btn.innerHTML = `<span class="spin">&#10227;</span> DOWNLINKING…`;
  try {
    const body = await api(`/api/scenes/${scene.id}/process`, { method: "POST" });
    const updated = body.scene;
    const idx = State.scenes.findIndex((s) => s.id === updated.id);
    if (idx >= 0) State.scenes[idx] = updated;
    renderScenes();
    await refreshChart();
    await loadFields();
    toast(`ANALYSIS COMPLETE // ${fmtDate(updated.date)} · MEAN NDVI ${fmtNum(updated.ndvi_mean)}`);
    showOverlay(updated, "ndvi");
  } catch (err) {
    toast(err.message, "err", 7000);
    btn.disabled = false;
    btn.innerHTML = `&#9678; ACQUIRE &amp; ANALYZE`;
  }
}

/* --------------------------------------------------------------- scanning */

async function scanField() {
  if (!State.selected) return;
  const btn = $("#checkFieldBtn");
  const days = $("#lookbackSelect").value;
  const label = $("#lookbackSelect").selectedOptions[0].textContent;
  const url = `/api/fields/${State.selected.id}/check${days ? `?days=${days}` : ""}`;
  btn.disabled = true;
  const original = btn.innerHTML;
  if (days) btn.innerHTML = `<span class="spin">&#10227;</span> SCANNING…`;
  try {
    const body = await api(url, { method: "POST" });
    State.scenes = body.scenes;
    renderScenes();
    const scope = days ? ` (${label})` : "";
    toast(body.new > 0
      ? `${body.new} NEW PASS${body.new > 1 ? "ES" : ""}${scope} // ${State.selected.name.toUpperCase()}`
      : `NO NEW PASSES${scope} // ${State.selected.name.toUpperCase()}`, body.new > 0 ? "ok" : "warn");
    await loadFields();
  } catch (err) {
    toast(err.message, "err", 7000);
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

async function scanAll({ silent = false } = {}) {
  if (State.scanning) return;
  if (!State.configured) {
    if (!silent) { toast("NO UPLINK — configure Copernicus credentials first", "warn"); openSettings(); }
    return;
  }
  if (!State.fields.length) {
    if (!silent) toast("No fields to scan — upload a boundary file first", "warn");
    return;
  }
  State.scanning = true;
  const btn = $("#scanBtn");
  btn.disabled = true;
  btn.innerHTML = `<span class="spin">&#10227;</span> SCANNING…`;
  try {
    const body = await api("/api/check-all", { method: "POST" });
    await loadFields();
    if (State.selected) await refreshScenes();
    if (body.total_new > 0) {
      const parts = body.results.filter((r) => r.new > 0).length;
      toast(`${body.total_new} NEW PASS${body.total_new > 1 ? "ES" : ""} ACROSS ${parts} FIELD${parts > 1 ? "S" : ""}`);
    } else if (!silent) {
      toast("SWEEP COMPLETE // NO NEW PASSES", "warn");
    }
  } catch (err) {
    toast(err.message, "err", 7000);
  } finally {
    State.scanning = false;
    btn.disabled = false;
    btn.innerHTML = `<span class="btn-ic">&#10227;</span> SCAN FOR PASSES`;
  }
}

/* ------------------------------------------------------------------ chart */

async function refreshChart() {
  if (!State.selected) return;
  const body = await api(`/api/fields/${State.selected.id}/timeseries`);
  drawChart(body.points || []);
}

function drawChart(points) {
  const svg = $("#tsChart");
  svg.innerHTML = "";
  const empty = $("#chartEmpty");
  $("#chartLatest").textContent = points.length
    ? `LATEST ${fmtNum(points[points.length - 1].ndvi_mean)}` : "";
  if (points.length === 0) { empty.classList.remove("hidden"); return; }
  empty.classList.add("hidden");

  const W = svg.clientWidth || 320, H = 130;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const padL = 30, padR = 10, padT = 10, padB = 18;
  const iw = W - padL - padR, ih = H - padT - padB;

  const ys = points.map((p) => p.ndvi_mean);
  const yMin = Math.min(0, ...ys), yMax = Math.max(1, ...ys);
  const xAt = (i) => points.length === 1 ? padL + iw / 2 : padL + (i / (points.length - 1)) * iw;
  const yAt = (v) => padT + (1 - (v - yMin) / (yMax - yMin)) * ih;

  const ns = "http://www.w3.org/2000/svg";
  const make = (tag, attrs) => {
    const el = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    svg.appendChild(el);
    return el;
  };

  // gradient defs
  const defs = document.createElementNS(ns, "defs");
  defs.innerHTML = `
    <linearGradient id="areaG" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ccff00" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="#ccff00" stop-opacity="0"/>
    </linearGradient>`;
  svg.appendChild(defs);

  // grid lines + y labels
  [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
    if (v < yMin || v > yMax) return;
    const y = yAt(v);
    make("line", { x1: padL, y1: y, x2: W - padR, y2: y, stroke: "#232326", "stroke-width": 1 });
    const label = make("text", { x: padL - 5, y: y + 3, "text-anchor": "end", fill: "#5c5c62",
      "font-size": 8, "font-family": "Share Tech Mono" });
    label.textContent = v.toFixed(2).replace(/0$/, "");
  });

  const lineD = points.map((p, i) => `${i ? "L" : "M"}${xAt(i).toFixed(1)},${yAt(p.ndvi_mean).toFixed(1)}`).join(" ");
  if (points.length > 1) {
    const areaD = `${lineD} L${xAt(points.length - 1).toFixed(1)},${yAt(yMin)} L${xAt(0).toFixed(1)},${yAt(yMin)} Z`;
    make("path", { d: areaD, fill: "url(#areaG)", stroke: "none" });
    make("path", { d: lineD, fill: "none", stroke: "#ccff00", "stroke-width": 1.6,
      style: "filter: drop-shadow(0 0 4px rgba(204,255,0,0.5))" });
  }

  points.forEach((p, i) => {
    make("circle", { cx: xAt(i), cy: yAt(p.ndvi_mean), r: 3, fill: "#040404",
      stroke: "#e8e8ee", "stroke-width": 1.5, style: "cursor:pointer" });
  });

  // x labels: first and last
  const xl = make("text", { x: padL, y: H - 5, fill: "#5c5c62", "font-size": 8, "font-family": "Share Tech Mono" });
  xl.textContent = fmtDate(points[0].date);
  if (points.length > 1) {
    const xr = make("text", { x: W - padR, y: H - 5, "text-anchor": "end", fill: "#5c5c62",
      "font-size": 8, "font-family": "Share Tech Mono" });
    xr.textContent = fmtDate(points[points.length - 1].date);
  }

  // hover tooltip
  const tip = $("#chartTip");
  svg.onmousemove = (ev) => {
    const rect = svg.getBoundingClientRect();
    const mx = ((ev.clientX - rect.left) / rect.width) * W;
    let best = 0, bestDist = Infinity;
    points.forEach((p, i) => {
      const d = Math.abs(xAt(i) - mx);
      if (d < bestDist) { bestDist = d; best = i; }
    });
    const p = points[best];
    tip.innerHTML = `${fmtDate(p.date)} · NDVI <b>${fmtNum(p.ndvi_mean)}</b>`;
    tip.style.left = `${(xAt(best) / W) * rect.width}px`;
    tip.style.top = `${(yAt(p.ndvi_mean) / H) * rect.height}px`;
    tip.classList.remove("hidden");
  };
  svg.onmouseleave = () => tip.classList.add("hidden");
}

/* --------------------------------------------------------------- settings */

function setUplink(configured) {
  State.configured = configured;
  const pill = $("#uplink");
  pill.classList.toggle("uplink-on", configured);
  pill.classList.toggle("uplink-off", !configured);
  $("#uplinkText").textContent = configured ? "UPLINK OK" : "NO UPLINK";
}

async function loadSettings() {
  try {
    const s = await api("/api/settings");
    setUplink(s.configured);
    $("#inClientId").value = s.client_id || "";
    $("#inClientSecret").placeholder = s.has_client_secret ? "•••••••• (stored)" : "";
    return s;
  } catch (err) {
    setUplink(false);
    return { configured: false };
  }
}

function openSettings() {
  $("#settingsStatus").classList.add("hidden");
  $("#settingsModal").showModal();
}

async function saveSettings() {
  const btn = $("#saveSettingsBtn");
  const status = $("#settingsStatus");
  btn.disabled = true;
  status.classList.add("hidden");
  try {
    const body = await api("/api/settings", {
      json: {
        client_id: $("#inClientId").value,
        client_secret: $("#inClientSecret").value,
        access_token: $("#inToken").value,
      },
    });
    status.textContent = body.message;
    status.className = "settings-status " + (body.ok ? "ok" : "err");
    status.classList.remove("hidden");
    setUplink(body.configured && body.ok);
    if (body.ok) {
      setTimeout(() => { $("#settingsModal").close(); }, 900);
      toast("UPLINK ESTABLISHED // COPERNICUS DATA SPACE");
      scanAll({ silent: true });
    }
  } catch (err) {
    status.textContent = err.message;
    status.className = "settings-status err";
    status.classList.remove("hidden");
  } finally {
    btn.disabled = false;
  }
}

async function clearCredentials() {
  await api("/api/settings", { json: { clear: true } });
  $("#inClientId").value = "";
  $("#inClientSecret").value = "";
  $("#inClientSecret").placeholder = "";
  $("#inToken").value = "";
  setUplink(false);
  toast("CREDENTIALS CLEARED", "warn");
}

/* ----------------------------------------------------------------- upload */

async function uploadFiles(fileList) {
  if (!fileList || !fileList.length) return;
  const form = new FormData();
  [...fileList].forEach((f) => form.append("files", f));
  const dz = $("#dropzone");
  dz.classList.add("dragover");
  try {
    const body = await api("/api/fields/upload", { method: "POST", body: form });
    const n = body.fields.length;
    toast(`${n} FIELD${n > 1 ? "S" : ""} REGISTERED`);
    await loadFields({ fit: true });
    if (State.configured) scanAll({ silent: true });
    else toast("Configure your Copernicus uplink to scan for imagery", "warn", 6000);
  } catch (err) {
    toast(err.message, "err", 8000);
  } finally {
    dz.classList.remove("dragover");
    $("#fileInput").value = "";
  }
}

/* ------------------------------------------------------------------- init */

function bindUI() {
  const dz = $("#dropzone");
  dz.addEventListener("click", () => $("#fileInput").click());
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") $("#fileInput").click(); });
  $("#fileInput").addEventListener("change", (e) => uploadFiles(e.target.files));

  ["dragenter", "dragover"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); if (ev === "dragleave") dz.classList.remove("dragover"); }));
  dz.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));

  // also accept drops anywhere on the map
  const mapEl = $("#mapwrap");
  ["dragenter", "dragover"].forEach((ev) => mapEl.addEventListener(ev, (e) => e.preventDefault()));
  mapEl.addEventListener("drop", (e) => { e.preventDefault(); uploadFiles(e.dataTransfer.files); });

  $("#settingsBtn").addEventListener("click", openSettings);
  $("#uplink").addEventListener("click", openSettings);
  $("#saveSettingsBtn").addEventListener("click", saveSettings);
  $("#clearCredsBtn").addEventListener("click", clearCredentials);
  $("#scanBtn").addEventListener("click", () => scanAll());
  $("#checkFieldBtn").addEventListener("click", scanField);
  $("#closePanelBtn").addEventListener("click", closePanel);
  $("#deleteFieldBtn").addEventListener("click", deleteSelectedField);

  $("#overlayOpacity").addEventListener("input", (e) => {
    if (State.overlay) State.overlay.setOpacity((+e.target.value) / 100);
  });
}

async function checkForUpdate() {
  // fire-and-forget: never let a version check slow down or break startup
  try {
    const info = await api("/api/update-check");
    if (info && info.update_available && info.latest) {
      const chip = $("#updateChip");
      $("#updateChipText").textContent = `UPDATE → v${info.latest}`;
      chip.href = info.url;
      chip.title = `Albatross v${info.latest} is available (you have v${info.current}). Click to download.`;
      chip.classList.remove("hidden");
      toast(`UPDATE AVAILABLE // v${info.latest} — you have v${info.current}. Click the pink UPDATE tag to get it.`, "warn", 9000);
    }
  } catch (_) { /* offline or rate-limited — silent */ }
}

async function init() {
  initMap();
  bindUI();
  const settings = await loadSettings();
  await loadFields({ fit: true });
  if (!settings.configured) {
    openSettings();
  } else {
    // auto-check for new imagery on every open/refresh
    scanAll({ silent: true });
  }
  checkForUpdate();
}

document.addEventListener("DOMContentLoaded", init);
