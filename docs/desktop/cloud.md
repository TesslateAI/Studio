# Desktop ↔ cloud transport

The desktop sidecar talks to the cloud companion through a single
bounded-retry, circuit-broken HTTP client with small on-disk config/token
stores.

Tesslate Studio desktop runs **fully offline by default** — the sidecar
auto-provisions a local account (`local@desktop.tesslate.app`) and the Tauri
host auto-logs in via `GET /api/desktop/local-auth`. Signing in to a Tesslate
Cloud account is **optional** and only needed for: LLM calls billed to account
credits, the cloud marketplace catalog, and project sync.

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

Base URL comes from `cloud_config.get_cloud_url()` (see below), not directly
from settings. Pool / timeout: `max_connections=20`,
`max_keepalive_connections=5`, `httpx.Timeout(30.0)`.

Public API: `await client.get(path, params=…)`, `await client.post(path, json=…)`,
`async with client.stream(path, method=…) as resp:` (streams skip the retry
loop — the body would be partially consumed — but still enforce the breaker).

`client.get(path, anonymous=True)` skips bearer injection entirely and does
NOT raise `NotPairedError` when there is no token — used for the public
marketplace browse endpoints (`/api/marketplace/public/*`) so an unpaired
desktop can still fetch the production catalog.

Use `await get_cloud_client()` for the process-wide singleton.
`reset_cloud_client()` drops the singleton — call it after the cloud URL
changes so the next request targets the new endpoint (the `PUT /cloud-url`
endpoint does this). Tests can construct
`CloudClient(base_url=…, transport=httpx.MockTransport(...))`;
`reset_cloud_client_for_tests` remains as a back-compat alias.

### Exceptions

| Class              | Meaning                                                          |
| ------------------ | ---------------------------------------------------------------- |
| `CloudClientError` | Base class.                                                      |
| `NotPairedError`   | No cloud bearer token available — user must pair the desktop.    |
| `CircuitOpenError` | Breaker is open; back off and surface as 502 to the UI.          |

## cloud_config

File: `/orchestrator/app/services/cloud_config.py`. No network I/O.

The cloud companion endpoint is user-overridable so self-hosters / beta
testers can point the desktop at their own cloud. Resolution order:

1. `$TESSLATE_CLOUD_URL` env var — Tauri-side / ops override; wins when set.
2. `$OPENSAIL_HOME/cache/cloud_url.json` — written by `PUT /api/desktop/cloud-url`.
3. `settings.tesslate_cloud_url` — compiled-in default (`https://opensail.tesslate.com`).

`normalize_cloud_url(url)` requires an `http`/`https` scheme + host and strips
trailing slash + path so callers can append `/api/...` deterministically;
bad input raises `InvalidCloudUrlError`. `set_cloud_url` writes atomically
(tmp + rename, 0600 on POSIX); `clear_cloud_url` reverts to the default.

## token_store

File: `/orchestrator/app/services/token_store.py`. No network I/O.

Precedence: `$TESSLATE_CLOUD_TOKEN` env var, else
`$OPENSAIL_HOME/cache/cloud_token.json`. `set_cloud_token` / `clear_cloud_token`
manage the file; `is_paired()` returns `True` iff either source yields a token.

## desktop_state

File: `/orchestrator/app/services/desktop_state.py`. No network I/O.

One flag at `$OPENSAIL_HOME/cache/desktop_state.json`:
`first_run_complete`. Drives the one-time first-run setup dialog.

## LLM proxy (account credits)

When the desktop is paired, `get_llm_client` (`services/model_adapters.py`)
routes **system models** (unprefixed / `builtin/`) through the cloud
companion's OpenAI-compatible proxy:

```
AsyncOpenAI(base_url = get_cloud_url() + "/api/v1", api_key = <cloud tsk_ token>)
        → POST {cloud}/api/v1/chat/completions   (routers/public/models.py)
        → credit check + deduct → internal LiteLLM
```

The internal LiteLLM is **never** exposed to the desktop — the desktop only
ever talks to the cloud orchestrator's public proxy. This covers both the
chat path and the agent worker (`create_model_adapter` → `get_llm_client`).

Fallback order in the desktop / no-litellm-key branch: cloud proxy (if paired)
→ explicit `LITELLM_API_BASE`+`LITELLM_MASTER_KEY` → `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` env vars → any active BYOK row →
`ValueError`. BYOK-prefixed models (`openai/…`) always go direct, regardless
of pairing.

## Endpoints

Router: `/orchestrator/app/routers/desktop/auth.py`. All use
`desktop_loopback_or_session` auth.

| Method   | Path                          | Body / Response                                                  |
| -------- | ----------------------------- | ---------------------------------------------------------------- |
| `GET`    | `/api/desktop/auth/status`    | `→ {paired, cloud_url, default_cloud_url}` (network-free)         |
| `POST`   | `/api/desktop/auth/token`     | `{token}` → `{paired: true}`                                     |
| `DELETE` | `/api/desktop/auth/token`     | `→ {paired: false}` (sign out)                                   |
| `PUT`    | `/api/desktop/cloud-url`      | `{url}` → `{cloud_url}` — 400 on bad URL; resets `CloudClient`    |
| `DELETE` | `/api/desktop/cloud-url`      | `→ {cloud_url}` — reverts to default                             |
| `GET`    | `/api/desktop/first-run`      | `→ {completed: bool}`                                            |
| `POST`   | `/api/desktop/first-run`      | `→ {completed: true}` — marks first-run done                     |

`CloudTokenBody` / `CloudUrlBody` validate `1 ≤ len ≤ 512`. The raw token is
never returned by any GET — only the `paired` boolean.

## Sign-in flow

1. **Settings → Cloud** (`app/src/pages/settings/CloudSettings.tsx`, desktop-only
   tab) — "Sign in" calls the Tauri `open_external_url` command, opening
   `{cloud_url}/desktop/pair` in the system browser.
2. **`/desktop/pair`** (`app/src/pages/DesktopPairPage.tsx`) — the same React
   app served by the cloud; `PrivateRoute` bounces anonymous visitors through
   `/login` and back. The user names the device and authorizes it; the page
   calls `POST /api/desktop/pair/complete` (session-auth, `desktop_pair.py`)
   which mints a desktop-scoped `tsk_` key returned exactly once.
3. The page hands the key back as `tesslate://auth/callback?token=…`.
4. **deep_link.rs** catches it, persists via `POST /api/desktop/auth/token`.
   `CloudSettings` polls `auth/status` so the UI flips to "connected".

First-run: `FirstRunDialog` (`app/src/components/desktop/FirstRunDialog.tsx`)
shows once after auto-login — sign in to cloud, bring your own keys, or skip.

## Deep-link contract

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

## Deferred: local ↔ cloud identity merge

Pairing is **transport-only** — the cloud token wires `CloudClient` + the LLM
proxy but does not reassign ownership of the local user's projects, BYOK keys,
or chats. A user who starts offline and later pairs keeps two separate
principals. Merging them (project transfer, BYOK re-encryption) is tracked in
issue #491, not implemented here.

## Related

- `/docs/desktop/marketplace.md` — primary consumer of `CloudClient`.
- `/docs/desktop/sync.md` — reuses `client._client` + `_build_headers()` for multipart.
- `/docs/desktop/runtimes.md` — the `k8s_remote_available` probe will read `is_paired()`.
