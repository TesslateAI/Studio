# tests/sync/

Unit tests for `app.services.sync_client` and the
`/api/desktop/projects/{id}/sync/*` router endpoints.

All tests are offline: respx mocks the cloud surface (`/api/v1/projects/sync/
push|pull|manifest/{id}`) so they never touch the network. Fixtures mirror
`tests/marketplace/` — a `opensail_home` tmp dir, a `paired` token fixture,
and a `cloud_singleton` that rebinds `get_cloud_client` to a respx-backed
client at `https://cloud.test`.

Coverage:
- `test_sync_client.py` — pack excludes node_modules / .venv / .git; manifest
  sha256 is stable across runs; push happy-path updates `last_sync_at`;
  push raises `ConflictError` when remote is newer; pull extracts atomically;
  pull failure leaves the project dir intact (rollback via `.replaced/`).
- `test_sync_router.py` — push / pull / status endpoints via TestClient with
  error mapping (401 unpaired, 409 conflict, 502 circuit-open / transport).
