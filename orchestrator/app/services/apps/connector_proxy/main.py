"""Standalone FastAPI app for the dedicated ``opensail-runtime`` Deployment.

In K8s production the Connector Proxy runs as its own pod (Phase 4) so a
NetworkPolicy can pin its egress to the OAuth providers it actually
forwards to (Slack, GitHub, Linear, Gmail) and pin its ingress to
compute-pool / ``proj-*`` namespaces.  The orchestrator pod does not
expose the proxy router in this topology — see ``app/main.py`` where the
``include_router`` is gated on ``settings.is_connector_proxy_dedicated``.

Embedded mode (desktop / docker-compose) keeps mounting the same router
on the orchestrator process so non-K8s users don't need a second
process.  Both topologies share the same router code, the same DB
schema, and the same per-pod token verifier.

Entry point::

    python -m app.services.apps.connector_proxy

Binds to ``0.0.0.0:8400``.  Reuses the orchestrator's database session
config (same ``DATABASE_URL``, same ``Base.metadata``, same
``get_db`` Depends).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from ....config import get_settings
from .router import router as connector_proxy_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build the standalone FastAPI app for the dedicated proxy.

    Kept as a factory so tests can construct a fresh instance per
    test (and so the K8s startup probe target is the same code path the
    process serves at runtime).
    """
    settings = get_settings()

    app = FastAPI(
        title="OpenSail Connector Proxy",
        description=(
            "Dedicated proxy that forwards app-pod requests to upstream "
            "OAuth providers without ever handing the user's token to "
            "the app process."
        ),
        version="1.0.0",
        # The Connector Proxy is an internal service — no docs UI is
        # exposed by default.  Operators flipping the deployment mode
        # back to embedded get docs from the orchestrator's main app.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # The router carries its own ``/api/v1/connector-proxy`` prefix so
    # the URL the SDK builds (``OPENSAIL_RUNTIME_URL`` +
    # ``/connectors/{id}/{path}``) lands on the same path whether it
    # hit the embedded mount or the dedicated Deployment.
    app.include_router(connector_proxy_router)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Liveness + readiness probe target.

        Cheap on purpose — kubelet hits this every few seconds.  We do
        NOT touch the database here: the proxy already surfaces a 502
        if its DB session fails on a real call, and we don't want a DB
        hiccup to flap kubelet into killing healthy pods.
        """
        return {
            "status": "ok",
            "mode": settings.connector_proxy_mode,
            "service": "opensail-runtime",
        }

    logger.info(
        "opensail-runtime: started in CONNECTOR_PROXY_MODE=%s",
        settings.connector_proxy_mode,
    )
    return app


# Module-level app for ``uvicorn app.services.apps.connector_proxy.main:app``
# style invocations (alternative to ``python -m``).  Same instance the
# ``__main__`` entrypoint serves.
app = create_app()


__all__ = ["app", "create_app"]
