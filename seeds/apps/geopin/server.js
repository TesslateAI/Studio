'use strict';
// GeoPin — map pinning and geometry editor
// REST API: GET/POST/PUT/DELETE /api/features
// Platform actions: POST /actions/{add_feature,list_features,update_feature,delete_feature}
// UI: GET / (Leaflet + OpenStreetMap, native click-based drawing — no Leaflet.Draw plugin)

const http = require('http');
const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');

const PORT = parseInt(process.env.PORT || '3000', 10);
const DATA_DIR = process.env.DATA_DIR || '/app/data';
const DATA_FILE = path.join(DATA_DIR, 'features.json');

try { fs.mkdirSync(DATA_DIR, { recursive: true }); } catch {}

// ── Data helpers ────────────────────────────────────────────────────────

function loadCollection() {
  try {
    return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
  } catch {
    return { type: 'FeatureCollection', features: [] };
  }
}

function saveCollection(fc) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(fc, null, 2), 'utf8');
}

// ── HTTP helpers ────────────────────────────────────────────────────────

function readBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', c => { raw += c; });
    req.on('end', () => {
      if (!raw) return resolve({});
      try { resolve(JSON.parse(raw)); } catch (e) { reject(e); }
    });
    req.on('error', reject);
  });
}

function sendJson(res, status, body) {
  const b = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(b),
  });
  res.end(b);
}

function sendHtml(res, html) {
  const b = Buffer.from(html, 'utf8');
  res.writeHead(200, {
    'content-type': 'text/html; charset=utf-8',
    'content-length': b.length,
  });
  res.end(b);
}

// ── Validation ──────────────────────────────────────────────────────────

function validateGeometry(geometry) {
  if (!geometry || typeof geometry !== 'object') return 'geometry is required';
  if (!['Point', 'LineString', 'Polygon'].includes(geometry.type)) {
    return 'geometry.type must be Point, LineString, or Polygon';
  }
  if (!Array.isArray(geometry.coordinates) || geometry.coordinates.length === 0) {
    return 'geometry.coordinates must be a non-empty array';
  }
  if (geometry.type === 'Point') {
    if (geometry.coordinates.length < 2) return 'Point coordinates must be [lng, lat]';
    const [lng, lat] = geometry.coordinates;
    if (typeof lng !== 'number' || typeof lat !== 'number') return 'coordinates must be numbers';
    if (lng < -180 || lng > 180) return 'longitude must be between -180 and 180';
    if (lat < -90 || lat > 90) return 'latitude must be between -90 and 90';
  }
  if (geometry.type === 'LineString' && geometry.coordinates.length < 2) {
    return 'LineString requires at least 2 coordinate pairs';
  }
  if (geometry.type === 'Polygon') {
    const ring = geometry.coordinates[0];
    if (!Array.isArray(ring) || ring.length < 4) {
      return 'Polygon outer ring must have at least 4 positions (first === last)';
    }
  }
  return null;
}

function validateColor(color) {
  if (color === undefined) return null;
  if (typeof color !== 'string' || !/^#[0-9a-fA-F]{3,6}$/.test(color)) {
    return 'color must be a hex string like #3b82f6';
  }
  return null;
}

// ── CRUD logic ──────────────────────────────────────────────────────────

function doCreate(body) {
  const { label, geometry, color = '#3b82f6', description = '' } = body;
  if (!label || typeof label !== 'string' || !label.trim()) {
    return { status: 400, body: { error: 'label is required and must be a non-empty string' } };
  }
  if (label.trim().length > 120) {
    return { status: 400, body: { error: 'label must be 120 characters or fewer' } };
  }
  const geoErr = validateGeometry(geometry);
  if (geoErr) return { status: 400, body: { error: geoErr } };
  const colorErr = validateColor(color);
  if (colorErr) return { status: 400, body: { error: colorErr } };

  const fc = loadCollection();
  const id = randomUUID();
  const now = new Date().toISOString();
  const feature = {
    type: 'Feature',
    id,
    geometry,
    properties: {
      id,
      label: label.trim(),
      color,
      description: (description || '').slice(0, 500),
      created_at: now,
      updated_at: now,
    },
  };
  fc.features.push(feature);
  saveCollection(fc);
  return { status: 201, body: { feature, feature_id: id } };
}

