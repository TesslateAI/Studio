"""Connector Proxy auth — verify the X-OpenSail-AppInstance header.

The header is a signed token of the form::

    <app_instance_id>.<nonce>.<hmac_sha256_hex>

* ``app_instance_id`` — UUID string identifying the calling install.
* ``nonce`` — 16+ character URL-safe random string minted at install
  time. Pinned to the K8s Secret backing the per-pod token; rotated when
  the install is reset/rotated.
* ``hmac_sha256_hex`` — HMAC-SHA256 over ``f"{instance_id}.{nonce}"``
  using the install's per-pod signing key.

Per-pod signing key
-------------------
The signing key is a 32-byte secret stored in K8s Secret
``app-pod-key-{instance_id}`` (sibling of the existing
``app-userenv-{instance_id}``). It's:

* Created at install time by ``installer.create_per_pod_signing_key()``.
* Injected into the app container as env var ``OPENSAIL_APPINSTANCE_TOKEN``
  (the pre-signed long-lived token, which is what the SDK forwards in
  the request header verbatim — apps never compute the HMAC themselves).
* Cached in-memory in the proxy with a 60s TTL so we don't read the K8s
  Secret on every request.
* Falls back to a deterministic derivation
  (``HMAC-SHA256(settings.secret_key, "app-pod-key:" + instance_id)``)
  when the K8s Secret is unavailable — same derivation as
  :mod:`shared_singleton_router._derive_signing_key`. This keeps
  desktop / docker-compose / dev modes (which don't have a K8s Secret
  backend) on the same verify path as production.

Constant-time signature compare (``hmac.compare_digest``); 401 on any
mismatch.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....models_automations import AppInstance
from ..shared_singleton_router import _derive_signing_key

logger = logging.getLogger(__name__)


APP_INSTANCE_HEADER = "X-OpenSail-AppInstance"

# Token format: "<uuid>.<nonce>.<hmac>". Three dot-separated fields.
_TOKEN_FIELD_COUNT = 3

# Per-instance signing-key cache TTL. Short enough that a recent rotation
# propagates within a minute; long enough that the K8s API server isn't
# hit on every proxy call.
_SIGNING_KEY_CACHE_TTL_SECONDS = 60


# In-memory cache: instance_id (UUID) → (signing_key_bytes, expires_at_ts).
# Module-global is fine — orchestrator workers run a single proxy
# instance per pod and the cache only lives in that pod's memory.
_signing_key_cache: dict[UUID, tuple[bytes, float]] = {}


class AppInstanceAuthError(HTTPException):
    """Raised when the X-OpenSail-AppInstance header is missing/invalid."""


def _k8s_secret_name(app_instance_id: UUID) -> str:
    """Canonical K8s Secret name for an install's per-pod signing key."""
    return f"app-pod-key-{app_instance_id}"


def generate_pod_signing_key() -> bytes:
    """Mint a fresh 32-byte signing key.

    Used by :func:`services.apps.installer.create_per_pod_signing_key` at
    install time. ``secrets.token_bytes`` is the right cryptographic
    primitive (vs ``os.urandom`` directly) — explicit intent that the
    bytes are key material.
    """
    return secrets.token_bytes(32)


