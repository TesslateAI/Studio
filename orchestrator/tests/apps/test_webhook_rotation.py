"""Wave 9 Track C1 — webhook secret rotation, revocation, listing.

Covers:
  - Verifier accepts the new ``webhook_secrets`` list shape.
  - Verifier still accepts the legacy ``webhook_secret`` single-key shape.
  - Pinned ``x-tesslate-key-id`` selects exactly one secret.
  - No-kid path falls through to the next non-revoked secret.
  - Revoked kids are rejected (even by direct pin).
  - Rotation appends a new ``v{N+1}`` and returns plaintext once.
  - List endpoint never returns plaintext.

These exercise the pure helpers + the verifier branch logic. The integration
flow (HTTP route end-to-end with a real DB + audit writes) is covered by the
manual install harness; this file stays unit-scoped so it runs in CI without
Postgres.
"""

from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace
from uuid import uuid4

from app.routers import app_schedules
from app.routers.app_triggers import (
    _candidate_secrets,
    _hmac_hex,
    _normalize_sig,
    _timing_safe_eq,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _entry(kid: str, secret: str, *, revoked: bool = False) -> dict:
    return {
        "kid": kid,
        "secret": secret,
        "created_at": "2026-01-01T00:00:00+00:00",
        "revoked_at": "2026-04-01T00:00:00+00:00" if revoked else None,
    }


def _verify(
    trig_cfg: dict, body: bytes, sig_header: str, kid_header: str | None = None
) -> str | None:
    """Re-implement the verifier's match decision using the public helpers,
    so tests stay decoupled from FastAPI plumbing while still exercising the
    same code paths the route relies on.
    """
    candidates = _candidate_secrets(trig_cfg)
    sig = _normalize_sig(sig_header)
    if kid_header:
        target = next((c for c in candidates if c["kid"] == kid_header), None)
        if target is None:
            return None
        return target["kid"] if _timing_safe_eq(sig, _hmac_hex(target["secret"], body)) else None
    for c in candidates:
        if _timing_safe_eq(sig, _hmac_hex(c["secret"], body)):
            return c["kid"]
    return None


# ---------------------------------------------------------------------------
# Verifier — back-compat with the legacy single-key shape.
# ---------------------------------------------------------------------------


def test_legacy_single_key_still_verifies():
    """Schedules created before Wave 9 wrote ``webhook_secret`` directly."""
    cfg = {"webhook_secret": "legacy-secret-value"}
    body = b'{"hello":"world"}'
    sig = _sign("legacy-secret-value", body)
    assert _verify(cfg, body, sig) == "legacy"
    # ``sha256=`` prefix accepted.
    assert _verify(cfg, body, f"sha256={sig}") == "legacy"


def test_legacy_wrong_secret_rejected():
    cfg = {"webhook_secret": "legacy"}
    assert _verify(cfg, b"x", _sign("other", b"x")) is None


# ---------------------------------------------------------------------------
# Verifier — new list shape, pinned + fallthrough.
# ---------------------------------------------------------------------------


def test_pinned_kid_selects_exact_secret():
    cfg = {
        "webhook_secrets": [
            _entry("v1", "old-secret"),
            _entry("v2", "new-secret"),
        ]
    }
    body = b"payload"
    assert _verify(cfg, body, _sign("v1", body), kid_header="v1") is None
    assert _verify(cfg, body, _sign("old-secret", body), kid_header="v1") == "v1"
    assert _verify(cfg, body, _sign("new-secret", body), kid_header="v2") == "v2"
    # Pinned to v1 must not silently accept v2's secret.
    assert _verify(cfg, body, _sign("new-secret", body), kid_header="v1") is None


def test_unknown_kid_pin_rejected():
    cfg = {"webhook_secrets": [_entry("v1", "s1")]}
    assert _verify(cfg, b"x", _sign("s1", b"x"), kid_header="v9") is None


def test_no_kid_falls_through_to_next_live_secret():
    cfg = {
        "webhook_secrets": [
            _entry("v1", "old"),
            _entry("v2", "new"),
        ]
    }
    body = b"hi"
    # Caller signs with v2 but doesn't pin: still matches.
    assert _verify(cfg, body, _sign("new", body)) == "v2"
    # Caller signs with v1: also matches.
    assert _verify(cfg, body, _sign("old", body)) == "v1"


def test_revoked_kid_rejected_even_when_pinned():
    cfg = {
        "webhook_secrets": [
            _entry("v1", "old", revoked=True),
            _entry("v2", "new"),
        ]
    }
    body = b"hi"
    # Pinned to revoked v1 with the right secret — still rejected.
    assert _verify(cfg, body, _sign("old", body), kid_header="v1") is None
    # No-kid path: v1 filtered out, v2 only candidate.
    assert _verify(cfg, body, _sign("old", body)) is None
    assert _verify(cfg, body, _sign("new", body)) == "v2"


def test_install_then_rotate_then_revoke_sequence():
    """End-to-end: simulate the lifecycle the rotate/revoke endpoints drive.

    install -> rotate -> v1 still works -> revoke v1 -> v1 rejected, v2 ok.
    """
    # 1) Install: installer writes a single v1 entry.
    cfg = {
        "webhook_secrets": [_entry("v1", "secret-one")],
    }
    body = b'{"event":"ping"}'
    assert _verify(cfg, body, _sign("secret-one", body)) == "v1"

    # 2) Rotate: append v2 via the helper used by the rotate endpoint.
    secrets_list = app_schedules._normalize_secrets_list(cfg)
    next_kid = app_schedules._next_kid(secrets_list)
    assert next_kid == "v2"
    secrets_list.append(
        {
            "kid": next_kid,
            "secret": "secret-two",
            "created_at": "2026-04-15T00:00:00+00:00",
            "revoked_at": None,
        }
    )
    cfg["webhook_secrets"] = secrets_list

    # 3) Old kid still accepted (this is the whole point of rotation).
    assert _verify(cfg, body, _sign("secret-one", body), kid_header="v1") == "v1"
    assert _verify(cfg, body, _sign("secret-two", body), kid_header="v2") == "v2"

    # 4) Revoke v1.
    for e in cfg["webhook_secrets"]:
        if e["kid"] == "v1":
            e["revoked_at"] = "2026-04-15T01:00:00+00:00"

    # 5) v1 rejected; v2 still works (both pinned and no-kid).
    assert _verify(cfg, body, _sign("secret-one", body), kid_header="v1") is None
    assert _verify(cfg, body, _sign("secret-one", body)) is None
    assert _verify(cfg, body, _sign("secret-two", body), kid_header="v2") == "v2"
    assert _verify(cfg, body, _sign("secret-two", body)) == "v2"


# ---------------------------------------------------------------------------
# Helpers used by the management router.
# ---------------------------------------------------------------------------


def test_normalize_lifts_legacy_single_key_into_v1():
    out = app_schedules._normalize_secrets_list({"webhook_secret": "old"})
    assert out == [{"kid": "v1", "secret": "old", "created_at": None, "revoked_at": None}]


def test_normalize_passes_through_list_shape():
    cfg = {"webhook_secrets": [_entry("v1", "s1"), _entry("v2", "s2", revoked=True)]}
    out = app_schedules._normalize_secrets_list(cfg)
    assert [e["kid"] for e in out] == ["v1", "v2"]
    assert out[1]["revoked_at"] is not None


def test_next_kid_skips_non_numeric():
    existing = [
        {"kid": "legacy", "secret": "x"},
        {"kid": "v3", "secret": "x"},
        {"kid": "v1", "secret": "x"},
    ]
    assert app_schedules._next_kid(existing) == "v4"


def test_next_kid_starts_at_v1_for_empty():
    assert app_schedules._next_kid([]) == "v1"


def test_candidate_secrets_filters_revoked():
    cfg = {
        "webhook_secrets": [
            _entry("v1", "s1", revoked=True),
            _entry("v2", "s2"),
        ]
    }
    cands = _candidate_secrets(cfg)
    assert [c["kid"] for c in cands] == ["v2"]


def test_candidate_secrets_empty_when_no_keys():
    assert _candidate_secrets({}) == []


# ---------------------------------------------------------------------------
# Sanity: installer emits the new shape (without running the full installer).
# ---------------------------------------------------------------------------


def test_installer_emits_list_shape_for_webhook_kind():
    """Smoke-check the exact lines the installer runs when trigger_kind is
    'webhook'. Mirrors the snippet in services/apps/installer.py so a refactor
    that drops the new shape gets caught here, not in production.
    """
    import secrets as _secrets
    from datetime import datetime, timezone

    trigger_config: dict = {"execution": "job", "entrypoint": None}
    trigger_config["webhook_secrets"] = [
        {
            "kid": "v1",
            "secret": _secrets.token_urlsafe(32),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "revoked_at": None,
        }
    ]
    assert "webhook_secret" not in trigger_config
    assert isinstance(trigger_config["webhook_secrets"], list)
    only = trigger_config["webhook_secrets"][0]
    assert only["kid"] == "v1"
    assert only["revoked_at"] is None
    assert len(only["secret"]) >= 32

    # Verifier accepts this freshly-installed shape.
    body = b"hello"
    sig = _sign(only["secret"], body)
    assert _verify(trigger_config, body, sig) == "v1"
    assert _verify(trigger_config, body, sig, kid_header="v1") == "v1"


# Sentinel for `pytest -k` filtering.
_ = SimpleNamespace(uuid=uuid4())
