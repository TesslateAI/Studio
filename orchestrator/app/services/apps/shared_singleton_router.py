"""Shared-singleton header signing — ``X-OpenSail-User`` HMAC.

Phase 3 ``shared_singleton`` apps run a single container/Deployment that
serves N users. Per-user secrets cannot be env-injected (one container,
many users), so the dispatcher signs ``user_id`` into a header the app
container can verify before serving the request.

Header shape::

    X-OpenSail-User: <user_id>:<app_instance_id>:<exp>:<hmac_hex>

* ``user_id`` and ``app_instance_id`` are UUID strings.
* ``exp`` is a unix timestamp (seconds, integer).
* ``hmac_hex`` is HMAC-SHA256 over
  ``f"{user_id}:{app_instance_id}:{exp}"`` keyed by the app instance's
  per-pod signing key (see :mod:`.key_lifecycle` integration below).

5-minute expiry. Constant-time signature compare on verify. Verification
returns the resolved user_id or raises :class:`InvalidSignature`.

Per-pod signing-key source
--------------------------
Each app instance gets a 32-byte signing key minted at install time and
stored in K8s Secret ``app-pod-key-{instance_id}`` (sibling of
``app-userenv-{instance_id}``). The dispatcher reads the key when
signing; the app container reads it via env var
``OPENSAIL_APPINSTANCE_TOKEN`` (Wave 1A — :mod:`.connector_proxy.auth`).

For the shared-singleton router specifically, we ALSO accept a key
derived deterministically from ``settings.secret_key + app_instance_id``
so the verify side can be exercised in tests / dev modes that haven't
provisioned the K8s Secret yet. The deterministic derivation is the same
function callers use during install when no Secret backend is available
(desktop / docker-compose modes).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from uuid import UUID

logger = logging.getLogger(__name__)


# Header name used by shared-singleton apps to identify the calling user.
SHARED_USER_HEADER = "X-OpenSail-User"

# Token validity. Short enough that a leaked token isn't long-lived; long
# enough that clock skew between dispatcher + pod doesn't cause spurious
# rejections.
DEFAULT_TTL_SECONDS = 300

# 30-second clock-skew tolerance on the verify side. Apps and the
# orchestrator may be on different nodes with NTP drift; a strict
# now < exp comparison would reject legitimate calls minted seconds
# before a slow NTP sync.
CLOCK_SKEW_TOLERANCE_SECONDS = 30


class InvalidSignature(Exception):
    """Raised on any verify failure (malformed, expired, signature mismatch)."""


def _derive_signing_key(
    *, app_instance_id: UUID, fallback_secret: str | bytes
) -> bytes:
    """Return the 32-byte HMAC key for ``app_instance_id``.

    Production: this delegates to :func:`load_pod_signing_key`
    (defined in :mod:`.connector_proxy.auth` Wave 1A) which reads the K8s
    Secret. Until that wave lands the deterministic-derivation fallback
    is the canonical source — both produce the same key for the same
    inputs so signing/verify stay in sync across a rolling upgrade.

    Derivation: ``HMAC-SHA256(secret_key, "app-pod-key:" || str(instance_id))``.
    """
    if isinstance(fallback_secret, str):
        fallback_bytes = fallback_secret.encode("utf-8")
    else:
        fallback_bytes = fallback_secret
    if not fallback_bytes:
        raise InvalidSignature(
            "no signing material available — settings.secret_key is empty"
        )
    return hmac.new(
        fallback_bytes,
        b"app-pod-key:" + str(app_instance_id).encode("utf-8"),
        hashlib.sha256,
    ).digest()


async def sign_user_header(
    user_id: UUID,
    app_instance_id: UUID,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    secret_override: str | bytes | None = None,
) -> str:
    """Mint a signed ``X-OpenSail-User`` header value.

    Args:
        user_id: The acting user — surfaces inside the shared container.
        app_instance_id: The shared-singleton install id; selects which
            per-pod signing key to use.
        ttl_seconds: How long the header is valid. Default 5 minutes.
        secret_override: Test seam — production callers leave None and
            pull from ``settings.secret_key``.

    Returns:
        The header value (string of the form
        ``"user_id:app_instance_id:exp:hmac"``).
    """
    if secret_override is None:
        from ...config import get_settings

        secret_override = get_settings().secret_key

    signing_key = _derive_signing_key(
        app_instance_id=app_instance_id, fallback_secret=secret_override
    )
    exp = int(time.time()) + max(1, ttl_seconds)
    payload = f"{user_id}:{app_instance_id}:{exp}"
    sig = hmac.new(
        signing_key, payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{sig}"


async def verify_user_header(
    header_value: str,
    app_instance_id: UUID,
    *,
    secret_override: str | bytes | None = None,
    now_seconds: int | None = None,
) -> UUID:
    """Verify a signed header value and return the embedded user id.

    Raises :class:`InvalidSignature` on any failure mode:

    * Malformed structure (missing fields, non-int exp).
    * The embedded ``app_instance_id`` does not match the expected one
      (so an attacker cannot replay a header signed for app A onto app B).
    * Expired (with ``CLOCK_SKEW_TOLERANCE_SECONDS`` slack).
    * Signature mismatch (constant-time compare).
    """
    if not header_value or not isinstance(header_value, str):
        raise InvalidSignature("header value missing or not a string")

    parts = header_value.split(":")
    if len(parts) != 4:
        raise InvalidSignature(
            f"expected 4 colon-separated fields, got {len(parts)}"
        )
    user_id_str, instance_str, exp_str, sig_hex = parts

    try:
        user_id = UUID(user_id_str)
    except (TypeError, ValueError) as exc:
        raise InvalidSignature(f"user_id not a UUID: {exc}") from exc

    try:
        embedded_instance_id = UUID(instance_str)
    except (TypeError, ValueError) as exc:
        raise InvalidSignature(
            f"app_instance_id not a UUID: {exc}"
        ) from exc

    if embedded_instance_id != app_instance_id:
        # Cross-app replay defense — header signed for instance A must
        # never authenticate against instance B. The verify side knows
        # its expected instance id from the call-site context.
        raise InvalidSignature(
            "embedded app_instance_id does not match expected"
        )

    try:
        exp = int(exp_str)
    except (TypeError, ValueError) as exc:
        raise InvalidSignature(f"exp not an integer: {exc}") from exc

    now = now_seconds if now_seconds is not None else int(time.time())
    if exp + CLOCK_SKEW_TOLERANCE_SECONDS < now:
        raise InvalidSignature(
            f"header expired at {exp} (now={now})"
        )

    if secret_override is None:
        from ...config import get_settings

        secret_override = get_settings().secret_key

    signing_key = _derive_signing_key(
        app_instance_id=app_instance_id, fallback_secret=secret_override
    )
    expected = hmac.new(
        signing_key,
        f"{user_id}:{app_instance_id}:{exp}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, sig_hex):
        raise InvalidSignature("signature mismatch")
    return user_id


__all__ = [
    "CLOCK_SKEW_TOLERANCE_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "InvalidSignature",
    "SHARED_USER_HEADER",
    "sign_user_header",
    "verify_user_header",
]
