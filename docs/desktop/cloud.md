# Desktop ↔ cloud transport

The desktop sidecar talks to the cloud companion through a single
bounded-retry, circuit-broken HTTP client with a small on-disk token store.

## CloudClient

File: `/orchestrator/app/services/cloud_client.py`.

Thin wrapper around `httpx.AsyncClient` with three desktop-specific behaviors:

- **Bearer injection**: every call reads `token_store.get_cloud_token()`
  *at call time*. Missing token → `NotPairedError` (no network I/O).
- **Bounded retries**: 5xx responses retry on `0.5s, 1.0s, 2.0s` then surface
  the last response to the caller. 4xx never retries.
  `asyncio.CancelledError` propagates.
- **Circuit breaker**: `_CircuitBreaker` opens after
  `_CB_FAILURE_THRESHOLD = 5` failures inside
  `_CB_FAILURE_WINDOW_S = 60.0`s, staying open for
  `_CB_OPEN_DURATION_S = 30.0`s; while open, calls fail fast with
  `CircuitOpenError`. Any non-5xx response resets the counter (half-open on
  expiry: one probe request; success closes, failure re-opens).

Pool / timeout:

- `max_connections=20`, `max_keepalive_connections=5`
- `httpx.Timeout(30.0)` default

Public API: `await client.get(path, params=…)`, `await client.post(path, json=…)`,
`async with client.stream(path, method=…) as resp:` (streams skip the retry
loop — the body would be partially consumed — but still enforce the breaker).

Use `await get_cloud_client()` for the process-wide singleton; tests can
construct `CloudClient(base_url=…, transport=httpx.MockTransport(...))` and
call `reset_cloud_client_for_tests()` in teardown.

### Exceptions

| Class              | Meaning                                                          |
| ------------------ | ---------------------------------------------------------------- |
| `CloudClientError` | Base class.                                                      |
| `NotPairedError`   | No cloud bearer token available — user must pair the desktop.    |
| `CircuitOpenError` | Breaker is open; back off and surface as 502 to the UI.          |

## token_store

File: `/orchestrator/app/services/token_store.py`. No network I/O.

Precedence (read order):

1. `$TESSLATE_CLOUD_TOKEN` env var — Tauri-side injection; wins when set.
2. `$TESSLATE_STUDIO_HOME/cache/cloud_token.json` — written by the auth-token
   endpoint.

`set_cloud_token(token)` writes atomically via `tempfile.mkstemp` + `os.replace`
and chmods the file to `0600` on POSIX. `clear_cloud_token()` unlinks only the
file — env var overrides are never touched. `is_paired()` returns `True` iff
either source yields a non-empty token.

## Pairing endpoints

Router: `/orchestrator/app/routers/desktop/auth.py`.

| Method   | Path                         | Body / Response                                 |
| -------- | ---------------------------- | ----------------------------------------------- |
| `GET`    | `/api/desktop/auth/status`   | `→ {paired: bool, cloud_url: str}` (network-free) |
| `POST`   | `/api/desktop/auth/token`    | `{token: str}` → `{paired: true}`               |
| `DELETE` | `/api/desktop/auth/token`    | `→ {paired: false}`                             |

`CloudTokenBody` validates `1 ≤ len(token) ≤ 512`. The raw token is never
returned by any GET — only the `paired` boolean.

## Deep-link contract

The Tauri shell registers `tesslate://` and, on completion of the cloud's
`POST /api/desktop/pair/complete` flow, receives:

```
tesslate://auth/callback?token=tsk_…
```

The deep-link handler forwards the token to the local sidecar via
`POST /api/desktop/auth/token`. The token never transits beyond the local
loopback boundary from the desktop side.

## Error mapping (consumers)

Routers that call `CloudClient` translate the exceptions consistently:

| Caught exception   | HTTP status |
| ------------------ | ----------- |
| `NotPairedError`   | 401         |
| `CircuitOpenError` | 502         |
| transport / 5xx    | 502         |

Examples: `marketplace_local.install_item`, `desktop.sync_push`/`sync_pull`.

## Related

- `/docs/desktop/marketplace.md` — primary consumer of `CloudClient`.
- `/docs/desktop/sync.md` — reuses `client._client` + `_build_headers()` for multipart.
- `/docs/desktop/runtimes.md` — the `k8s_remote_available` probe will read `is_paired()`.
