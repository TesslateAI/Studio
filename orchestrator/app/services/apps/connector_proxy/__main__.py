"""``python -m app.services.apps.connector_proxy`` entrypoint.

Boots the dedicated ``opensail-runtime`` proxy on ``0.0.0.0:8400`` using
uvicorn.  This is what the K8s Deployment runs as its container command.

The bind host / port are intentionally fixed to match the Service
contract documented in ``k8s/base/opensail-runtime/service.yaml``.
Operators who need to override (local debug, smoke tests) can still
``uvicorn app.services.apps.connector_proxy.main:app --port ...``
directly — this module just gives the K8s manifest a single canonical
command to call.
"""

from __future__ import annotations

import logging
import os

import uvicorn

from ....config import get_settings


def main() -> None:
    settings = get_settings()
    log_level = (settings.log_level or "INFO").lower()

    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Honor explicit overrides for dev / debug, but production K8s
    # manifests should leave these unset so the canonical contract
    # ``opensail-runtime:8400`` holds.
    host = os.environ.get("OPENSAIL_RUNTIME_HOST", "0.0.0.0")  # noqa: S104
    port = int(os.environ.get("OPENSAIL_RUNTIME_PORT", "8400"))

    uvicorn.run(
        "app.services.apps.connector_proxy.main:app",
        host=host,
        port=port,
        log_level=log_level,
        # Single worker; the proxy is stateless and we scale via
        # Deployment replicas, not in-process workers.  Reload off
        # because this is a production entrypoint — devs use the
        # orchestrator's embedded mount for hot reload.
        workers=1,
        reload=False,
    )


if __name__ == "__main__":
    main()
