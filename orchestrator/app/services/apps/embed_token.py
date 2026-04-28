"""Signed view-embed tokens for App Composition.

A parent app does not render a child's view directly. Instead, the parent
mints a short-lived JWT via :func:`sign_embed_token`, then renders an
iframe pointing at the child's embed endpoint with the token in the URL
or header. The child container validates the signature via
:func:`verify_embed_token`, reads the bound ``input`` and ``view_name``
from the claims, and renders.

Signing uses HS256 over the orchestrator's ``secret_key`` config value.
The same secret already protects user session JWTs (see ``app/auth.py``)
so an attacker capable of forging an embed token already controls
authentication globally — there is no point storing a separate secret.

Token shape (RFC 7519-ish):

  {
    "iss": "opensail-runtime",
    "sub": "<child_install_id>",      # the install the iframe will hit
    "aud": "<child_install_id>",      # echoed for clarity
    "iat": <unix>,
    "exp": <unix + ttl>,
    "parent_install_id": "<uuid>",
    "view_name": "<name>",
    "input": {...},
    "scopes_granted": [...]
  }

Errors
------
:class:`EmbedTokenInvalid` is raised on any signature, expiry, malformed
payload, or missing-required-claim failure. The router catches it and
returns 401 / 403 as appropriate; the caller never sees a stack trace.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from ...config import get_settings

logger = logging.getLogger(__name__)


_ISSUER = "opensail-runtime"
_ALG = "HS256"
# Last-resort dev fallback so an empty secret_key in a fresh dev shell
# doesn't crash mint/verify. NEVER used in cloud / k8s — config validation
# refuses an empty secret_key for those modes — but desktop sidecar tests
# can spin up without explicit env wiring.
_DEV_FALLBACK_SECRET = "tesslate-dev-embed-token-secret-do-not-use-in-prod"


class EmbedTokenInvalid(Exception):
    """Token failed signature, expiry, or schema validation."""


def _signing_secret() -> str:
    settings = get_settings()
    secret = (settings.secret_key or "").strip()
    if not secret:
        # Plan §"App Composition": dev fallback is acceptable so the
        # composition runtime works in a fresh checkout. Production
        # deployments set ``SECRET_KEY`` via env and the fallback path
        # is unreachable.
        logger.warning(
            "embed_token: SECRET_KEY not configured; using dev fallback "
            "(do not run in production)"
        )
        return _DEV_FALLBACK_SECRET
    return secret


def sign_embed_token(
    *,
    parent_install_id: UUID,
    child_install_id: UUID,
    view_name: str,
    input: dict[str, Any],
    ttl_seconds: int,
    scopes_granted: list[str] | None = None,
) -> str:
    """Mint a signed JWT for a parent → child view embed.

    The token is HS256-signed over the orchestrator's ``secret_key``.
    ``ttl_seconds`` is the absolute lifetime in seconds — the token is
    rejected at verification once ``iat + ttl_seconds`` < now.
    """
    if ttl_seconds <= 0:
        raise ValueError(f"ttl_seconds must be positive (got {ttl_seconds})")

    import time

    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": _ISSUER,
        "sub": str(child_install_id),
        "aud": str(child_install_id),
        "iat": now,
        "exp": now + int(ttl_seconds),
        "parent_install_id": str(parent_install_id),
        "view_name": str(view_name),
        "input": input or {},
        "scopes_granted": list(scopes_granted or []),
    }
    return jwt.encode(claims, _signing_secret(), algorithm=_ALG)


def verify_embed_token(token: str) -> dict[str, Any]:
    """Verify and decode a previously-minted embed token.

    Raises :class:`EmbedTokenInvalid` on any failure: bad signature,
    expired, malformed JSON, wrong issuer, or missing required claims.
    Returns the decoded claims dict on success.
    """
    if not token or not isinstance(token, str):
        raise EmbedTokenInvalid("token is empty or not a string")

    secret = _signing_secret()
    try:
        # ``audience`` is set per-call by the caller (the child install id),
        # not at decode time — we don't have access to the install id when
        # only the token is in hand. Skip aud check at the JWT layer; the
        # caller reads ``sub`` and is responsible for verifying the iframe
        # is hitting the correct install.
        claims = jwt.decode(
            token,
            secret,
            algorithms=[_ALG],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise EmbedTokenInvalid(f"jwt decode failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — defense-in-depth
        raise EmbedTokenInvalid(f"unexpected decode error: {exc}") from exc

    # Schema check — the encoder is hermetic and writes every required
    # field, but a token from a *different* signer with the same secret
    # could still be malformed. Be paranoid.
    if not isinstance(claims, dict):
        raise EmbedTokenInvalid("decoded claims is not a dict")
    if claims.get("iss") != _ISSUER:
        raise EmbedTokenInvalid(f"iss mismatch (expected {_ISSUER!r})")
    for required in ("sub", "parent_install_id", "view_name", "exp", "iat"):
        if required not in claims:
            raise EmbedTokenInvalid(f"missing required claim {required!r}")

    return claims


__all__ = [
    "EmbedTokenInvalid",
    "sign_embed_token",
    "verify_embed_token",
]
