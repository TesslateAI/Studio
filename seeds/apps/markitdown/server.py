"""Minimal FastAPI wrapper around Microsoft's MarkItDown.

Two surfaces:
- GET /           → a tiny HTML uploader + markdown preview (single-page).
- POST /convert   → multipart file upload; returns application/json
                    `{ markdown, filename }` so the page can render the result
                    with copy + download.

Designed to be iframe-friendly: no external network calls, no auth, no JS
frameworks. Serves inside a Tesslate App container at :3000.
"""
from __future__ import annotations

import io
import logging
from pathlib import PurePath

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from markitdown import MarkItDown

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("markitdown-app")

app = FastAPI(title="MarkItDown", docs_url=None, redoc_url=None)
_md = MarkItDown()


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>MarkItDown</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    :root {
      --bg: #0f0f11;
      --surface: #161618;
      --surface-hover: #1c1e21;
      --border: #1c1e21;
      --border-hover: #2a2c30;
      --text: #ffffff;
      --text-muted: #6b6f76;
      --text-subtle: #4a4e55;
      --primary: #f89521;
      --radius: 12px;
      --radius-small: 4px;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font: 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      display: flex; flex-direction: column;
    }
    header {
      padding: 14px 20px;
      border-bottom: 1px solid var(--border);
      display: flex; align-items: center; gap: 10px;
    }
    header .title { font-size: 13px; font-weight: 600; }
    header .sub { font-size: 11px; color: var(--text-muted); }
    main {
      flex: 1; min-height: 0;
      display: grid; grid-template-columns: 320px 1fr; gap: 1px; background: var(--border);
    }
    .pane { background: var(--bg); padding: 18px; overflow: auto; }
    .drop {
      border: 1px dashed var(--border-hover);
      border-radius: var(--radius);
      padding: 22px;
      text-align: center;
      color: var(--text-muted);
      cursor: pointer;
      background: var(--surface-hover);
      transition: border-color .15s ease, color .15s ease;
    }
    .drop:hover, .drop.drag { border-color: var(--primary); color: var(--text); }
    .drop input { display: none; }
    .btn {
      display: inline-flex; align-items: center; gap: 6px;
      height: 29px; padding: 0 12px;
      border-radius: 999px;
      background: var(--surface-hover);
      border: 1px solid var(--border);
      color: var(--text);
      font-size: 12px; font-weight: 500;
      cursor: pointer;
      transition: background .15s ease, border-color .15s ease;
    }
    .btn:hover { background: var(--surface); border-color: var(--border-hover); }
    .btn:disabled { opacity: .5; cursor: not-allowed; }
    .btn-primary { background: var(--primary); border-color: var(--primary); color: #fff; }
    .btn-primary:hover { opacity: .92; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .hint { font-size: 11px; color: var(--text-subtle); margin-top: 10px; }
    .meta { font-size: 11px; color: var(--text-muted); margin: 10px 0 14px; }
    textarea {
      width: 100%; height: 100%;
      min-height: 300px;
      background: var(--surface);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px;
      font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace;
      resize: none;
      outline: none;
    }
    textarea:focus { border-color: var(--border-hover); }
    .toolbar { display: flex; gap: 8px; margin-bottom: 10px; align-items: center; }
    .spinner {
      width: 12px; height: 12px; border: 2px solid var(--surface-hover);
      border-top-color: var(--primary); border-radius: 50%;
      animation: spin .7s linear infinite; display: inline-block; vertical-align: middle;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .error { color: #f46e6e; font-size: 12px; margin-top: 10px; }
    .empty { color: var(--text-subtle); font-size: 12px; padding: 40px 0; text-align: center; }
    @media (max-width: 760px) {
      main { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div class="title">MarkItDown</div>
    <div class="sub">PDF · Office · audio · YouTube → Markdown</div>
  </header>
  <main>
    <section class="pane">
      <label class="drop" id="drop">
        <div id="drop-text"><strong>Drop a file</strong> or click to browse</div>
        <div class="hint">PDF, DOCX, PPTX, XLSX, HTML, mp3/wav, zip, etc.</div>
        <input id="file" type="file" />
      </label>
      <div class="meta" id="meta">No file selected.</div>
      <div class="row">
        <button class="btn btn-primary" id="go" disabled>Convert</button>
        <button class="btn" id="download" disabled>Download .md</button>
        <button class="btn" id="copy" disabled>Copy</button>
      </div>
      <div class="error" id="error" hidden></div>
    </section>
    <section class="pane">
      <div class="toolbar">
        <span class="sub" style="color:var(--text-muted);font-size:11px;">Markdown</span>
        <span id="status" class="sub" style="color:var(--text-subtle);font-size:11px;"></span>
      </div>
      <textarea id="out" readonly placeholder="Converted markdown will appear here."></textarea>
    </section>
  </main>
<script>
(() => {
  const el = (id) => document.getElementById(id);
  const drop = el('drop'), input = el('file'), meta = el('meta');
  const go = el('go'), dl = el('download'), cp = el('copy');
  const out = el('out'), status = el('status'), error = el('error');
  let file = null;

  const setFile = (f) => {
    file = f;
    meta.textContent = f ? `${f.name} · ${(f.size/1024).toFixed(1)} KB` : 'No file selected.';
    go.disabled = !f;
  };
  input.addEventListener('change', () => setFile(input.files[0] || null));
  ;['dragenter','dragover'].forEach(e => drop.addEventListener(e, (ev) => {
    ev.preventDefault(); drop.classList.add('drag');
  }));
  ;['dragleave','drop'].forEach(e => drop.addEventListener(e, (ev) => {
    ev.preventDefault(); drop.classList.remove('drag');
  }));
  drop.addEventListener('drop', (ev) => {
    if (ev.dataTransfer?.files?.length) setFile(ev.dataTransfer.files[0]);
  });

  const showError = (msg) => {
    error.hidden = !msg; error.textContent = msg || '';
  };

  go.addEventListener('click', async () => {
    if (!file) return;
    go.disabled = true; dl.disabled = true; cp.disabled = true;
    showError(''); out.value = '';
    status.innerHTML = '<span class="spinner"></span> Converting…';
    const body = new FormData(); body.append('file', file);
    try {
      const res = await fetch('/convert', { method: 'POST', body });
      if (!res.ok) {
        const text = await res.text();
        showError(text || `HTTP ${res.status}`);
        status.textContent = '';
      } else {
        const json = await res.json();
        out.value = json.markdown || '';
        status.textContent = json.markdown ? `${json.markdown.length.toLocaleString()} chars` : 'Empty result.';
        dl.disabled = !json.markdown;
        cp.disabled = !json.markdown;
      }
    } catch (e) {
      showError(String(e));
      status.textContent = '';
    } finally {
      go.disabled = !file;
    }
  });

  dl.addEventListener('click', () => {
    if (!out.value || !file) return;
    const baseName = file.name.replace(/\\.[^.]+$/, '') || 'output';
    const blob = new Blob([out.value], { type: 'text/markdown' });
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href; a.download = baseName + '.md';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 0);
  });

  cp.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(out.value); status.textContent = 'Copied.'; }
    catch { status.textContent = 'Copy failed.'; }
  });
})();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    return "ok"


@app.post("/convert")
async def convert(file: UploadFile = File(...)) -> JSONResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    # MarkItDown needs a filename hint to pick a converter. Pass the original
    # filename via stream_info.
    name = file.filename or "upload"
    ext = PurePath(name).suffix.lower() or None

    try:
        # convert_stream requires a binary file-like object (post-0.1.0 API).
        result = _md.convert_stream(io.BytesIO(data), file_extension=ext, url=None)
    except Exception as exc:  # MarkItDown wraps converter errors in its own hierarchy.
        logger.warning("convert failed name=%s ext=%s err=%r", name, ext, exc)
        raise HTTPException(status_code=422, detail=f"conversion failed: {exc}") from exc

    return JSONResponse({"markdown": result.text_content or "", "filename": name})
