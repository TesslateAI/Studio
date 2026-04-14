# routers/desktop/

Desktop tray/shell router package. `__init__.py` builds the single
`APIRouter(prefix="/api/desktop", tags=["desktop"])` that `app/main.py`
includes, and each submodule contributes its endpoints via
`router.include_router(...)`. Submodules have no prefix of their own.

## Layout

| Submodule       | Endpoints                                                                                  |
|-----------------|--------------------------------------------------------------------------------------------|
| `tray.py`       | `GET /runtime-probe`, `GET /tray-state`                                                    |
| `auth.py`       | `GET /auth/status`, `POST /auth/token`, `DELETE /auth/token`                               |
| `tickets.py`    | `GET /agents/tickets`, `POST /agents/{ticket_id}/approve`                                  |
| `directories.py`| `GET /directories`, `POST /directories`, `DELETE /directories/{directory_id}`              |
| `sessions.py`   | `GET /agents/sessions`, `GET /agents/{ticket_id}/diff`                                     |
| `projects.py`   | `POST /import`, `POST /projects/{id}/sync/push`, `POST /projects/{id}/sync/pull`, `GET /projects/{id}/sync/status` |
| `handoff.py`    | `POST /agents/{ticket_id}/handoff/push`, `POST /agents/handoff/pull`                       |
| `_helpers.py`   | shared: `_safe_probe`, `_collect_runtimes`, `_canonical_path`, `_detect_git_root`, `_load_project`, `_map_sync_error`, ticket/directory/session serializers |

## Re-exports

`__init__.py` re-exports `router` plus every helper, serializer, and request
body model so legacy `from app.routers import desktop; desktop.X` access
patterns keep working. Add new re-exports to `__all__` when a caller reaches
in via attribute access.

## Non-blocking contract

Probes and cloud calls that fail unexpectedly must degrade to a well-formed
payload. The desktop shell polls these endpoints and must never observe a
5xx caused by an unreachable probe or cloud.
