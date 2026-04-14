"""
Public API routers — external surface authenticated via `tsk_` ExternalAPIKey tokens.

All routers in this package are consumed by external clients (desktop app, SDK, on-prem).
Internal/session-auth routers live in `orchestrator/app/routers/` one level up.

URL prefix convention:
- `/api/public/*` — read-only public catalog (marketplace browse).
- `/api/v1/*` — authenticated public API (everything else).

See `CLAUDE.md` in this directory for conventions and how to add a new public router.
"""

from __future__ import annotations

from .agents import router as agents_router
from .k8s_projects import router as k8s_projects_router
from .marketplace import router as marketplace_router
from .marketplace_install import router as marketplace_install_router
from .models import router as models_router
from .projects_sync import router as projects_sync_router

public_routers = [
    marketplace_router,
    models_router,
    agents_router,
    marketplace_install_router,
    projects_sync_router,
    k8s_projects_router,
]

__all__ = ["public_routers"]
