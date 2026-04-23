# Desktop Routers

Desktop sidecar routes consumed by the Tauri shell. Split across the `desktop/` package (session-auth, tray-oriented) and two standalone files (`desktop_pair.py`, `marketplace_local.py`).

For the desktop client architecture, see [../../desktop/CLAUDE.md](../../desktop/CLAUDE.md).

## File Index

| File | Prefix | Purpose |
|------|--------|---------|
| `desktop/__init__.py` | `/api/desktop` | Assembles the desktop router and includes all submodules. |
| `desktop/tray.py` | `/api/desktop` | Runtime probe + tray state feed. |
| `desktop/auth.py` | `/api/desktop` | Cloud pairing auth shim (status / store / clear token). |
| `desktop/tickets.py` | `/api/desktop` | Agent task tickets (list + approve). |
| `desktop/directories.py` | `/api/desktop` | Connected directories CRUD + git-root detection. |
| `desktop/sessions.py` | `/api/desktop` | Agent sessions feed + per-ticket diff. |
| `desktop/projects.py` | `/api/desktop` | Import folder, sync push/pull/status. |
| `desktop/handoff.py` | `/api/desktop` | Handoff push/pull between local and cloud agents. |
| `desktop/_helpers.py` | (internal) | Shared helpers (`_safe_probe`, `_canonical_path`, `_detect_git_root`, `_load_project`, `_map_sync_error`, serializers). |
| `desktop_pair.py` | `/api/desktop` + `/api/v1/desktop` | Pairing mint (`session_router`) and revoke (`public_router`). |
| `marketplace_local.py` | `/api/desktop/marketplace` | Local + cloud dual-source marketplace for the desktop shell. |

## Endpoints

### desktop/tray.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/runtime-probe` | session | Probe local/docker/k8s-remote runtimes (non-blocking; falls back to a well-formed payload on any error). |
| GET | `/tray-state` | session | Tray badge feed (pending tickets, agent activity, sync state). |

### desktop/auth.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/local-auth` | session | Sidecar self-check (is the sidecar reachable and authenticated). |
| GET | `/auth/status` | session | Returns `{paired, cloud_url}`. Never returns the token itself. |
| POST | `/auth/token` | session | Persist a bearer minted by the cloud `/api/desktop/pair/complete`. |
| DELETE | `/auth/token` | session | Clear the stored token (desktop logout). |

### desktop/tickets.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/agents/tickets` | session | List agent tickets awaiting approval/action. |
| POST | `/agents/{ticket_id}/approve` | session | Approve or act on a ticket. |

### desktop/directories.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/directories` | session | Connected directories for the desktop workspace. |
| POST | `/directories` | session | Register a directory (auto-detects runtime + git root). |
| DELETE | `/directories/{directory_id}` | session | Disconnect (204). |

### desktop/sessions.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/agents/sessions` | session | Local agent session feed. |
| GET | `/agents/{ticket_id}/diff` | session | Diff for a specific ticket. |

### desktop/projects.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/import` | session | Import a local folder as an OpenSail project. |
| POST | `/projects/{project_id}/sync/push` | session | Push local project state to cloud. |
| POST | `/projects/{project_id}/sync/pull` | session | Pull cloud project state locally. |
| GET | `/projects/{project_id}/sync/status` | session | Sync status. |

### desktop/handoff.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/agents/{ticket_id}/handoff/push` | session | Send local agent state to cloud. |
| POST | `/agents/handoff/pull` | session | Pull cloud agent handoff. |

### desktop_pair.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/desktop/pair/complete` (session_router) | session | Mint a desktop pairing bearer from a cloud session. |
| POST | `/api/v1/desktop/pair/revoke` (public_router) | tsk key | Revoke a paired bearer (desktop-initiated logout). |

### marketplace_local.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/items` | session | List installed items (`source: "local"`) merged with cloud catalog (`source: "cloud"`) when paired. 1h cached with stale-while-revalidate. |
| POST | `/install` | session | Install an item (201). 401 on not-paired, 502 on cloud circuit-open, 409 if already installed. |
| DELETE | `/install/{kind}/{slug}` | session | Uninstall (204). |

## Auth

- Sidecar routes use `current_active_user` backed by the local desktop session.
- `desktop_pair.session_router` requires the cloud session; `desktop_pair.public_router` requires a `tsk_` key.
- Cloud-reaching endpoints must degrade gracefully: probes/cloud failures return a well-formed payload rather than 5xx.

## Related

- Desktop architecture: [../../desktop/CLAUDE.md](../../desktop/CLAUDE.md).
- Runtime probes: [../../desktop/runtimes.md](../../desktop/runtimes.md).
- Sync: [../../desktop/sync.md](../../desktop/sync.md).
- Cloud client: [../services/cloud-client.md](../services/cloud-client.md).
