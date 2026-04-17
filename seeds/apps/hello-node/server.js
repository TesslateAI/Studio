// Tesslate hello-node seed — zero-dependency Node.js HTTP server.
// Proves the Apps runtime can boot a long-running process (not a static page)
// without any `npm install` step. Uses only Node's built-in `http` and `os`.

const http = require('node:http');
const os = require('node:os');

const PORT = parseInt(process.env.PORT, 10) || 3000;
const BOOTED_AT = new Date();
let requests = 0;

const page = () => {
  requests += 1;
  const uptimeSec = Math.round((Date.now() - BOOTED_AT.getTime()) / 1000);
  const hh = String(Math.floor(uptimeSec / 3600)).padStart(2, '0');
  const mm = String(Math.floor((uptimeSec % 3600) / 60)).padStart(2, '0');
  const ss = String(uptimeSec % 60).padStart(2, '0');

  const stats = [
    { label: 'Requests served', value: requests.toLocaleString(), hint: 'Incremented server-side, per hit' },
    { label: 'Uptime', value: `${hh}:${mm}:${ss}`, hint: `Booted at ${BOOTED_AT.toISOString()}` },
    { label: 'Node runtime', value: process.version, hint: `${process.platform}/${process.arch}` },
    { label: 'Process', value: `pid ${process.pid}`, hint: os.hostname() },
  ];

  const rows = stats
    .map(
      (s) => `
      <div class="stat">
        <div class="stat-label">${s.label}</div>
        <div class="stat-value">${s.value}</div>
        <div class="stat-hint">${s.hint}</div>
      </div>`,
    )
    .join('');

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Hello from Tesslate</title>
  <style>
    :root {
      --bg-0: #0a0b14;
      --bg-1: #141528;
      --fg: #f5f6fb;
      --muted: #a5a8c0;
      --accent: #9d7bff;
      --accent-2: #6fe0ff;
      --ring: rgba(157, 123, 255, 0.35);
      --card: rgba(255, 255, 255, 0.04);
      --border: rgba(255, 255, 255, 0.08);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; min-height: 100%; }
    body {
      font-family: ui-sans-serif, system-ui, -apple-system, "SF Pro Text", "Inter", sans-serif;
      color: var(--fg);
      background:
        radial-gradient(1100px 600px at 10% -10%, rgba(111, 224, 255, 0.22), transparent 60%),
        radial-gradient(1000px 700px at 100% 0%, rgba(157, 123, 255, 0.28), transparent 55%),
        radial-gradient(900px 600px at 50% 120%, rgba(255, 120, 200, 0.14), transparent 60%),
        linear-gradient(180deg, var(--bg-0), var(--bg-1));
      display: grid;
      place-items: center;
      padding: 48px 20px;
      overflow-x: hidden;
    }
    .shell {
      width: min(920px, 100%);
      position: relative;
    }
    .shell::before {
      content: "";
      position: absolute;
      inset: -1px;
      border-radius: 28px;
      padding: 1px;
      background: linear-gradient(135deg, rgba(157, 123, 255, 0.7), rgba(111, 224, 255, 0.35) 55%, transparent 85%);
      -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
      -webkit-mask-composite: xor;
              mask-composite: exclude;
      pointer-events: none;
    }
    .card {
      position: relative;
      border-radius: 28px;
      padding: 44px 44px 40px;
      background:
        linear-gradient(180deg, rgba(20, 21, 40, 0.72), rgba(10, 11, 20, 0.82));
      backdrop-filter: blur(14px) saturate(140%);
      border: 1px solid var(--border);
      box-shadow: 0 30px 80px -30px rgba(0, 0, 0, 0.6), 0 2px 0 rgba(255,255,255,0.04) inset;
    }
    .kicker {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
    }
    .kicker .dot {
      width: 8px; height: 8px; border-radius: 50%;
      background: #5bff9a;
      box-shadow: 0 0 0 0 rgba(91, 255, 154, 0.7);
      animation: pulse 2s ease-out infinite;
    }
    @keyframes pulse {
      0%   { box-shadow: 0 0 0 0 rgba(91, 255, 154, 0.55); }
      70%  { box-shadow: 0 0 0 10px rgba(91, 255, 154, 0); }
      100% { box-shadow: 0 0 0 0 rgba(91, 255, 154, 0); }
    }
    h1 {
      margin: 22px 0 10px;
      font-size: clamp(36px, 6vw, 60px);
      line-height: 1.05;
      letter-spacing: -0.02em;
      font-weight: 700;
    }
    h1 .grad {
      background: linear-gradient(90deg, var(--accent-2), var(--accent) 60%, #ff9ad3);
      -webkit-background-clip: text;
              background-clip: text;
      color: transparent;
    }
    p.lede {
      margin: 0 0 28px;
      color: var(--muted);
      font-size: 17px;
      max-width: 60ch;
      line-height: 1.55;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin: 8px 0 24px;
    }
    .stat {
      padding: 16px 18px;
      border-radius: 16px;
      background: var(--card);
      border: 1px solid var(--border);
      transition: transform 180ms ease, border-color 180ms ease, background 180ms ease;
    }
    .stat:hover {
      transform: translateY(-2px);
      border-color: var(--ring);
      background: rgba(255,255,255,0.05);
    }
    .stat-label {
      font-size: 11px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .stat-value {
      margin-top: 8px;
      font-size: 22px;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
      font-feature-settings: "tnum" 1;
    }
    .stat-hint {
      margin-top: 4px;
      font-size: 12px;
      color: var(--muted);
    }
    .row {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }
    a.btn, button.btn {
      appearance: none;
      border: 1px solid var(--border);
      color: var(--fg);
      background: rgba(255,255,255,0.04);
      padding: 10px 14px;
      border-radius: 12px;
      text-decoration: none;
      font-size: 14px;
      cursor: pointer;
      transition: border-color 180ms ease, background 180ms ease, transform 180ms ease;
    }
    a.btn:hover, button.btn:hover {
      border-color: var(--ring);
      background: rgba(157,123,255,0.12);
      transform: translateY(-1px);
    }
    .tag {
      font-family: ui-monospace, "SF Mono", Menlo, monospace;
      font-size: 12px;
      padding: 4px 8px;
      border-radius: 8px;
      color: var(--muted);
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
    }
    footer {
      margin-top: 28px;
      color: var(--muted);
      font-size: 12px;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="card">
      <span class="kicker"><span class="dot"></span> Server online</span>
      <h1>Hello from <span class="grad">Tesslate</span>.</h1>
      <p class="lede">
        You are looking at a live Node.js process inside a Tesslate App container.
        No build step, no <code>npm install</code>, no framework — just a handful
        of lines using Node's built-in <span class="tag">http</span> module.
        Refresh and watch the counters tick.
      </p>

      <div class="stats">${rows}</div>

      <div class="row">
        <a class="btn" href="/">Refresh</a>
        <a class="btn" href="/healthz">/healthz</a>
        <a class="btn" href="/api/info">/api/info</a>
        <span class="tag">served at ${new Date().toISOString()}</span>
      </div>

      <footer>
        <span>Tesslate Apps &middot; hello-node seed</span>
        <span>${os.type()} ${os.release()} &middot; ${os.cpus().length} CPU</span>
      </footer>
    </section>
  </main>
</body>
</html>`;
};

const server = http.createServer((req, res) => {
  if (req.url === '/healthz') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ ok: true, uptime_s: Math.round(process.uptime()) }));
    return;
  }
  if (req.url === '/api/info') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(
      JSON.stringify({
        hostname: os.hostname(),
        node: process.version,
        pid: process.pid,
        uptime_s: Math.round(process.uptime()),
        requests,
        booted_at: BOOTED_AT.toISOString(),
      }),
    );
    return;
  }
  res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
  res.end(page());
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[hello-node] listening on http://0.0.0.0:${PORT} (pid ${process.pid}, node ${process.version})`);
});

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    console.log(`[hello-node] ${sig} — closing`);
    server.close(() => process.exit(0));
  });
}
