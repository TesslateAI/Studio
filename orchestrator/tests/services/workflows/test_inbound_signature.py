"""Unit tests for the inbound trigger HMAC verifier (#474 should-fix #7).

Routes ``/api/triggers/inbound/email`` + ``.../slack/{cc_id}`` delegate
their signature check to :func:`app.routers.triggers._verify_inbound_signature`.
These tests pin the helper's behaviour without spinning up Postgres
(which the router-test fixture requires).
"""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException


def _sign(secret: str, ts: int, body: bytes, fmt: str = "sha256") -> str:
    digest = hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    if fmt == "v0":
        return f"v0={digest}"
    return f"sha256={digest}"


class _FakeRequest:
    def __init__(self, body: bytes):
        self._body = body

    async def body(self) -> bytes:  # noqa: D401 — request protocol
        return self._body


@pytest.mark.asyncio
async def test_rejects_when_secret_unset():
    from app.routers.triggers import _verify_inbound_signature

    with pytest.raises(HTTPException) as exc:
        await _verify_inbound_signature(
            _FakeRequest(b"{}"),
            secret="",
            timestamp_header=str(int(time.time())),
            signature_header="sha256=00",
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_rejects_missing_headers():
    from app.routers.triggers import _verify_inbound_signature

    with pytest.raises(HTTPException) as exc:
        await _verify_inbound_signature(
            _FakeRequest(b"{}"),
            secret="sekret",
            timestamp_header=None,
            signature_header=None,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_stale_timestamp():
    from app.routers.triggers import _verify_inbound_signature

    stale_ts = int(time.time()) - 10_000
    body = b'{"x":1}'
    with pytest.raises(HTTPException) as exc:
        await _verify_inbound_signature(
            _FakeRequest(body),
            secret="sekret",
            timestamp_header=str(stale_ts),
            signature_header=_sign("sekret", stale_ts, body),
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_bad_signature():
    from app.routers.triggers import _verify_inbound_signature

    ts = int(time.time())
    body = b'{"x":1}'
    with pytest.raises(HTTPException) as exc:
        await _verify_inbound_signature(
            _FakeRequest(body),
            secret="sekret",
            timestamp_header=str(ts),
            signature_header="sha256=" + "0" * 64,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_accepts_sha256_format():
    from app.routers.triggers import _verify_inbound_signature

    ts = int(time.time())
    body = b'{"x":1}'
    raw = await _verify_inbound_signature(
        _FakeRequest(body),
        secret="sekret",
        timestamp_header=str(ts),
        signature_header=_sign("sekret", ts, body),
    )
    assert raw == body


@pytest.mark.asyncio
async def test_accepts_slack_v0_format():
    """Slack signs with ``X-Slack-Signature: v0=<hex>``; the verifier
    accepts both shapes so platform webhooks work without an adapter."""
    from app.routers.triggers import _verify_inbound_signature

    ts = int(time.time())
    body = b'{"channel":"C123"}'
    raw = await _verify_inbound_signature(
        _FakeRequest(body),
        secret="sekret",
        timestamp_header=str(ts),
        signature_header=_sign("sekret", ts, body, fmt="v0"),
    )
    assert raw == body


@pytest.mark.asyncio
async def test_invalid_timestamp_format():
    from app.routers.triggers import _verify_inbound_signature

    with pytest.raises(HTTPException) as exc:
        await _verify_inbound_signature(
            _FakeRequest(b"{}"),
            secret="sekret",
            timestamp_header="notanumber",
            signature_header="sha256=00",
        )
    assert exc.value.status_code == 401
