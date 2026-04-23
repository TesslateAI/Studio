# Public Services

**Directory**: `orchestrator/app/services/public/`

Business logic for routers that expose surfaces consumed by the desktop shell and other external clients. Keeps the public routers thin.

## When to load

Load this doc when:
- Adding a new public router.
- Modifying local-cloud sync conflict detection.
- Changing agent handoff bundle shape (desktop-cloud contract).
- Gating paid marketplace installs.

## File map

| File | Purpose |
|------|---------|
| `__init__.py` | Package docstring; re-exports the three service modules. |
| `sync_service.py` | Project sync storage + conflict detection. Client uploads zip + manifest; service compares against server tree and returns merge instructions. |
| `handoff_service.py` | Serialize `AgentTask` state for local-cloud moves. Defines the stable bundle contract between cloud and desktop clients. |
| `marketplace_install_service.py` | Resolves marketplace items (agent / skill / base / theme), enforces paid-item entitlement, records installs, returns download URLs. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| `routers/desktop/sessions.py`, `routers/desktop/handoff.py` | `handoff_service` |
| `routers/sync.py`, `routers/desktop/projects.py` | `sync_service` |
| `routers/marketplace_local.py`, `routers/marketplace_apps.py` | `marketplace_install_service` |

## Related

- [desktop-services.md](./desktop-services.md): desktop-side clients (`sync_client`, `handoff_client`, `marketplace_installer`) call these services through HTTP.
- [cloud-client.md](./cloud-client.md): HTTP shape used by desktop to call these endpoints.
