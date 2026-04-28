// Surfaces MathKit — dependency-target test app for OpenSail surface coverage.
// Exposes:
//   POST /actions/multiply       — { x, y } -> { product }
//   POST /actions/last_result    — {} -> { last_x, last_y, last_product, calls }
//   GET  /views/calculator       — card view (HTML)
//   GET  /healthz                — liveness
//   GET  /                       — UI (also acts as ui surface)

const http = require('http');

const PORT = parseInt(process.env.PORT || '3000', 10);

const state = {
  calls: 0,
  last_x: null,
  last_y: null,
  last_product: null,
  startedAt: new Date().toISOString(),
};

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => { raw += chunk; });
    req.on('end', () => {
      if (!raw) return resolve({});
      try { resolve(JSON.parse(raw)); }
      catch (e) { reject(e); }
    });
    req.on('error', reject);
  });
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

function sendHtml(res, status, html) {
  const body = Buffer.from(html, 'utf-8');
  res.writeHead(status, {
    'content-type': 'text/html; charset=utf-8',
    'content-length': body.length,
  });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  if (req.method === 'GET' && (url.pathname === '/healthz' || url.pathname === '/health')) {
    return sendJson(res, 200, { ok: true, app: 'surfaces-mathkit', uptime_s: Math.floor((Date.now() - new Date(state.startedAt).getTime()) / 1000) });
  }

  if (req.method === 'POST' && url.pathname === '/actions/multiply') {
    let input;
    try { input = await readJsonBody(req); }
    catch { return sendJson(res, 400, { error: 'invalid json body' }); }
    const x = Number(input?.x);
    const y = Number(input?.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return sendJson(res, 400, { error: 'x and y must be numbers' });
    }
    const product = x * y;
    state.calls += 1;
    state.last_x = x;
    state.last_y = y;
    state.last_product = product;
    return sendJson(res, 200, { product });
  }

  if (req.method === 'POST' && url.pathname === '/actions/last_result') {
    return sendJson(res, 200, {
      last_x: state.last_x,
      last_y: state.last_y,
      last_product: state.last_product,
      calls: state.calls,
    });
  }

  if (req.method === 'GET' && url.pathname === '/views/calculator') {
    return sendHtml(res, 200, `<!doctype html><html><body style="font-family:system-ui;padding:24px">
      <h1>MathKit calculator</h1>
      <p>calls=${state.calls} last=${state.last_x} × ${state.last_y} = ${state.last_product ?? 'never'}</p>
    </body></html>`);
  }

  if (req.method === 'GET' && url.pathname === '/') {
    return sendHtml(res, 200, `<!doctype html><html><body style="font-family:system-ui;padding:24px">
      <h1>Surfaces MathKit</h1>
      <ul>
        <li>POST /actions/multiply { x, y } → { product }</li>
        <li>POST /actions/last_result → { last_x, last_y, last_product, calls }</li>
        <li>GET /views/calculator</li>
        <li>GET /healthz</li>
      </ul>
      <p>state: calls=${state.calls}</p>
    </body></html>`);
  }

  sendJson(res, 404, { error: 'not found', method: req.method, path: url.pathname });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[mathkit] listening on :${PORT}`);
});

process.on('SIGTERM', () => server.close(() => process.exit(0)));
process.on('SIGINT', () => server.close(() => process.exit(0)));
