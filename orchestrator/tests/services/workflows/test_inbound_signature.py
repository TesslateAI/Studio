"""Shared inbound-trigger HMAC verifier (#474 should-fix #7).

Tests the helpers in :mod:`app.services.triggers.webhook_hmac` that
back Phase E typed routes (``/api/triggers/inbound/email`` +
``.../slack/{cc_id}``) and the per-automation webhook router. The
verifier is engine-agnostic; these tests pin behaviour without
spinning up Postgres.
"""

from __future__ import annotations

import hashlib
import hmac
import time


def _hmac_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_candidate_secrets_filters_revoked():
    from app.services.triggers.webhook_hmac import candidate_secrets

    cfg = {
        "webhook_secrets": [
            {"kid": "v1", "secret": "first", "revoked_at": None},
            {"kid": "v2", "secret": "revoked", "revoked_at": "2026-05-01"},
            {"kid": "v3", "secret": "third", "revoked_at": None},
        ]
    }
    out = candidate_secrets(cfg)
    kids = {c["kid"] for c in out}
    assert kids == {"v1", "v3"}


def test_candidate_secrets_legacy_fallback():
    from app.services.triggers.webhook_hmac import candidate_secrets

    cfg = {"webhook_secret": "legacy-single"}
    out = candidate_secrets(cfg)
    assert len(out) == 1
    assert out[0]["kid"] == "legacy"
    assert out[0]["secret"] == "legacy-single"


def test_verify_accepts_sha256_prefix():
    from app.services.triggers.webhook_hmac import verify_webhook_signature

    body = b'{"x":1}'
    sig = "sha256=" + _hmac_hex("sekret", body)
    matched = verify_webhook_signature(
        body_bytes=body,
        provided_signature=sig,
        requested_kid=None,
        candidates=[{"kid": "v1", "secret": "sekret"}],
    )
    assert matched == "v1"


def test_verify_accepts_slack_v0_prefix():
    from app.services.triggers.webhook_hmac import verify_webhook_signature

    body = b'{"channel":"C"}'
    sig = "v0=" + _hmac_hex("sekret", body)
    matched = verify_webhook_signature(
        body_bytes=body,
        provided_signature=sig,
        requested_kid=None,
        candidates=[{"kid": "v1", "secret": "sekret"}],
    )
    assert matched == "v1"


def test_verify_rejects_wrong_signature():
    from app.services.triggers.webhook_hmac import verify_webhook_signature

    body = b'{"x":1}'
    matched = verify_webhook_signature(
        body_bytes=body,
        provided_signature="sha256=" + "0" * 64,
        requested_kid=None,
        candidates=[{"kid": "v1", "secret": "sekret"}],
    )
    assert matched is None


def test_verify_returns_none_when_no_candidates():
    from app.services.triggers.webhook_hmac import verify_webhook_signature

    matched = verify_webhook_signature(
        body_bytes=b"x",
        provided_signature="sha256=" + "0" * 64,
        requested_kid=None,
        candidates=[],
    )
    assert matched is None


def test_verify_kid_pin_path():
    from app.services.triggers.webhook_hmac import verify_webhook_signature

    body = b"hello"
    cands = [
        {"kid": "v1", "secret": "first"},
        {"kid": "v2", "secret": "second"},
    ]
    # Pin v2; signature computed with second only matches when v2 selected.
    sig = "sha256=" + _hmac_hex("second", body)
    assert (
        verify_webhook_signature(
            body_bytes=body, provided_signature=sig, requested_kid="v2", candidates=cands
        )
        == "v2"
    )
    # Same body+sig but pin v1 → no match.
    assert (
        verify_webhook_signature(
            body_bytes=body, provided_signature=sig, requested_kid="v1", candidates=cands
        )
        is None
    )


def test_verify_kid_unknown_returns_none():
    from app.services.triggers.webhook_hmac import verify_webhook_signature

    body = b"x"
    sig = "sha256=" + _hmac_hex("sekret", body)
    assert (
        verify_webhook_signature(
            body_bytes=body,
            provided_signature=sig,
            requested_kid="does-not-exist",
            candidates=[{"kid": "v1", "secret": "sekret"}],
        )
        is None
    )


def test_mint_webhook_secret_shape():
    from app.services.triggers.webhook_hmac import mint_webhook_secret

    entry = mint_webhook_secret()
    assert entry["kid"] == "v1"
    assert isinstance(entry["secret"], str) and len(entry["secret"]) >= 32
    assert entry["revoked_at"] is None
    # Timestamp present + parseable.
    from datetime import datetime

    datetime.fromisoformat(entry["created_at"])


def test_verify_iterates_rotation_until_match():
    """First candidate is stale, second is current. The verifier
    accepts the second match."""
    from app.services.triggers.webhook_hmac import verify_webhook_signature

    body = b"payload"
    new_sig = "sha256=" + _hmac_hex("new-key", body)
    matched = verify_webhook_signature(
        body_bytes=body,
        provided_signature=new_sig,
        requested_kid=None,
        candidates=[
            {"kid": "v1", "secret": "old-key"},
            {"kid": "v2", "secret": "new-key"},
        ],
    )
    assert matched == "v2"


def test_normalize_sig_strips_prefixes():
    from app.services.triggers.webhook_hmac import normalize_sig

    assert normalize_sig("sha256=abc") == "abc"
    assert normalize_sig("v0=abc") == "abc"
    assert normalize_sig("bareHex") == "bareHex"
    assert normalize_sig("") == ""


def test_timing_safe_eq_behavior():
    from app.services.triggers.webhook_hmac import timing_safe_eq

    assert timing_safe_eq("abc", "abc") is True
    assert timing_safe_eq("abc", "abd") is False
    # Different length: still constant-time, should be False, no crash.
    assert timing_safe_eq("abc", "abcd") is False


def test_replay_window_governed_by_caller():
    """The verifier itself is stateless about time — callers
    (the route layer) enforce a timestamp window if needed. This
    test pins that the helper happily verifies an old body if the
    secret matches; per-route replay protection lives in the
    handler (or in develop's idempotency_key index for
    AutomationEvent)."""
    from app.services.triggers.webhook_hmac import verify_webhook_signature

    body = b"x"
    sig = "sha256=" + _hmac_hex("k", body)
    matched = verify_webhook_signature(
        body_bytes=body,
        provided_signature=sig,
        requested_kid=None,
        candidates=[{"kid": "v1", "secret": "k"}],
    )
    assert matched == "v1"
    _ = time  # imported for shape consistency with prior test file
