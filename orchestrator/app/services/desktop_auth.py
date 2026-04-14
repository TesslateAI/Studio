"""Loopback auth shim for the desktop sidecar.

The desktop tray polls endpoints (``/runtime-probe``, ``/tray-state``)
before the user has logged in — the Tauri host only holds the sidecar
loopback-isolation bearer emitted on stdout at spawn time, not a session
cookie. That bearer is strictly secret to the local process pair, so
treating it as "trust this request" is safe on the desktop sidecar.

``desktop_loopback_or_session`` is a FastAPI dependency that accepts
either:

1. A valid session via ``current_active_user`` (cloud + desktop-after-login), OR
2. An ``Authorization: Bearer <TESSLATE_DESKTOP_BEARER>`` header matching
   the sidecar bearer (desktop loopback only — this env var is set by
   ``desktop/sidecar/entrypoint.py`` right before uvicorn starts and
   NEVER set in cloud deployments).

Returns a real ``User`` for the session case and a synthetic desktop
pseudo-user for the bearer case. Callers that just need to gate access
don't have to care which branch fired.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import Depends, Header, HTTPException, status

from ..users import current_optional_user


class _LoopbackUser:
    """Minimal duck-typed User for desktop loopback requests.

    Has the handful of attributes routers read off the user object
    (``id``, ``email``, ``is_active``). Not a SQLAlchemy row — routers
    that try to persist this will fail loudly, which is the right
    behaviour for a synthetic principal.
    """

    id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    email = "desktop-loopback@tesslate.local"
    is_active = True
    is_superuser = False
    is_verified = True


def _sidecar_bearer() -> str | None:
    """Read the per-launch bearer the sidecar entrypoint set in env.

    Returns ``None`` in non-desktop deployments so the bearer branch
    never matches.
    """
    return os.environ.get("TESSLATE_DESKTOP_BEARER") or None


async def desktop_loopback_or_session(
    authorization: str | None = Header(default=None),
    session_user: Any = Depends(current_optional_user),
) -> Any:
    """Accept session auth *or* the sidecar loopback bearer.

    ``current_optional_user`` returns ``None`` when no session cookie is
    present (instead of 401-ing), which lets us try the bearer branch
    afterwards. Either path yields a principal; if both miss we 401.
    """
    expected = _sidecar_bearer()
    if authorization and expected:
        _, _, token = authorization.partition(" ")
        if token.strip() == expected:
            return _LoopbackUser()

    if session_user is not None:
        return session_user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


__all__ = ["desktop_loopback_or_session"]
