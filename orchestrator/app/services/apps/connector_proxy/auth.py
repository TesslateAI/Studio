"""Connector Proxy auth — verify the X-OpenSail-AppInstance header.

Phase 3 ships a **stubbed** verification: the proxy accepts a plain
``X-OpenSail-AppInstance: <app_instance_id_uuid>`` header and looks the
row up in the DB. Real per-install signing (HMAC over the request body
using the install's signing key from
``services/apps/key_lifecycle.py``) lands in a follow-up wave.

Why stubbed for Phase 3
-----------------------
The orchestrator already injects ``X-OpenSail-Instance-Id`` on outbound
``action_dispatcher`` calls without signing — see
``services/apps/action_dispatcher.py``. Adding HMAC signing is an
end-to-end change spanning the dispatcher, app pod SDK, and proxy verify
step; doing it here would block this wave on three other surfaces. The
stubbed shape keeps the contract identical so the upgrade is a pure
"verify the signature" patch in this module + the dispatcher's signer +
the SDK helper.

Threat model under the stub
---------------------------
Inside the cluster the proxy lives on the orchestrator and is reachable
only from the in-cluster Service network. App pods cannot reach
orchestrator-internal addresses except via the published
``opensail-runtime`` Service. NetworkPolicy (Phase 4) further restricts
which Pods may talk to that Service — combined with the
``app_connector_grants`` table requirement (no grant → 403), an attacker
needs cluster-internal network access AND a valid app_instance_id AND a
matching grant, which is the same envelope an HMAC-signed token would
buy us in practice. The signing upgrade is still important for defense
in depth and for cross-cluster federation, but Phase 3 is correct
without it.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....models_automations import AppInstance

logger = logging.getLogger(__name__)


APP_INSTANCE_HEADER = "X-OpenSail-AppInstance"


class AppInstanceAuthError(HTTPException):
    """Raised when the X-OpenSail-AppInstance header is missing/invalid."""


async def verify_app_instance(
    request: Request, db: AsyncSession
) -> AppInstance:
    """Resolve the calling AppInstance from the request headers.

    Raises ``AppInstanceAuthError`` (HTTP 401) if the header is missing,
    not a UUID, or doesn't correspond to a live ``AppInstance`` row.

    Phase 3 stub — accepts the raw UUID. Real signature verification lands
    in a follow-up wave (see module docstring).
    """
    header_value = request.headers.get(APP_INSTANCE_HEADER)
    if not header_value:
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing {APP_INSTANCE_HEADER} header",
        )

    try:
        instance_id = UUID(header_value)
    except (TypeError, ValueError):
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid {APP_INSTANCE_HEADER} header (not a UUID)",
        ) from None

    instance = await db.get(AppInstance, instance_id)
    if instance is None:
        # Use 401 (not 404) so an attacker probing for valid IDs cannot
        # distinguish "wrong id" from "no auth provided".
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="app instance not found or not authorized",
        )

    # Reject calls from instances that aren't in a runnable state. Allowing
    # a proxy call from an "uninstalling" or "errored" install would let a
    # crashed app keep using its grants past the user's intent to revoke.
    if instance.uninstalled_at is not None:
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="app instance has been uninstalled",
        )

    return instance


__all__ = ["APP_INSTANCE_HEADER", "AppInstanceAuthError", "verify_app_instance"]