function doList(query = {}) {
  const fc = loadCollection();
  let features = fc.features;
  if (query.geometry_type) {
    features = features.filter(f => f.geometry.type === query.geometry_type);
  }
  if (query.label_contains) {
    const q = query.label_contains.toLowerCase();
    features = features.filter(f => f.properties.label.toLowerCase().includes(q));
  }
  return { status: 200, body: { feature_collection: { type: 'FeatureCollection', features }, count: features.length } };
}

function doUpdate(id, body) {
  const fc = loadCollection();
  const idx = fc.features.findIndex(f => f.properties.id === id);
  if (idx === -1) return { status: 404, body: { error: 'Feature not found', feature_id: id } };

  const feature = fc.features[idx];
  if (body.label !== undefined) {
    if (typeof body.label !== 'string' || !body.label.trim()) {
      return { status: 400, body: { error: 'label must be a non-empty string' } };
    }
    feature.properties.label = body.label.trim().slice(0, 120);
  }
  if (body.color !== undefined) {
    const colorErr = validateColor(body.color);
    if (colorErr) return { status: 400, body: { error: colorErr } };
    feature.properties.color = body.color;
  }
  if (body.description !== undefined) {
    feature.properties.description = String(body.description).slice(0, 500);
  }
  if (body.geometry !== undefined) {
    const geoErr = validateGeometry(body.geometry);
    if (geoErr) return { status: 400, body: { error: geoErr } };
    feature.geometry = body.geometry;
  }
  feature.properties.updated_at = new Date().toISOString();
  saveCollection(fc);
  return { status: 200, body: { feature } };
}

function doDelete(id) {
  const fc = loadCollection();
  const before = fc.features.length;
  fc.features = fc.features.filter(f => f.properties.id !== id);
  if (fc.features.length === before) {
    return { status: 404, body: { error: 'Feature not found', feature_id: id } };
  }
  saveCollection(fc);
  return { status: 200, body: { deleted: true, feature_id: id } };
}

// ── UI HTML ─────────────────────────────────────────────────────────────

