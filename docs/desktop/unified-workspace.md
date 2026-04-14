# Unified desktop workspace

The desktop shell surfaces agent activity across many on-disk working
directories, not just Studio-managed projects. `Directory` rows model those
adopted paths; `AgentTask` rows join them via a many-to-many association so a
single session can span multiple trees.

## Directory CRUD

Router: `/orchestrator/app/routers/desktop/ (tickets.py, sessions.py, directories.py, handoff.py)`.

| Method   | Path                                 | Status | Body / Response |
| -------- | ------------------------------------ | ------ | --------------- |
| `GET`    | `/api/desktop/directories`           | 200    | `{directories: [_serialize_directory(d), ...]}` |
| `POST`   | `/api/desktop/directories`           | 200    | `DirectoryCreate` → serialized `Directory` |
| `DELETE` | `/api/desktop/directories/{dir_id}`  | 204    | — (404 if not owned by user) |

`DirectoryCreate`:

```json
{"path": "/home/me/code/thing", "runtime": "local|docker|k8s|null", "project_id": "<uuid>|null"}
```

Serialized row:

```json
{
  "id": "<uuid>",
  "path": "/canonical/path",
  "runtime": "local|...|null",
  "project_id": "<uuid>|null",
  "git_root": "/canonical/git-root|null",
  "last_opened_at": "...",
  "created_at": "..."
}
```

### Dedup via canonical path

`_canonical_path(raw)` runs `os.path.expanduser` then `Path(...).resolve(strict=False)`
(falls back to `os.path.abspath`) and strips trailing separators. All lookups +
uniqueness keys use this canonical string.

POST semantics:

1. Query `(user_id, path == canonical)`. If a row exists, `last_opened_at` is
   bumped, `runtime` / `project_id` updated when supplied, and the existing
   row is returned (idempotent upsert).
2. Otherwise insert. On `IntegrityError` (race), the handler rolls back, re-selects
   the winning row, and returns it.

### Git-root detection

`_detect_git_root(path)` walks from the canonical path up through its parents
and returns the first ancestor containing a `.git` entry — or `None`. This is
persisted on `Directory.git_root` so the UI can group sessions by repo without
re-walking.

## AgentTask ↔ Directory join

`AgentTask.directories` is a many-to-many via an association table. The
unified sessions endpoint uses `selectinload(AgentTask.directories)` and
`AgentTask.directories.any(...)` filters — see `/docs/desktop/agents.md` for
the endpoint + filter matrix.

`_serialize_session(ticket)` returns the same fields as `_serialize_ticket`
plus `source: "local"` and `directories: [{id, path}]`.

## Handoff bundle

File: `/orchestrator/app/services/handoff_client.py`.

Pure serialization — no HTTP. `HandoffBundle` is a frozen dataclass:

```python
@dataclass(frozen=True)
class HandoffBundle:
    ticket_id: str
    title: str | None
    goal_ancestry: list[str]
    trajectory_events: list[dict[str, Any]] = []
    diff: str = ""
    skill_bindings: list[dict[str, Any]] = []
```

### `push(session, *, ticket_id)`

Loads the `AgentTask` (raises `LookupError` if missing) and returns a
`HandoffBundle` with empty trajectory/diff/skill-binding placeholders. Real
trajectory + git-diff wiring is deferred; the shape is stable so callers can
start integrating now.

### `pull(session, *, cloud_task_id, bundle, project_id)`

Allocates a fresh local ticket via `create_ticket()`, preserving
`bundle.title` and `bundle.goal_ancestry` and appending `f"cloud:{cloud_task_id}"`
to the ancestry (dedup-guarded) so local tickets keep provenance of the
remote origin. Commits and returns the new `AgentTask`.

### `upload_to_cloud(bundle) -> cloud_task_id`

Posts a serialized `HandoffBundle` to `POST /api/v1/agents/handoff/upload`
through `CloudClient` (bearer injected by `token_store`). Returns the opaque
`cloud_task_id` the bundle is addressable by on the cloud side.

### `download_from_cloud(cloud_task_id) -> HandoffBundle`

Fetches a previously uploaded bundle via
`GET /api/v1/agents/handoff/download/{id}` and rehydrates the frozen
dataclass.

`NotPairedError` / `CircuitOpenError` propagate unchanged; routers map them
to 401 / 502.

## Desktop router endpoints

| Method | Path | Body | Success | Errors |
|---|---|---|---|---|
| POST | `/api/desktop/agents/{ticket_id}/handoff/push` | — | `{ticket_id, cloud_task_id}` | 404 missing · 401 unpaired · 502 cloud |
| POST | `/api/desktop/agents/handoff/pull` | `{cloud_task_id, project_id}` | `{ticket_id, ref_id, title, cloud_task_id}` | 401 unpaired · 502 cloud |

Push composes `push() → upload_to_cloud()`. Pull composes
`download_from_cloud() → pull()`. Project-level file-tree sync is a separate
flow — see `/docs/desktop/sync.md`.

## `tesslate-agent` bridge

File: `/orchestrator/app/services/tesslate_agent_bridge.py`.

`TesslateAgentBridge` is the single seam between the orchestrator's in-tree
runner and the `packages/tesslate-agent` submodule. Routers and services
should import `TesslateAgentBridge` from here rather than the submodule
directly so the eventual runner cutover is a one-file change.
`BridgeContext(project_id, user_id, goal_ancestry, extra)` is the minimal
invocation context; nothing else changes today.

## Open-in-IDE (planned)

A Rust-side Tauri command (e.g. `open_in_ide`) will take a `Directory.path`
and spawn the user's configured editor. Not yet implemented — the backend
contract exists (`Directory.path` is always canonical + user-scoped), but the
Tauri command is pending.

## Related

- `/docs/desktop/agents.md` — ticket allocator, budgets, approvals, sessions filter.
- `/docs/desktop/import.md` — imported projects carry `source_path`; `Directory` rows co-exist.
- `/docs/desktop/sync.md` — project-tree sync vs. ticket handoff.
