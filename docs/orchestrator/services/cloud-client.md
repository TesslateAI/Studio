# Cloud Client and Sync Client - Desktop Sidecar ↔ Cloud Transport

## Overview

Two companion modules handle all HTTP communication from the desktop sidecar to the Tesslate cloud:

- **`cloud_client.py`** — general-purpose `httpx.AsyncClient` wrapper with bearer auth, retries, and a circuit breaker. Used for API calls (model proxy, usage, marketplace).
- **`sync_client.py`** — project sync pipeline (push/pull) built on top of `CloudClient`. Handles zipping, manifest computation, conflict detection, and atomic extraction.

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/cloud_client.py` | `CloudClient` class and `get_cloud_client()` singleton |
| `orchestrator/app/services/sync_client.py` | `push()`, `pull()`, `pack_project()`, `compute_manifest()`, `get_sync_client()` |
| `orchestrator/app/services/token_store.py` | Read/write the `tsk_` bearer token from env or disk |

---

## CloudClient

### Purpose

Process-wide async HTTP client for all desktop-to-cloud requests. Injects the user's bearer token on every call, retries on 5xx, and protects against cascading failures with a circuit breaker.

### Construction

```python
from app.services.cloud_client import get_cloud_client, CloudClient

# Singleton (preferred in production code)
client = await get_cloud_client()

# Direct construction (tests)
client = CloudClient(base_url="http://localhost:8000", transport=my_mock_transport)
```

`get_cloud_client()` is async-safe (uses `asyncio.Lock`) and returns the same instance for the process lifetime.

### Configuration

| Setting | Source | Default |
|---------|--------|---------|
| `tesslate_cloud_url` | `settings.tesslate_cloud_url` | `https://opensail.tesslate.com` |
| Connection pool | hardcoded | `max_connections=20`, `max_keepalive_connections=5` |
| Request timeout | hardcoded | `30s` |

### Bearer Token

On every request, `_build_headers()` calls `token_store.get_cloud_token()`. If no token is available, `NotPairedError` is raised immediately — no network call is made. The token is a `tsk_` API key stored via `token_store` (see below).

### Retry Policy

- Applies to standard `GET` and `POST` calls only.
- Streaming (`stream()`, `stream_post()`) and multipart uploads (`post_multipart()`) do **not** retry — the response body would be partially consumed.
- 5xx responses: retry with delays of `0.5s → 1.0s → 2.0s`, then return the final 5xx to the caller.
- 4xx responses: no retry; returned immediately.
- Transport / timeout errors: same delay schedule, then re-raise.
- `asyncio.CancelledError` always propagates without retry.

### Circuit Breaker

Tracks consecutive failures within a 60-second window. After 5 failures the breaker opens for 30 seconds; subsequent calls raise `CircuitOpenError` immediately. After 30 seconds the breaker enters half-open: one request is allowed through. A success closes the breaker and clears the failure list.

| Parameter | Value |
|-----------|-------|
| Failure threshold | 5 |
| Failure window | 60s |
| Open duration | 30s |

### Public Methods

| Method | When to Use |
|--------|-------------|
| `get(path, params=...)` | Read-only API calls |
| `post(path, json=...)` | JSON POST with retry |
| `post_multipart(path, files=..., data=...)` | File upload (no retry) |
| `stream(path, method=...)` | Streaming GET/any verb (no retry) |
| `stream_post(path, json=...)` | Streaming POST with JSON body (no retry) |
| `aclose()` | Explicit shutdown (called on app teardown) |

### Error Types

| Exception | Meaning |
|-----------|---------|
| `NotPairedError` | No bearer token — desktop must pair first |
| `CircuitOpenError` | Too many recent failures; waiting for recovery window |
| `CloudClientError` | Base class for all `CloudClient`-originated errors |

All failures are designed to be non-blocking. Callers should `try/except` and fall back to cached or empty data so the desktop UI remains responsive when the cloud is unreachable.

### Cloud Endpoints Used

| Purpose | Method | Path |
|---------|--------|------|
| LiteLLM model proxy | POST (streaming) | `/api/v1/chat/completions` |
| Usage stats | GET | `/api/v1/usage` |
| Marketplace catalog | GET | `/api/public/marketplace` |
| Install marketplace item | POST | `/api/v1/marketplace/install` |
| Sync push | POST (multipart) | `/api/v1/projects/sync/push` |
| Sync pull | GET | `/api/v1/projects/sync/pull/{project_id}` |
| Sync manifest | GET | `/api/v1/projects/sync/manifest/{project_id}` |

### BYOK (Bring Your Own Key)

When a user configures their own provider API keys, the agent calls the provider directly without a cloud hop. In this mode, `CloudClient` is not involved in model calls. Token is still needed for non-model endpoints (usage, marketplace, sync).

---

## token_store

### Purpose

On-disk and env-var storage for the `tsk_` bearer token. No network I/O.

### Resolution Order

1. `$TESSLATE_CLOUD_TOKEN` env var (Tauri shell injects this; takes precedence).
2. `$TESSLATE_STUDIO_HOME/cache/cloud_token.json` (written by `POST /api/desktop/auth/token`).

