"""Shared HMAC verification for inbound trigger webhooks.

Lifted out of ``routers/app_triggers.py`` so Phase E typed inbound
routes (``/api/triggers/inbound/email`` + ``.../slack/{cc_id}``) and
the generic per-automation webhook (``/api/automations/{id}/webhook/
{token}``) share one signature-verification path with the
rotation-friendly ``trigger.config["webhook_secrets"][]`` storage.

The mint helper produces the canonical secret-list entry that
:func:`candidate_secrets` knows how to read. ``token_urlsafe(32)`` is
the same generator the standalone-webhook auto-provisioner uses.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets as _stdlib_secrets
from datetime import UTC, datetime
from typing import Any


def hmac_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def normalize_sig(s: str) -> str:
    """Accept either ``sha256=<hex>``, ``v0=<hex>``, or bare ``<hex>``
    so the verifier handles both Tesslate-native and Slack-style
    callers without an adapter layer."""
    s = (s or "").strip()
    if s.lower().startswith("sha256="):
        return s[len("sha256=") :]
    if s.lower().startswith("v0="):
        return s[len("v0=") :]
    return s


def timing_safe_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except (AttributeError, TypeError):
        return False


def candidate_secrets(trig_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Non-revoked secrets in the canonical list shape, with legacy
    single-key fallback. Each entry normalized to ``{kid, secret}``.
    """
    raw_list = trig_cfg.get("webhook_secrets")
    out: list[dict[str, Any]] = []
    if isinstance(raw_list, list) and raw_list:
        for entry in raw_list:
            if not isinstance(entry, dict):
                continue
            secret = entry.get("secret")
            if not secret or entry.get("revoked_at"):
                continue
            out.append({"kid": entry.get("kid") or "v?", "secret": str(secret)})
        return out
    legacy = trig_cfg.get("webhook_secret")
    if isinstance(legacy, str) and legacy:
        out.append({"kid": "legacy", "secret": legacy})
    return out


def verify_webhook_signature(
    *,
    body_bytes: bytes,
    provided_signature: str | None,
    requested_kid: str | None,
    candidates: list[dict[str, Any]],
) -> str | None:
    """Return the matching ``kid`` or ``None`` if no candidate verified.

    Pinned-kid path verifies exactly one secret. Fall-through tries
    each non-revoked secret in declaration order; first match wins.
    Each comparison is constant-time; the loop bound is the small
    rotation count.
    """
    if not provided_signature or not candidates:
        return None
    provided = normalize_sig(provided_signature)

    if requested_kid:
        target = next((c for c in candidates if c["kid"] == requested_kid), None)
        if target is None:
            return None
        expected = hmac_hex(target["secret"], body_bytes)
        return target["kid"] if timing_safe_eq(provided, expected) else None

    for cand in candidates:
        expected = hmac_hex(cand["secret"], body_bytes)
        if timing_safe_eq(provided, expected):
            return cand["kid"]
    return None


def mint_webhook_secret() -> dict[str, Any]:
    """Fresh ``webhook_secrets[]`` entry. ``kid='v1'`` on first mint;
    rotation appends with incrementing kids in a future endpoint."""
    return {
        "kid": "v1",
        "secret": _stdlib_secrets.token_urlsafe(32),
        "created_at": datetime.now(tz=UTC).isoformat(),
        "revoked_at": None,
    }


__all__ = [
    "candidate_secrets",
    "hmac_hex",
    "mint_webhook_secret",
    "normalize_sig",
    "timing_safe_eq",
    "verify_webhook_signature",
]
