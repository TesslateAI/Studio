"""Internal secrets endpoint for shared-singleton apps.

Shared-singleton apps run a single Deployment that serves N users; per-
user secrets cannot be env-injected (one container, many users) so the
container fetches the user's specific credential at request time. This
router is the fetch endpoint.

Design
------
* Route: ``GET /internal/secrets/{token}``
* Auth: signed token only — no JWT, no session cookie. The token carries
  ``(user_id, app_instance_id, secret_key, exp)`` HMAC-signed by the
  per-app-instance signing key from
  :mod:`app.services.apps.shared_singleton_router`.
* Network policy: this router lives at ``/internal/*`` so K8s
  NetworkPolicy can restrict ingress to the cluster-internal pod
  network only — external traffic is dropped at the ingress layer.
  See ``docs/infrastructure/kubernetes/CLAUDE.md`` for the policy spec
  (Phase 4 lands the actual NetworkPolicy YAML; until then the
  ``/internal/*`` prefix is the convention this router relies on).
* Response: a JSON dict with ONLY the requested ``secret_key`` value —
  never the full credential bag, never other users' material.

Token shape::

    base64url(
      f"{user_id}:{app_instance_id}:{secret_key}:{exp}:{hmac_hex}"
    )

The HMAC is over ``f"{user_id}:{app_instance_id}:{secret_key}:{exp}"``
keyed by the per-instance signing key. 5-minute default TTL.

Threat model
------------
The token is short-lived and bound to (instance, secret_key) — an
attacker who steals one cannot escalate to other users' credentials or
other secret keys without forging an HMAC. Combined with the
``/internal/*`` NetworkPolicy gate, the worst case is "leak of a single
user's single credential within a 5-minute window" rather than "full
credential bag".
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import McpOAuthConnection, UserMcpConfig
from ..services.apps.shared_singleton_router import _derive_signing_key
from ..services.channels.registry import decrypt_credentials

logger = logging.getLogger(__name__)


# Token TTL — see module docstring. Short by design.
INTERNAL_SECRET_TOKEN_TTL_SECONDS = 300

# Same skew tolerance as the shared-singleton header — keep both surfaces
# tolerant of the same NTP drift envelope.
CLOCK_SKEW_TOLERANCE_SECONDS = 30


router = APIRouter(prefix="/internal", tags=["internal:secrets"])


def mint_secret_token(
    *,
    user_id: UUID,
    app_instance_id: UUID,
    secret_key: str,
    ttl_seconds: int = INTERNAL_SECRET_TOKEN_TTL_SECONDS,
    secret_override: str | bytes | None = None,
) -> str:
    """Create a token the app pod can present at GET /internal/secrets/.

    Production callers leave ``secret_override`` None and the function
    pulls from ``settings.secret_key``. Tests pass an override so they
    don't need to monkey-patch the global.
    """
    if secret_override is None:
        from ..config import get_settings

        secret_override = get_settings().secret_key

    signing_key = _derive_signing_key(
        app_instance_id=app_instance_id, fallback_secret=secret_override
    )
    exp = int(time.time()) + max(1, ttl_seconds)
    payload = f"{user_id}:{app_instance_id}:{secret_key}:{exp}"
    sig = hmac.new(
        signing_key, payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    raw = f"{payload}:{sig}".encode("utf-8")
    # base64url so the token is URL-safe — the route encodes the token
    # in the path segment. Strip padding so we never have to worry about
    # FastAPI URL-decoding a `=` mid-route.
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_token(
    token: str,
    *,
    secret_override: str | bytes | None = None,
    now_seconds: int | None = None,
) -> tuple[UUID, UUID, str]:
    """Verify the token and return ``(user_id, app_instance_id, secret_key)``.

    Raises HTTPException(401) on any failure mode — never reflects the
    decryption error so an attacker probing for valid tokens gets a flat
    "unauthorized" with no oracle for the underlying failure.
    """
    if secret_override is None:
        from ..config import get_settings

        secret_override = get_settings().secret_key

    try:
        # base64url with padding restored.
        padding = b"=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token.encode("ascii") + padding)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        logger.debug("internal_secrets: token b64 decode failed: %r", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        ) from None

    parts = raw.decode("utf-8", errors="replace").split(":")
    if len(parts) != 5:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        )
    user_id_str, instance_str, secret_key, exp_str, sig_hex = parts

    try:
        user_id = UUID(user_id_str)
        app_instance_id = UUID(instance_str)
        exp = int(exp_str)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        ) from None

    now = now_seconds if now_seconds is not None else int(time.time())
    if exp + CLOCK_SKEW_TOLERANCE_SECONDS < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token expired",
        )

    signing_key = _derive_signing_key(
        app_instance_id=app_instance_id, fallback_secret=secret_override
    )
    expected = hmac.new(
        signing_key,
        f"{user_id}:{app_instance_id}:{secret_key}:{exp}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, sig_hex):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="signature mismatch",
        )

    return user_id, app_instance_id, secret_key


async def _resolve_secret(
    db: AsyncSession,
    *,
    user_id: UUID,
    app_instance_id: UUID,  # noqa: ARG001 — reserved for per-app credential mappings
    secret_key: str,
) -> Any:
    """Fetch the user's credential value for ``secret_key``.

    Resolution path:

    1. Walk the user's ``user_mcp_configs.credentials`` (Fernet-decrypted)
       and return the matching key — UserMcpConfig is the canonical
       store for per-user MCP/API credentials today.
    2. If no MCP config carries the key, walk
       ``McpOAuthConnection.tokens_encrypted`` for ``access_token`` /
       ``refresh_token`` lookups (named secret keys like
       ``slack_oauth_access_token``).
    3. Otherwise raise 404 — the app pod treats a missing secret as a
       configuration error.

    The function returns a JSON-serializable value (string for tokens,
    dict for nested OAuth payloads) so the FastAPI response can wrap it
    in ``{"value": ...}`` directly.
    """
    # 1) UserMcpConfig credentials.
    rows = (
        await db.execute(
            select(UserMcpConfig)
            .where(UserMcpConfig.user_id == user_id)
            .where(UserMcpConfig.is_active.is_(True))
        )
    ).scalars().all()
    for row in rows:
        if not row.credentials:
            continue
        try:
            payload = decrypt_credentials(row.credentials)
        except Exception:  # noqa: BLE001 — corrupt rows are skipped
            continue
        if not isinstance(payload, dict):
            continue
        if secret_key in payload:
            return payload[secret_key]

    # 2) OAuth-derived secrets.
    oauth_rows = (
        await db.execute(
            select(McpOAuthConnection).join(
                UserMcpConfig,
                UserMcpConfig.id == McpOAuthConnection.user_mcp_config_id,
            ).where(UserMcpConfig.user_id == user_id)
        )
    ).scalars().all()
    for oauth in oauth_rows:
        if not oauth.tokens_encrypted:
            continue
        try:
            tokens = decrypt_credentials(oauth.tokens_encrypted)
        except Exception:  # noqa: BLE001 — corrupt rows skipped
            continue
        if not isinstance(tokens, dict):
            continue
        if secret_key in tokens:
            return tokens[secret_key]

    return None


@router.get("/secrets/{token}")
async def get_secret(token: str) -> dict[str, Any]:
    """Return the requested secret value for the user encoded in ``token``.

    Auth is the signed token alone — no JWT, no session cookie. The
    response is ``{"value": <str|dict>}`` on success or a 401/404 on any
    failure. We never echo the token or the full credential bag.

    Open the session inline (not via ``Depends(get_db)``) because this
    router is mounted under ``/internal/*`` and we want it to remain
    importable from worker contexts without dragging the FastAPI app's
    full DI graph.
    """
    user_id, app_instance_id, secret_key = _decode_token(token)

    async with AsyncSessionLocal() as db:
        value = await _resolve_secret(
            db,
            user_id=user_id,
            app_instance_id=app_instance_id,
            secret_key=secret_key,
        )

    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"secret {secret_key!r} not found for user",
        )

    return {"value": value}


__all__ = [
    "CLOCK_SKEW_TOLERANCE_SECONDS",
    "INTERNAL_SECRET_TOKEN_TTL_SECONDS",
    "mint_secret_token",
    "router",
]