### API

| Function | Purpose |
|----------|---------|
| `get_cloud_token() -> str \| None` | Read token (env then file); returns `None` if not paired |
| `set_cloud_token(token: str)` | Atomically write to cache file (tmp + rename, `0600` on POSIX) |
| `clear_cloud_token()` | Remove the on-disk file (env var is unaffected) |
| `is_paired() -> bool` | `True` if any token source is available |

---

## SyncClient

### Purpose

Drives bidirectional project sync between the desktop and cloud. Provides `push()` and `pull()` as the primary entry points; `pack_project()` and `compute_manifest()` are available for inspection or pre-flight checks.

### Entry Points

```python
from app.services.sync_client import push, pull, get_sync_client

# Push local → cloud
result: PushResult = await push(project, db=db_session)
# result.sync_id, result.uploaded_at, result.bytes_uploaded

# Pull cloud → local
result: PullResult = await pull(project_id, project=project_row)
# result.project_id, result.files_written, result.bytes_downloaded
```

### `push(project, db=None) -> PushResult`

1. Fetches the remote manifest (`GET /api/v1/projects/sync/manifest/{id}`).
2. Compares `remote.updated_at` against `project.last_sync_at`. If the cloud is newer, raises `ConflictError` before any upload.
3. Computes a local manifest (SHA-256 per file, deterministic sort order).
4. Zips the filtered project tree via `pack_project()` (streams via `ZipFile`; does not balloon memory).
5. Uploads zip + manifest as multipart to `POST /api/v1/projects/sync/push`.
6. On HTTP 409 from the cloud, raises `ConflictError` with `cloud_updated_at` set.
7. On success, updates `project.last_sync_at` in-memory and, if `db` is provided, commits to the database.

### `pull(project_id, project=None) -> PullResult`

1. Fetches `GET /api/v1/projects/sync/pull/{project_id}` via `CloudClient`.
2. If the response is JSON with `download_url`, downloads the zip from the signed URL using a separate bearer-less `httpx.AsyncClient` (signed S3/R2 URLs must not carry the cloud bearer).
3. If the response body is a direct zip, writes it to a temp file.
4. Atomically replaces the destination directory:
   - Extracts to `{dest}.incoming/`.
   - Renames existing `dest` to `{dest}.replaced/`.
   - Renames `{dest}.incoming/` to `dest`.
   - Deletes `{dest}.replaced/` on success; restores it on any failure.
5. Guards against path traversal in zip entries (`..` or absolute paths raise `SyncError`).

### Conflict Resolution

Conflicts are surfaced as `ConflictError` with a human-readable message and `cloud_updated_at`. The router maps this to a `409` response and surfaces the diff in the UI. There is no automatic merge or overwrite — the user must choose to pull (accepting cloud state) or force-push.

### File Exclusions

The following are excluded from both push and pull manifests:

```
node_modules, __pycache__, .venv, venv, .git, dist, build,
.next, .mypy_cache, .pytest_cache, .ruff_cache, target
.tesslate/logs  (path prefix)
```

`.git` is excluded wholesale — branch metadata can be rebuilt from cloud-side project records.

### Project Root Resolution

`_project_root(project)` prefers `project.source_path` (for imported external projects) over the orchestration-managed root resolved by `services/orchestration/local._get_project_root()`.

### Error Types

| Exception | Meaning |
|-----------|---------|
| `SyncError` | Any sync failure (transport, HTTP error, disk, malformed response) |
| `ConflictError(SyncError)` | Remote manifest is newer; `.cloud_updated_at` carries the remote timestamp |
| `NotPairedError` | Re-raised from `CloudClient`; desktop not paired |
| `CircuitOpenError` | Re-raised from `CloudClient`; cloud temporarily unavailable |

### Result Types

```python
@dataclass(frozen=True)
class PushResult:
    sync_id: str
    uploaded_at: str
    bytes_uploaded: int

@dataclass(frozen=True)
class PullResult:
    project_id: str
    files_written: int
    bytes_downloaded: int
```

### Opt-In Sync

Sync is opt-in per project via `Project.sync_enabled`. Routers should check this flag before calling `push()` or `pull()`.

---

## Testing

```python
# Reset CloudClient singleton between tests
from app.services.cloud_client import reset_cloud_client_for_tests
reset_cloud_client_for_tests()

# Inject a custom transport (respx or httpx.MockTransport)
client = CloudClient(base_url="http://test", transport=my_mock_transport)

# Patch the token store
import app.services.token_store as ts
monkeypatch.setattr(ts, "get_cloud_token", lambda: "tsk_test_key")
```

---

## Related Contexts

| Context | When to Load |
|---------|--------------|
| `docs/orchestrator/services/CLAUDE.md` | Services layer overview |
| `docs/desktop/CLAUDE.md` | Desktop sidecar architecture, pairing flow |
| `docs/orchestrator/routers/CLAUDE.md` | `/api/desktop/` endpoints that call CloudClient |
| `docs/orchestrator/services/worker.md` | Agent execution that may use cloud model proxy |
