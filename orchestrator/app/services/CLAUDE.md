# services/

Business-logic services used by routers, agents, and workers.

## runtime_probe.py

`RuntimeProbe` performs bounded, non-blocking availability checks for execution
runtimes (local / docker / remote k8s). Each probe returns a `ProbeResult`
dataclass and never raises — failures are surfaced as `ok=False` with a
human-readable `reason`.

- Docker probe shells `docker info --format json` with a 3s timeout and caches
  the result for 30 seconds via a monotonic clock.
- The k8s remote probe is currently a stub returning
  `"Cloud pairing required"`; it will integrate with the pairing state once
  that lands.
- Access via the process-wide singleton `get_runtime_probe()`.

Used by `app/routers/desktop.py` to power the tray/runtime-probe endpoints.

## cloud_client.py + token_store.py

Desktop sidecar HTTP transport to the cloud companion. `CloudClient` is an
`httpx.AsyncClient` wrapper with bearer injection (sourced lazily from
`token_store.get_cloud_token()`), bounded 5xx retries (0.5s/1s/2s), and a
consecutive-failure circuit breaker (5 failures in 60s → open for 30s).
4xx never retries; `asyncio.CancelledError` propagates. Streaming requests
skip the retry loop but still respect the breaker. Use `get_cloud_client()`
for the process singleton, or instantiate directly in tests with a custom
`transport=httpx.MockTransport(...)` / `respx` router.

`token_store` is the on-disk contract for the eventual Tauri shell:
`$TESSLATE_CLOUD_TOKEN` env var wins, else `cache/cloud_token.json` under
`$TESSLATE_STUDIO_HOME` (atomic write, 0600 on POSIX). No network I/O.

Both modules are non-blocking on failure: routers should `try/except` and
fall back to cached/empty data so the desktop UI stays responsive when the
cloud is unreachable.

## marketplace_installer.py

Desktop-side install pipeline for marketplace items. `install(kind, slug)`
calls `POST /api/v1/marketplace/install` via `CloudClient` (cloud returns
signed download URLs + sha256 + manifest), streams each URL with a
bearer-LESS `httpx.AsyncClient` (signed S3/R2 URLs MUST NOT carry the cloud
bearer), verifies SHA-256, and atomically moves a `.installing/` staging
directory into `$TESSLATE_STUDIO_HOME/{kind}s/{slug}/`. Writes `manifest.json`
with `source: "local"`, `installed_from: "cloud"`, `install_id`. Best-effort
`POST .../ack` — ack failure logs but never raises.

All failures surface as `InstallError` (domain error) so the router can map
to a clean 4xx/5xx. Partial downloads are cleaned up on any error — the
target directory only appears on full success.

`uninstall(kind, slug) -> bool` removes the directory; returns False if
nothing was there.

## handoff_client.py

Pure serialization layer for agent ticket hand-offs between the desktop
orchestrator and a cloud peer. `push(session, ticket_id=...)` loads an
`AgentTask` and returns a frozen `HandoffBundle` (ticket id, title,
goal ancestry, plus trajectory/diff/skill-binding placeholders).
`pull(session, cloud_task_id=..., bundle=..., project_id=...)` creates a
fresh local ticket preserving ancestry and tagging the cloud origin. No
network I/O — HTTP transport and real trajectory/diff wiring are deferred
to later slices.
