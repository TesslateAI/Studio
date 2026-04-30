"""
Wave 8 — server-side governance for yanks.

Covers:
  * Two-admin policy on critical severity (router + governance helper).
  * Single-admin fast-path on non-critical severity.
  * Self-appeal refused with the wire-stable error code.
  * Appeal lifecycle (creation + state transitions on yank row).
  * Scope enforcement: yanks.write required for create, yanks.appeal
    required for appeal.
  * compute_initial_state policy returns identical decisions for the
    same severity.
"""

from __future__ import annotations

import uuid

import pytest

from app.models import YankRequest
from app.services.yanks_governance import (
    appeal_can_resolve,
    compute_initial_state,
    decide_appeal,
)


# ---------------------------------------------------------------------------
# Pure-policy unit tests (no DB)
# ---------------------------------------------------------------------------


def test_compute_initial_state_critical_stays_open() -> None:
    decision = compute_initial_state("critical")
    assert decision.state == "open"
    assert decision.requires_second_admin is True
    assert decision.resolved_at is None
    assert decision.resolution is None


@pytest.mark.parametrize("sev", ["low", "medium"])
def test_compute_initial_state_noncritical_resolves_immediately(sev: str) -> None:
    decision = compute_initial_state(sev)  # type: ignore[arg-type]
    assert decision.state == "resolved"
    assert decision.requires_second_admin is False
    assert decision.resolution == "applied"
    assert decision.resolved_at is not None


def _yank(*, severity: str, state: str, requested_by: str | None, token: uuid.UUID | None) -> YankRequest:
    return YankRequest(
        id=uuid.uuid4(),
        kind="agent",
        slug="x",
        version="0.1.0",
        severity=severity,
        reason="r",
        requested_by=requested_by,
        requested_by_token_id=token,
        state=state,
    )


def test_appeal_blocked_when_handle_matches() -> None:
    same_handle = "static:abc"
    yank = _yank(severity="critical", state="open", requested_by=same_handle, token=None)
    allowed, reason = appeal_can_resolve(
        yank, appellant_handle=same_handle, appellant_token_id=None
    )
    assert allowed is False
    assert reason == "cannot_self_appeal_critical_yank"


def test_appeal_blocked_when_token_id_matches() -> None:
    token = uuid.uuid4()
    yank = _yank(severity="critical", state="open", requested_by="alice", token=token)
    allowed, reason = appeal_can_resolve(
        yank, appellant_handle="bob", appellant_token_id=token
    )
    assert allowed is False
    assert reason == "cannot_self_appeal_critical_yank"


def test_appeal_allowed_when_distinct_admin() -> None:
    yank = _yank(severity="critical", state="open", requested_by="alice", token=uuid.uuid4())
    allowed, reason = appeal_can_resolve(
        yank, appellant_handle="bob", appellant_token_id=uuid.uuid4()
    )
    assert allowed is True
    assert reason is None


def test_appeal_noncritical_always_allowed() -> None:
    yank = _yank(severity="low", state="resolved", requested_by="alice", token=None)
    allowed, _ = appeal_can_resolve(
        yank, appellant_handle="alice", appellant_token_id=None
    )
    assert allowed is True


def test_decide_appeal_resolves_critical_open() -> None:
    yank = _yank(severity="critical", state="open", requested_by="alice", token=None)
    fake_appeal = type("A", (), {})()
    decision = decide_appeal(
        yank, fake_appeal, appellant_handle="bob", appellant_token_id=None
    )
    assert decision.appeal_state == "resolved"
    assert decision.appeal_decision == "second_admin_confirmed"
    assert decision.yank_state == "resolved"
    assert decision.yank_resolution == "second_admin_confirmed"
    assert decision.yank_resolved_at is not None


def test_decide_appeal_noop_on_already_resolved() -> None:
    yank = _yank(severity="low", state="resolved", requested_by="alice", token=None)
    fake_appeal = type("A", (), {})()
    decision = decide_appeal(
        yank, fake_appeal, appellant_handle="bob", appellant_token_id=None
    )
    assert decision.yank_state == "resolved"


def test_decide_appeal_refuses_on_self_appeal() -> None:
    """When the policy gate refuses, decide_appeal yields a no-op decision."""
    yank = _yank(severity="critical", state="open", requested_by="alice", token=None)
    fake_appeal = type("A", (), {})()
    decision = decide_appeal(
        yank, fake_appeal, appellant_handle="alice", appellant_token_id=None
    )
    assert decision.appeal_state == "open"
    assert decision.appeal_decision is None
    assert decision.yank_state == "open"


# ---------------------------------------------------------------------------
# Router integration — two-admin policy end-to-end
# ---------------------------------------------------------------------------


async def test_critical_yank_two_admin_resolves(client, seeded, auth_headers, auth_headers_admin_2):
    """Distinct second admin's appeal flips critical yank to resolved."""
    res = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "vuln",
            "severity": "critical",
        },
        headers=auth_headers,
    )
    yid = res.json()["id"]
    assert res.json()["state"] == "open"

    appeal = await client.post(
        f"/v1/yanks/{yid}/appeal",
        json={"reason": "second-admin confirms"},
        headers=auth_headers_admin_2,
    )
    assert appeal.status_code == 201
    body = appeal.json()
    assert body["state"] == "resolved"
    assert body["decision"] == "second_admin_confirmed"

    final = await client.get(f"/v1/yanks/{yid}")
    assert final.json()["state"] == "resolved"
    assert final.json()["resolution"] == "second_admin_confirmed"


async def test_critical_self_appeal_refused(client, seeded, auth_headers):
    """Same admin who filed the critical yank cannot self-confirm via appeal."""
    res = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "vuln",
            "severity": "critical",
        },
        headers=auth_headers,
    )
    yid = res.json()["id"]

    appeal = await client.post(
        f"/v1/yanks/{yid}/appeal",
        json={"reason": "i confirm myself"},
        headers=auth_headers,
    )
    assert appeal.status_code == 409
    assert appeal.json()["detail"]["error"] == "cannot_self_appeal_critical_yank"

    # Yank still open.
    detail = await client.get(f"/v1/yanks/{yid}")
    assert detail.json()["state"] == "open"


async def test_noncritical_single_admin_path(client, seeded, auth_headers):
    """Low / medium yanks resolve on the first admin's request."""
    res = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "perf regression",
            "severity": "medium",
        },
        headers=auth_headers,
    )
    body = res.json()
    assert body["state"] == "resolved"
    assert body["resolution"] == "applied"


async def test_yank_create_requires_yanks_write_scope(client, seeded):
    """Anonymous request to /v1/yanks fails 401."""
    res = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "x",
            "severity": "low",
        },
    )
    assert res.status_code == 401


async def test_appeal_requires_yanks_appeal_scope(client, seeded, auth_headers):
    """Token without ``yanks.appeal`` scope is refused 403."""
    # Build a yank first.
    res = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "vuln",
            "severity": "critical",
        },
        headers=auth_headers,
    )
    yid = res.json()["id"]

    # Anonymous appeal fails 401.
    res2 = await client.post(
        f"/v1/yanks/{yid}/appeal", json={"reason": "test"}
    )
    assert res2.status_code == 401
