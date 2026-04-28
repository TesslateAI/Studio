// Test Surfaces — comprehensive surface-test app for OpenSail.
// Action handlers (POST):
//   /actions/echo        — { message } -> { echoed, echoed_at }
//   /actions/add         — { a, b } -> { sum }
//   /actions/now         — {} -> { now_iso, calls }
// View entrypoints (GET):
//   /views/dashboard     — full_page view
//   /                    — also renders dashboard (ui surface)
//   /healthz             — liveness probe

const http = require('http');

const PORT = parseInt(process.env.PORT || '3000', 10);

const counters = { now: 0, echo: 0, add: 0 };
const startedAt = new Date().toISOString();

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

function dashboardHtml() {
  return `<!doctype html><html><body style="font-family:system-ui;padding:24px;max-width:720px">
    <h1>Test Surfaces — Dashboard</h1>
    <p>Started at ${startedAt}.</p>
    <h2>Counters</h2>
    <ul>
      <li>echo: ${counters.echo}</li>
      <li>add_numbers: ${counters.add}</li>
      <li>now: ${counters.now}</li>
    </ul>
    <h2>Endpoints</h2>
    <ul>
      <li>POST /actions/echo { message } → { echoed, echoed_at }</li>
      <li>POST /actions/add { a, b } → { sum }</li>
      <li>POST /actions/now → { now_iso, calls }</li>
      <li>GET /views/dashboard</li>
      <li>GET /healthz</li>
    </ul>
  </body></html>`;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  if (req.method === 'GET' && (url.pathname === '/healthz' || url.pathname === '/health')) {
    return sendJson(res, 200, { ok: true, app: 'test-surfaces', counters });
  }

  if (req.method === 'POST' && url.pathname === '/actions/echo') {
    let input;
    try { input = await readJsonBody(req); }
    catch { return sendJson(res, 400, { error: 'invalid json body' }); }
    const message = input?.message;
    if (typeof message !== 'string' || message.length === 0) {
      return sendJson(res, 400, { error: 'message must be a non-empty string' });
    }
    counters.echo += 1;
    return sendJson(res, 200, { echoed: message, echoed_at: new Date().toISOString() });
  }

  if (req.method === 'POST' && url.pathname === '/actions/add') {
    let input;
    try { input = await readJsonBody(req); }
    catch { return sendJson(res, 400, { error: 'invalid json body' }); }
    const a = Number(input?.a);
    const b = Number(input?.b);
    if (!Number.isFinite(a) || !Number.isFinite(b)) {
      return sendJson(res, 400, { error: 'a and b must be numbers' });
    }
    counters.add += 1;
    return sendJson(res, 200, { sum: a + b });
  }

  if (req.method === 'POST' && url.pathname === '/actions/now') {
    counters.now += 1;
    return sendJson(res, 200, {
      now_iso: new Date().toISOString(),
      calls: counters.now,
    });
  }

  if (req.method === 'GET' && (url.pathname === '/views/dashboard' || url.pathname === '/')) {
    return sendHtml(res, 200, dashboardHtml());
  }

  sendJson(res, 404, { error: 'not found', method: req.method, path: url.pathname });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[test-surfaces] listening on :${PORT}`);
});

process.on('SIGTERM', () => server.close(() => process.exit(0)));
process.on('SIGINT', () => server.close(() => process.exit(0)));
