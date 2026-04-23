# routers/

FastAPI routers. Each module exposes a `router = APIRouter(...)` that
`app/main.py` includes once. Auth dependency is the unified
`current_active_user` (session) or `require_api_scope(...)` (tsk-auth).

## desktop.py

Tray/runtime endpoints plus the **cloud auth shim**:

- `GET  /api/desktop/auth/status` — `{paired, cloud_url}`. Network-free; just
  asks `services.token_store.is_paired()`. Used by the tray to render the
  "Pair" affordance.
- `POST /api/desktop/auth/token` — body `{token}`. Persists the bearer minted
  by the cloud's `/api/desktop/pair/complete`. Called by the Tauri deep-link
  handler after `tesslate://auth/callback?token=...`.
- `DELETE /api/desktop/auth/token` — clears the local token (logout).

The token never leaves the sidecar process via these endpoints — only `paired`
is ever returned.

## marketplace_local.py

`/api/desktop/marketplace/items?kind=agent|skill|base|theme` — lists installed
items from `$OPENSAIL_HOME/{agents,skills,bases,themes}/*/manifest.json`
(`source: "local"`). When `settings.pull_from_cloud` is on AND a cloud token
exists, ALSO fetches the cloud catalog via `services.cloud_client.CloudClient`
(`source: "cloud"`). Cloud failures are swallowed (NotPaired, CircuitOpen,
5xx, transport error → log.debug, return local-only).

1h on-disk cache at `$OPENSAIL_HOME/cache/marketplace.json` with
stale-while-revalidate: stale entries return immediately and trigger a
background refresh via `BackgroundTasks`.

Install pipeline:
- `POST /api/desktop/marketplace/install` body `{kind, slug}` — delegates to
  `services.marketplace_installer.install()`. 201 + InstallResult on success,
  409 if already installed, 401 on `NotPairedError`, 502 on
  `CircuitOpenError` / cloud transport error.
- `DELETE /api/desktop/marketplace/install/{kind}/{slug}` — 204 on success,
  404 if not installed.
- Both endpoints invalidate the on-disk `marketplace.json` cache for that
  kind so the next `GET /items` reflects the change.