def generate_pod_token(*, app_instance_id: UUID, signing_key: bytes) -> str:
    """Mint the long-lived per-pod token the app container ships with.

    The token is HMAC-SHA256 over ``f"{instance_id}.{nonce}"`` so the
    proxy can verify without ever calling out to the orchestrator. The
    nonce binds the token to a specific Secret rotation — rotating the
    Secret invalidates all previously-issued tokens.
    """
    nonce = secrets.token_urlsafe(16)
    payload = f"{app_instance_id}.{nonce}"
    sig = hmac.new(
        signing_key, payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{sig}"


async def _load_signing_key_from_k8s(
    app_instance_id: UUID,
) -> bytes | None:
    """Try to fetch the per-pod signing key from its K8s Secret.

    Returns None on any failure (K8s client unavailable, Secret not
    found, malformed payload). The caller falls back to the deterministic
    derivation in that case.

    The Secret carries the raw key bytes under ``data.signing_key``
    (base64 by K8s convention). We decode and return the bytes.
    """
    try:
        # Late import — keeps the kubernetes client off the import path
        # for callers in modes (desktop / docker) that never use it.
        import base64

        from kubernetes import client as k8s_client

        from ....config import get_settings  # type: ignore[no-redef]

        settings = get_settings()
        if not getattr(settings, "is_kubernetes_mode", False):
            return None

        core_v1 = k8s_client.CoreV1Api()
        # The Secret lives in the install's project namespace; for the
        # proxy we don't have an easy handle to that namespace today
        # (the AppInstance row carries project_id but not namespace as a
        # cheap join). Phase 4 will hoist the namespace onto a column;
        # until then we read from the orchestrator namespace because the
        # installer mirrors the Secret there too.
        ns = getattr(settings, "kubernetes_namespace", "tesslate") or "tesslate"
        secret = core_v1.read_namespaced_secret(
            name=_k8s_secret_name(app_instance_id),
            namespace=ns,
        )
        data = getattr(secret, "data", None) or {}
        encoded = data.get("signing_key")
        if not encoded:
            return None
        return base64.b64decode(encoded)
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.debug(
            "connector_proxy.auth: K8s Secret lookup failed for %s: %r",
            app_instance_id,
            exc,
        )
        return None


async def _resolve_signing_key(app_instance_id: UUID) -> bytes:
    """Return the signing key for ``app_instance_id`` with TTL caching."""
    now = time.monotonic()
    cached = _signing_key_cache.get(app_instance_id)
    if cached is not None and cached[1] > now:
        return cached[0]

    key = await _load_signing_key_from_k8s(app_instance_id)
    if key is None:
        # Fallback path — same deterministic derivation as the
        # shared-singleton header signer. This keeps desktop / dev /
        # tests on the verify surface without K8s.
        from ....config import get_settings

        settings = get_settings()
        key = _derive_signing_key(
            app_instance_id=app_instance_id,
            fallback_secret=settings.secret_key,
        )

    _signing_key_cache[app_instance_id] = (
        key,
        now + _SIGNING_KEY_CACHE_TTL_SECONDS,
    )
    return key


def _parse_token(header_value: str) -> tuple[UUID, str, str]:
    """Split the header into ``(instance_id, nonce, signature)``.

    Raises :class:`AppInstanceAuthError` (401) on malformed input — this
    is the only failure mode the proxy distinguishes externally.
    """
    parts = header_value.split(".")
    if len(parts) != _TOKEN_FIELD_COUNT:
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid {APP_INSTANCE_HEADER} header (wrong field count)",
        )
    instance_str, nonce, sig = parts
    try:
        instance_id = UUID(instance_str)
    except (TypeError, ValueError) as exc:
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid {APP_INSTANCE_HEADER} header (bad UUID)",
        ) from exc
    if not nonce or not sig:
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid {APP_INSTANCE_HEADER} header (empty field)",
        )
    return instance_id, nonce, sig


async def verify_app_instance(
    request: Request, db: AsyncSession
) -> AppInstance:
    """Resolve and authenticate the calling AppInstance.

    Steps:

    1. Pull the ``X-OpenSail-AppInstance`` header (401 if missing).
    2. Parse into ``(instance_id, nonce, signature)`` (401 if malformed).
    3. Resolve the per-pod signing key (K8s Secret, with TTL cache, with
       deterministic-derivation fallback for non-K8s modes).
    4. Recompute HMAC over ``f"{instance_id}.{nonce}"`` and constant-time
       compare against the supplied signature (401 on mismatch).
    5. Load the AppInstance row; refuse if uninstalled.

    Returns the live ``AppInstance`` row on success.
    """
    header_value = request.headers.get(APP_INSTANCE_HEADER)
    if not header_value:
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing {APP_INSTANCE_HEADER} header",
        )

    instance_id, nonce, sig = _parse_token(header_value)
    signing_key = await _resolve_signing_key(instance_id)

    expected = hmac.new(
        signing_key,
        f"{instance_id}.{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="signature mismatch",
        )

    instance = await db.get(AppInstance, instance_id)
    if instance is None:
        # Use 401 (not 404) so an attacker probing for valid IDs cannot
        # distinguish "wrong id" from "no auth provided".
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="app instance not found or not authorized",
        )

    if instance.uninstalled_at is not None:
        raise AppInstanceAuthError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="app instance has been uninstalled",
        )

    return instance


def invalidate_signing_key_cache(app_instance_id: UUID | None = None) -> None:
    """Drop cached signing key(s).

    Called by the install/uninstall flows when a Secret is rotated or
    removed so the next request re-fetches. Pass ``None`` to flush the
    full cache (used by tests).
    """
    if app_instance_id is None:
        _signing_key_cache.clear()
        return
    _signing_key_cache.pop(app_instance_id, None)


__all__ = [
    "APP_INSTANCE_HEADER",
    "AppInstanceAuthError",
    "generate_pod_signing_key",
    "generate_pod_token",
    "invalidate_signing_key_cache",
    "verify_app_instance",
]


# Used by other modules that want to know the canonical Secret name
# without re-implementing it. Underscored to match the existing
# user_secret_propagator convention.
def k8s_secret_name(app_instance_id: UUID) -> str:  # noqa: D401 — re-export
    """Public re-export of the per-pod-key Secret name builder."""
    return _k8s_secret_name(app_instance_id)


_: Any = k8s_secret_name  # silence unused-name lint when callers import it
