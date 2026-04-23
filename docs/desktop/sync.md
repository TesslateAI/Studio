# Desktop ↔ cloud project sync

Bidirectional project-tree sync between the desktop shell and the cloud
companion. Service: `/orchestrator/app/services/sync_client.py`. Router:
`/orchestrator/app/routers/desktop/projects.py` (`sync_push`, `sync_pull`, `sync_status`).

## Project root resolution

`_project_root(project)` prefers `project.source_path` (set for imported
projects) before falling back to `local._get_project_root(project)`. For
non-imported desktop projects this resolves to
`$OPENSAIL_HOME/projects/{slug}-{id}`.

## Pack exclusions

Hard-coded in `sync_client.py`:

```python
EXCLUDED_DIRS = frozenset({
    "node_modules", "__pycache__", ".venv", "venv", ".git",
    "dist", "build", ".next", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "target",
})
EXCLUDED_PATH_PREFIXES = (".tesslate/logs",)
```

`.git` is excluded wholesale — branch state rebuilds from cloud-side
metadata. `_iter_included_files` walks the tree in sorted order so manifests
are deterministic.

## Manifest shape

`compute_manifest(project)`:

```json
{
  "project_id": "<uuid>",
  "files": [{"path": "src/app.py", "sha256": "…", "size": 1234}, ...],
  "total_size": 123456,
  "created_at": "2026-04-14T12:00:00+00:00"
}
```

SHA-256 is streamed in 64 KiB chunks; walk order is stable. `pack_project`
produces a deterministic `ZIP_DEFLATED` archive with matching arc-names.

## Push: `POST /api/desktop/projects/{project_id}/sync/push`

`sync_client.push(project, db=...)`:

1. **Pre-flight** — `GET /api/v1/projects/sync/manifest/{project_id}` via
   `CloudClient`. `404` → no cloud history (fine). Any other 4xx/5xx →
   `SyncError`.
2. **Conflict check** — if the remote `updated_at` is newer than the local
   `Project.last_sync_at` (or a remote manifest exists and local has never
   pushed), raise `ConflictError(message, cloud_updated_at=…)`.
3. **Upload** — multipart POST to `/api/v1/projects/sync/push` with
   `zip_file` + `project_id` + serialized manifest, using
   `client._client` + `client._build_headers()` (bypassing the JSON-only
   retry wrapper while still injecting the bearer and respecting the breaker).
4. **Commit** — writes `Project.last_sync_at = now` (in-memory + DB when a
   session is provided).

Success response: `{sync_id, uploaded_at, bytes_uploaded}`.

## Pull: `POST /api/desktop/projects/{project_id}/sync/pull`

`sync_client.pull(project_id, project=…)`:

1. Request `GET /api/v1/projects/sync/pull/{project_id}` with bearer.
2. If response is `application/json`, follow `download_url` (or `url`) via a
   **bearer-less** `httpx.AsyncClient` (signed cross-origin URLs must not
   carry the cloud bearer). Otherwise the body is the zip itself.
3. **Atomic extract** via `_extract_atomic(zip_path, dest)`:
   - Unzip into `dest.with_suffix('.incoming')`.
   - Zip-slip guard: reject absolute paths or `..` entries (`SyncError`).
   - If `dest` exists, move it to `dest.with_suffix('.replaced')`.
   - Rename incoming → dest. On failure, rollback restores `.replaced` and
     removes `.incoming`.
   - On success, `.replaced` is deleted.

Success response: `{project_id, files_written, bytes_downloaded}`.

## Status: `GET /api/desktop/projects/{project_id}/sync/status`

Non-blocking. Computes `in_sync` by comparing the local `Project.last_sync_at`
against the remote manifest's `updated_at`. If the cloud is unreachable
(`NotPairedError`, `CircuitOpenError`, `SyncError`) the endpoint sets
`degraded: true` and returns the locally-known fields only.

Response:

```json
{
  "last_sync_at": "2026-04-14T…" | null,
  "cloud_updated_at": "2026-04-14T…" | null,
  "in_sync": true,
  "degraded": false
}
```

## Error map (all three endpoints)

`_map_sync_error()` in `/orchestrator/app/routers/desktop/projects.py`:

| Caught exception                  | HTTP | Body                                                    |
| --------------------------------- | ---- | ------------------------------------------------------- |
| `NotPairedError`                  | 401  | `cloud not paired`                                      |
| `sync_client.ConflictError`       | 409  | `{message, cloud_updated_at}`                           |
| `CircuitOpenError`                | 502  | `cloud unavailable: …`                                  |
| `sync_client.SyncError` (transport / HTTP ≥ 400 / malformed) | 502  | `<str(exc)>`                          |
| anything else                     | 500  | `unexpected sync error`                                 |

Project scope: `_load_project` enforces `owner_id == user.id` (single-user
desktop invariant) and returns 404 otherwise.

## Related

- `/docs/desktop/cloud.md` — bearer injection and breaker behavior consumed here.
- `/docs/desktop/import.md` — `source_path` makes pack/pull operate on the adopted dir.
