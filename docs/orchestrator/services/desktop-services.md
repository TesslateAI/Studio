# Desktop Sidecar Services

Desktop-mode-specific services that ship inside the PyInstaller-frozen sidecar. Most make HTTP calls to the cloud orchestrator via `cloud_client.py`, or operate purely on local resources.

## When to load

Load this doc when:
- Working on the Tauri-mode sidecar.
- Debugging local-cloud auth, sync, handoff, or paid install flows.
- Detecting which runtimes a user has available (local subprocess, Docker, cloud K8s).

## File map

| File | Purpose |
|------|---------|
| `desktop_auth.py` | Loopback auth shim: handles early polls (`/runtime-probe`, `/tray-state`) before the user has logged in, using the sidecar loopback bearer emitted on stdout. |
| `desktop_paths.py` | Resolves `$OPENSAIL_HOME` and derives per-concern subdirectories (projects, cache, marketplace, logs, SQLite DB). |
| `runtime_probe.py` | Non-blocking checks for available runtimes (local, Docker daemon, cloud K8s via paired key). Drives the tray "where can I run this?" UI. |
| `token_store.py` | Persists the long-lived `tsk_` API key minted by cloud `POST /api/desktop/pair/complete`. Tauri shell keeps its own copy in Stronghold; this file is the sidecar's fallback. |
| `cloud_client.py` | httpx wrapper for all outbound desktop-to-cloud calls. See [cloud-client.md](./cloud-client.md). |
| `sync_client.py` | Bidirectional project sync: bundle local working tree, upload, merge, download remote changes. Calls `public/sync_service.py` on the cloud. |
| `handoff_client.py` | Serializes an `AgentTask` into a transport bundle so the cloud (or another desktop) can resume it. Pure-Python contract; see `public/handoff_service.py` for the server side. |
| `marketplace_installer.py` | Cloud-mediated install flow for marketplace items (agent, skill, base, theme). Resolves item, handles paid-item entitlement, downloads bundle, places files locally. |
| `tsinit_client.py` | Async WebSocket client for the `tsinit` service's `/v1/run` endpoint. Uses the K8s remotecommand channel-multiplexed binary protocol to stream stdin/stdout/stderr and exit codes. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| `routers/desktop/auth.py` | `token_store`, `desktop_auth` |
| `routers/desktop/tray.py` | `runtime_probe` |
| `routers/desktop/projects.py`, `routers/sync.py` | `sync_client` (client side), `public/sync_service.py` (server side) |
| `routers/desktop/handoff.py`, `routers/desktop/sessions.py` | `handoff_client`, `public/handoff_service.py` |
| `routers/marketplace_local.py` | `marketplace_installer`, `cloud_client` |
| Worker `execute_agent_task` (desktop mode) | `tsinit_client` when runtime is `k8s` remote |

## Related

- [../../desktop/CLAUDE.md](../../desktop/CLAUDE.md): Tauri shell context.
- [cloud-client.md](./cloud-client.md): HTTP client wrapper used by most of these modules.
- [public-services.md](./public-services.md): cloud-side counterparts to sync, handoff, marketplace-install.
- [project-setup.md](./project-setup.md): `marketplace_installer` may trigger a local setup pipeline for new projects.