function renderUI() {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>GeoPin — Map Editor</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --w-sidebar: 300px;
      --accent: #2563eb;
      --accent-dim: #eff6ff;
      --bg: #f3f4f6;
      --surface: #ffffff;
      --border: #e5e7eb;
      --text: #111827;
      --muted: #6b7280;
      --danger: #ef4444;
      --danger-dim: #fee2e2;
      --r: 7px;
      --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    html, body { height: 100%; font-family: var(--font); color: var(--text); background: var(--bg); }
    .layout { display: flex; height: 100vh; overflow: hidden; }

    /* ── Sidebar ── */
    .sidebar {
      width: var(--w-sidebar);
      min-width: var(--w-sidebar);
      background: var(--surface);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .sb-head {
      padding: 14px 16px 12px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }
    .sb-head h1 { font-size: 17px; font-weight: 700; letter-spacing: -0.2px; display: flex; align-items: center; gap: 7px; }
    .sb-head p { font-size: 11px; color: var(--muted); margin-top: 2px; }

    .sb-tools {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }
    .tool-row { display: flex; gap: 6px; }
    .tool-btn {
      flex: 1; padding: 7px 4px;
      font-size: 11px; font-weight: 500;
      border: 1.5px solid var(--border);
      border-radius: var(--r);
      background: var(--surface);
      cursor: pointer;
      display: flex; align-items: center; justify-content: center; gap: 4px;
      color: var(--text);
      transition: border-color .12s, background .12s, color .12s;
      white-space: nowrap;
    }
    .tool-btn:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }
    .tool-btn.active { border-color: var(--accent); background: var(--accent); color: #fff; }

    .sb-search {
      padding: 8px 12px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }
    .search-inp {
      width: 100%; padding: 7px 10px;
      font-size: 13px; font-family: var(--font);
      border: 1.5px solid var(--border);
      border-radius: var(--r);
      background: var(--bg);
      outline: none;
      color: var(--text);
    }
    .search-inp:focus { border-color: var(--accent); }

    .sb-list-head {
      padding: 9px 16px 5px;
      font-size: 10.5px; font-weight: 600;
      text-transform: uppercase; letter-spacing: .5px;
      color: var(--muted);
      flex-shrink: 0;
    }
    .sb-list { flex: 1; overflow-y: auto; padding: 0 6px 8px; }

    .f-item {
      display: flex; align-items: center;
      padding: 8px 10px;
      border-radius: var(--r);
      cursor: pointer; gap: 9px;
      transition: background .1s;
      margin-bottom: 1px;
    }
    .f-item:hover { background: #f9fafb; }
    .f-item.sel { background: var(--accent-dim); }
    .f-dot { width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; }
    .f-info { flex: 1; min-width: 0; }
    .f-label { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .f-meta { font-size: 11px; color: var(--muted); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .f-btns { display: flex; gap: 2px; flex-shrink: 0; }
    .icon-btn {
      background: none; border: none; cursor: pointer;
      padding: 4px 5px; border-radius: 4px;
      font-size: 13px; color: var(--muted);
      transition: background .1s, color .1s;
      line-height: 1;
    }
    .icon-btn:hover { background: var(--bg); color: var(--text); }
    .icon-btn.del:hover { background: var(--danger-dim); color: var(--danger); }

    .empty {
      text-align: center; padding: 28px 14px;
      color: var(--muted); font-size: 12.5px; line-height: 1.6;
    }
    .empty .icon { font-size: 28px; margin-bottom: 8px; display: block; }

    /* ── Map ── */
    .map-wrap { flex: 1; position: relative; }
    #map { width: 100%; height: 100%; }

    /* ── Modal ── */
    .modal-bg {
      display: none; position: fixed; inset: 0;
      background: rgba(0,0,0,.32); z-index: 9000;
      align-items: center; justify-content: center;
    }
    .modal-bg.open { display: flex; }
    .modal {
      background: var(--surface); border-radius: 12px;
      padding: 22px 24px 20px; width: 340px; max-width: 95vw;
      box-shadow: 0 16px 48px rgba(0,0,0,.16);
    }
    .modal h2 { font-size: 15px; font-weight: 700; margin-bottom: 14px; }
    .field { margin-bottom: 12px; }
    .field label { display: block; font-size: 11px; font-weight: 600; margin-bottom: 4px; color: var(--muted); }
    .field input[type=text], .field textarea {
      width: 100%; padding: 7px 10px;
      font-size: 13px; font-family: var(--font);
      border: 1.5px solid var(--border);
      border-radius: var(--r); outline: none;
      color: var(--text); resize: vertical;
    }
    .field input:focus, .field textarea:focus { border-color: var(--accent); }
    .palette { display: flex; gap: 7px; flex-wrap: wrap; align-items: center; }
    .swatch {
      width: 24px; height: 24px; border-radius: 50%;
      border: 2.5px solid transparent; cursor: pointer;
      transition: transform .1s, border-color .1s;
    }
    .swatch:hover { transform: scale(1.1); }
    .swatch.on { border-color: var(--text); }
    .swatch-custom {
      width: 24px; height: 24px; border-radius: 50%;
      border: 1.5px dashed var(--border); cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      font-size: 13px; overflow: hidden; position: relative;
    }
    .swatch-custom input {
      position: absolute; inset: 0; opacity: 0; cursor: pointer;
      width: 100%; height: 100%;
    }
    .modal-foot { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
    .btn {
      padding: 7px 16px; font-size: 13px; font-weight: 500;
      border: none; border-radius: var(--r);
      cursor: pointer; transition: opacity .12s; font-family: var(--font);
    }
    .btn:hover { opacity: .85; }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-ghost { background: var(--bg); color: var(--text); border: 1.5px solid var(--border); }

    /* ── Toast ── */
    #toast {
      position: fixed; bottom: 18px; right: 18px;
      background: #1f2937; color: #fff;
      padding: 9px 14px; border-radius: 8px;
      font-size: 13px; z-index: 9999;
      opacity: 0; transform: translateY(6px);
      transition: opacity .2s, transform .2s;
      pointer-events: none;
    }
    #toast.show { opacity: 1; transform: translateY(0); }

    /* ── Draw hint bar ── */
    .draw-hint {
      display: none; position: absolute; bottom: 14px; left: 50%; transform: translateX(-50%);
      background: rgba(17,24,39,.82); color: #fff; backdrop-filter: blur(6px);
      padding: 7px 16px; border-radius: 20px; font-size: 12px;
      white-space: nowrap; z-index: 1000; pointer-events: none;
      box-shadow: 0 2px 12px rgba(0,0,0,.25);
    }
    .draw-hint.visible { display: block; }
    .map-wrap { cursor: default; }
    .map-wrap.drawing,
    .map-wrap.drawing .leaflet-container,
    .map-wrap.drawing .leaflet-interactive,
    .map-wrap.drawing .leaflet-marker-icon,
    .map-wrap.drawing .leaflet-marker-pane { cursor: crosshair !important; }

    /* Scrollbar */
    .sb-list::-webkit-scrollbar { width: 4px; }
    .sb-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
  </style>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <div class="sb-head">
      <h1><span>🗺</span> GeoPin</h1>
      <p>OpenStreetMap · GeoJSON editor</p>
    </div>
    <div class="sb-tools">
      <div class="tool-row">
        <button class="tool-btn" id="btn-marker" data-tool="marker">📍 Marker</button>
        <button class="tool-btn" id="btn-line" data-tool="line">✏️ Line</button>
        <button class="tool-btn" id="btn-polygon" data-tool="polygon">⬡ Polygon</button>
      </div>
    </div>
    <div class="sb-search">
      <input class="search-inp" id="search" type="text" placeholder="Search features…" oninput="renderList()">
    </div>
    <div class="sb-list-head" id="list-head">Features · 0</div>
    <div class="sb-list" id="list"></div>
  </aside>
  <div class="map-wrap" id="map-wrap">
    <div id="map"></div>
    <div class="draw-hint" id="draw-hint"></div>
  </div>
</div>

<!-- Modal -->
<div class="modal-bg" id="modal-bg">
  <div class="modal">
    <h2 id="modal-title">Add Feature</h2>
    <div class="field">
      <label>LABEL *</label>
      <input type="text" id="f-label" maxlength="120" placeholder="e.g. HQ, Route A, Zone 3">
    </div>
    <div class="field">
      <label>DESCRIPTION</label>
      <textarea id="f-desc" rows="2" maxlength="500" placeholder="Optional notes…"></textarea>
    </div>
    <div class="field">
      <label>COLOR</label>
      <div class="palette" id="palette"></div>
    </div>
    <div class="modal-foot">
      <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitModal()">Save Feature</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet-src.js"></script>
<script>
const COLORS = ['#2563eb','#16a34a','#d97706','#dc2626','#7c3aed','#db2777','#0891b2','#475569'];

// ── State ────────────────────────────────────────────────────────────────
let features = [], featureLayers = {}, selectedId = null;
let pendingGeom = null, editingId = null;
let pickedColor = COLORS[0];

// ── Draw state machine ────────────────────────────────────────────────────
// drawMode: null | 'marker' | 'line' | 'polygon'
let drawMode = null;
let drawPoints = [];       // [L.LatLng, ...]
let previewLayer = null;   // polyline/polygon shown while drawing

// ── Map setup ────────────────────────────────────────────────────────────
const map = L.map('map', { zoomControl: true, doubleClickZoom: false }).setView([20, 0], 2);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
}).addTo(map);
const drawn = new L.FeatureGroup().addTo(map);

// ── Draw helpers ──────────────────────────────────────────────────────────
function setDrawMode(mode) {
  drawMode = mode;
  drawPoints = [];
  if (previewLayer) { map.removeLayer(previewLayer); previewLayer = null; }
  document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
  const mapWrap = document.getElementById('map-wrap');
  const hint = document.getElementById('draw-hint');
  if (mode) {
    document.getElementById('btn-' + mode).classList.add('active');
    mapWrap.classList.add('drawing');
    const HINTS = {
      marker: 'Click to place a marker · ESC to cancel',
      line: 'Click to add points · Double-click to finish · ESC to cancel',
      polygon: 'Click to add vertices · Double-click to close · ESC to cancel',
    };
    hint.textContent = HINTS[mode] || '';
    hint.classList.add('visible');
  } else {
    mapWrap.classList.remove('drawing');
    hint.classList.remove('visible');
  }
}

function updatePreview(latlng) {
  if (drawPoints.length === 0) return;
  const pts = [...drawPoints, latlng];
  if (previewLayer) map.removeLayer(previewLayer);
  const style = { color: pickedColor, weight: 2, dashArray: '6 4', opacity: 0.8, fillOpacity: 0.15 };
  if (drawMode === 'line') {
    previewLayer = L.polyline(pts, style).addTo(map);
  } else if (drawMode === 'polygon' && pts.length >= 2) {
    previewLayer = L.polygon(pts, style).addTo(map);
  }
}

map.on('mousemove', e => {
  if (!drawMode || drawMode === 'marker') return;
  updatePreview(e.latlng);
});

map.on('click', e => {
  if (!drawMode) return;
  L.DomEvent.stopPropagation(e);
  if (drawMode === 'marker') {
    pendingGeom = { type: 'Point', coordinates: [e.latlng.lng, e.latlng.lat] };
    setDrawMode(null);
    openModal(null);
    return;
  }
  drawPoints.push(e.latlng);
  updatePreview(e.latlng);
});

map.on('dblclick', e => {
  if (!drawMode || drawMode === 'marker') return;
  L.DomEvent.stopPropagation(e);
  // Leaflet always fires exactly 2 click events before dblclick at the same position.
  // Remove those spurious points the click handler already added, then add the final
  // point once via the dblclick coordinates.
  const spurious = Math.min(2, drawPoints.length);
  drawPoints.splice(drawPoints.length - spurious, spurious);
  drawPoints.push(e.latlng);
  if (drawMode === 'line' && drawPoints.length >= 2) {
    pendingGeom = { type: 'LineString', coordinates: drawPoints.map(p => [p.lng, p.lat]) };
  } else if (drawMode === 'polygon' && drawPoints.length >= 3) {
    const ring = drawPoints.map(p => [p.lng, p.lat]);
    ring.push(ring[0]); // close ring
    pendingGeom = { type: 'Polygon', coordinates: [ring] };
  } else {
    return; // not enough points yet
  }
  if (previewLayer) { map.removeLayer(previewLayer); previewLayer = null; }
  setDrawMode(null);
  openModal(null);
});

// Tool button clicks via event delegation
document.querySelector('.sb-tools').addEventListener('click', e => {
  const btn = e.target.closest('[data-tool]');
  if (!btn) return;
  const tool = btn.dataset.tool;
  setDrawMode(drawMode === tool ? null : tool);
});

// ── API ───────────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body ? { 'content-type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

async function loadAll() {
  try {
    const d = await api('GET', '/api/features');
    features = d.features || [];
    reRenderMap(); renderList();
  } catch { toast('Failed to load features'); }
}

// ── Map rendering ──────────────────────────────────────────────────────────
function featureStyle(f) {
  const c = f.properties.color || '#2563eb';
  return { color: c, fillColor: c, fillOpacity: 0.22, weight: 2.5 };
}

function addToMap(f) {
  const { id, color = '#2563eb', label } = f.properties;
  let layer;
  if (f.geometry.type === 'Point') {
    const [lng, lat] = f.geometry.coordinates;
    layer = L.circleMarker([lat, lng], { radius: 7, ...featureStyle(f), fillOpacity: 0.9 });
  } else if (f.geometry.type === 'LineString') {
    layer = L.polyline(f.geometry.coordinates.map(c => [c[1], c[0]]), featureStyle(f));
  } else if (f.geometry.type === 'Polygon') {
    layer = L.polygon(f.geometry.coordinates[0].map(c => [c[1], c[0]]), featureStyle(f));
  }
  if (!layer) return;
  layer.bindTooltip(label, { permanent: false, direction: 'top', className: '' });
  layer.on('click', () => selectFeature(id));
  featureLayers[id] = layer;
  drawn.addLayer(layer);
}

function removeFromMap(id) {
  if (featureLayers[id]) { drawn.removeLayer(featureLayers[id]); delete featureLayers[id]; }
}

function reRenderMap() {
  drawn.clearLayers(); featureLayers = {};
  features.forEach(addToMap);
}

// ── Sidebar ────────────────────────────────────────────────────────────────
function typeLabel(t) {
  return { Point: '📍 Marker', LineString: '➖ Line', Polygon: '⬡ Polygon' }[t] || t;
}

function coordHint(f) {
  if (f.geometry.type === 'Point') {
    const [lng, lat] = f.geometry.coordinates;
    return lat.toFixed(4) + ', ' + lng.toFixed(4);
  }
  if (f.geometry.type === 'LineString') return f.geometry.coordinates.length + ' points';
  if (f.geometry.type === 'Polygon') return (f.geometry.coordinates[0].length - 1) + ' vertices';
  return '';
}

function selectFeature(id) {
  selectedId = id;
  document.querySelectorAll('.f-item').forEach(el => el.classList.toggle('sel', el.dataset.id === id));
  const f = features.find(x => x.properties.id === id);
  if (!f) return;
  if (f.geometry.type === 'Point') {
    const [lng, lat] = f.geometry.coordinates;
    map.flyTo([lat, lng], Math.max(map.getZoom(), 14), { duration: 0.5 });
  } else {
    const l = featureLayers[id];
    if (l) map.flyToBounds(l.getBounds(), { padding: [40, 40], maxZoom: 16, duration: 0.5 });
  }
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function renderList() {
  const q = (document.getElementById('search').value || '').toLowerCase();
  const filtered = features.filter(f => !q || f.properties.label.toLowerCase().includes(q));
  document.getElementById('list-head').textContent = 'Features · ' + features.length;
  const el = document.getElementById('list');
  if (filtered.length === 0) {
    el.innerHTML = '<div class="empty"><span class="icon">🗺️</span>' +
      (features.length === 0 ? 'No features yet.<br>Pick a draw tool above to place your first pin, line, or polygon.'
                             : 'No features match your search.') + '</div>';
    return;
  }
  el.innerHTML = filtered.map(f => {
    const { id, label, color, description } = f.properties;
    const meta = typeLabel(f.geometry.type) + ' · ' + coordHint(f) + (description ? ' · ' + esc(description.slice(0, 40)) : '');
    return \`<div class="f-item\${selectedId === id ? ' sel' : ''}" data-id="\${esc(id)}" data-action="select">
      <div class="f-dot" style="background:\${esc(color)}"></div>
      <div class="f-info">
        <div class="f-label">\${esc(label)}</div>
        <div class="f-meta">\${meta}</div>
      </div>
      <div class="f-btns">
        <button class="icon-btn" data-action="edit" data-id="\${esc(id)}" title="Edit">✏️</button>
        <button class="icon-btn del" data-action="delete" data-id="\${esc(id)}" title="Delete">🗑️</button>
      </div>
    </div>\`;
  }).join('');
}

// Sidebar click delegation — handles select, edit, delete without inline handlers
document.getElementById('list').addEventListener('click', e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  const id = btn.dataset.id || btn.closest('[data-id]')?.dataset.id;
  if (!id) return;
  if (action === 'edit') { e.stopPropagation(); openModal(id); }
  else if (action === 'delete') { e.stopPropagation(); doDelete(id); }
  else if (action === 'select') selectFeature(id);
});

// ── Modal ─────────────────────────────────────────────────────────────────
function buildPalette() {
  const el = document.getElementById('palette');
  el.innerHTML = COLORS.map(c =>
    \`<div class="swatch\${pickedColor === c ? ' on' : ''}" style="background:\${c}" onclick="pickColor('\${c}')" title="\${c}"></div>\`
  ).join('') + \`<label class="swatch-custom" title="Custom color" style="background:\${/^#/.test(pickedColor) && !COLORS.includes(pickedColor) ? pickedColor : '#fff'}">
    +<input type="color" value="\${pickedColor}" oninput="pickColor(this.value)">
  </label>\`;
}

function pickColor(c) { pickedColor = c; buildPalette(); }

function openModal(id) {
  editingId = id;
  document.getElementById('modal-title').textContent = id ? 'Edit Feature' : 'Add Feature';
  if (id) {
    const f = features.find(x => x.properties.id === id);
    if (f) {
      document.getElementById('f-label').value = f.properties.label;
      document.getElementById('f-desc').value = f.properties.description || '';
      pickedColor = f.properties.color || COLORS[0];
    }
  } else {
    document.getElementById('f-label').value = '';
    document.getElementById('f-desc').value = '';
    pickedColor = COLORS[0];
  }
  buildPalette();
  document.getElementById('modal-bg').classList.add('open');
  setTimeout(() => document.getElementById('f-label').focus(), 50);
}

function closeModal() {
  document.getElementById('modal-bg').classList.remove('open');
  if (!editingId) { pendingGeom = null; }
  editingId = null;
}

async function submitModal() {
  const label = document.getElementById('f-label').value.trim();
  if (!label) { toast('Label is required'); return; }
  const description = document.getElementById('f-desc').value.trim();
  try {
    if (editingId) {
      const d = await api('PUT', '/api/features/' + editingId, { label, color: pickedColor, description });
      if (d.error) throw new Error(d.error);
      const idx = features.findIndex(f => f.properties.id === editingId);
      if (idx !== -1) features[idx] = d.feature;
      removeFromMap(editingId); addToMap(d.feature);
      renderList(); toast('Feature updated');
    } else if (pendingGeom) {
      const d = await api('POST', '/api/features', { geometry: pendingGeom, label, color: pickedColor, description });
      if (d.error) throw new Error(d.error);
      features.push(d.feature);
      addToMap(d.feature); renderList();
      pendingGeom = null; toast('Feature saved');
    }
    closeModal();
  } catch (e) { toast('Error: ' + e.message); }
}

// ── Delete ─────────────────────────────────────────────────────────────────
async function doDelete(id) {
  const f = features.find(x => x.properties.id === id);
  if (!f || !confirm('Delete "' + f.properties.label + '"?')) return;
  try {
    const d = await api('DELETE', '/api/features/' + id);
    if (d.error) throw new Error(d.error);
    features = features.filter(x => x.properties.id !== id);
    removeFromMap(id);
    if (selectedId === id) selectedId = null;
    renderList(); toast('Feature deleted');
  } catch (e) { toast('Error: ' + e.message); }
}

// ── Toast ──────────────────────────────────────────────────────────────────
let toastTimer;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

// ── Global keyboard ────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (drawMode) { setDrawMode(null); return; }
    closeModal();
  }
  if (e.key === 'Enter' && document.getElementById('modal-bg').classList.contains('open') && document.activeElement.tagName !== 'TEXTAREA') {
    submitModal();
  }
});
document.getElementById('modal-bg').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeModal();
});

// ── Boot ───────────────────────────────────────────────────────────────────
loadAll();
</script>
</body>
</html>`;
}

// ── Request handler ─────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const parts = url.pathname.split('/').filter(Boolean);

  // Health
  if (req.method === 'GET' && (url.pathname === '/healthz' || url.pathname === '/health')) {
    return sendJson(res, 200, { ok: true, app: 'geopin' });
  }

  // UI
  if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/views/map_editor')) {
    return sendHtml(res, renderUI());
  }

  // REST — GET /api/features
  if (req.method === 'GET' && url.pathname === '/api/features') {
    const result = doList({
      geometry_type: url.searchParams.get('geometry_type') || undefined,
      label_contains: url.searchParams.get('label_contains') || undefined,
    });
    return sendJson(res, result.status, result.body.feature_collection);
  }

  // REST — POST /api/features
  if (req.method === 'POST' && url.pathname === '/api/features') {
    let body;
    try { body = await readBody(req); } catch { return sendJson(res, 400, { error: 'invalid JSON body' }); }
    const result = doCreate(body);
    return sendJson(res, result.status, result.body);
  }

  // REST — PUT /api/features/:id
  if (req.method === 'PUT' && parts[0] === 'api' && parts[1] === 'features' && parts[2]) {
    let body;
    try { body = await readBody(req); } catch { return sendJson(res, 400, { error: 'invalid JSON body' }); }
    const result = doUpdate(parts[2], body);
    return sendJson(res, result.status, result.body);
  }

  // REST — DELETE /api/features/:id
  if (req.method === 'DELETE' && parts[0] === 'api' && parts[1] === 'features' && parts[2]) {
    const result = doDelete(parts[2]);
    return sendJson(res, result.status, result.body);
  }

  // Platform actions
  if (req.method === 'POST' && parts[0] === 'actions') {
    let input;
    try { input = await readBody(req); } catch { return sendJson(res, 400, { error: 'invalid JSON body' }); }
    let result;
    if (parts[1] === 'add_feature') {
      result = doCreate(input);
    } else if (parts[1] === 'list_features') {
      result = doList(input);
    } else if (parts[1] === 'update_feature') {
      if (!input.feature_id) return sendJson(res, 400, { error: 'feature_id is required' });
      result = doUpdate(input.feature_id, input);
    } else if (parts[1] === 'delete_feature') {
      if (!input.feature_id) return sendJson(res, 400, { error: 'feature_id is required' });
      result = doDelete(input.feature_id);
    } else {
      return sendJson(res, 404, { error: 'unknown action', action: parts[1] });
    }
    // Platform actions return 201 → 200 for consistency with output_schema
    return sendJson(res, result.status === 201 ? 200 : result.status, result.body);
  }

  sendJson(res, 404, { error: 'not found', method: req.method, path: url.pathname });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[geopin] listening on :${PORT}`);
});

process.on('SIGTERM', () => server.close(() => process.exit(0)));
process.on('SIGINT', () => server.close(() => process.exit(0)));
