"""
Wave 8 — admin governance endpoints (admin.write scope).

Covers:
  * /v1/admin/submissions/{id}/force-approve fast-tracks a submission
    past stage 0/1/2 to ``approved``, recording an
    ``admin_override_approve`` audit check.
  * /v1/admin/submissions/{id}/force-reject finalises immediately to
    ``rejected``.
  * /v1/admin/yanks/{id}/override flips a critical yank to
    ``resolved`` without a second-admin appeal and emits the changes
    feed yank op.
  * Every admin endpoint requires the ``admin.write`` scope; tokens
    that lack it receive 403 with a structured error envelope.
"""

from __future__ import annotations

import base64
import json

from app.services.install_check import write_tar_zst


def _bundle_for(slug: str) -> str:
    payload = json.dumps({"slug": slug, "name": slug}).encode("utf-8")
    data = write_tar_zst({"item.manifest.json": payload})
    return base64.b64encode(data).decode("ascii")


async def _create_open_submission(client, auth_headers, *, slug: str) -> str:
    """Create a submission that pauses pre-terminal so admin endpoints have something to act on.

    The auto-pipeline runs all the way to ``approved`` for valid inputs,
    so we deliberately submit invalid disclosure to land at ``rejected``
    or no-bundle to land somewhere mid-stage. To exercise the admin
    overrides we instead create + then patch state by acting on the
    auto-approved row's terminal status (which the admin endpoints
    refuse with 409, proving the gate).

    For force-approve / force-reject we need a non-terminal row. We seed
    one directly on the DB through ``session_scope``.
    """
    payload = {
        "item": {
            "slug": slug,
            "name": slug.title(),
            "pricing": {"pricing_type": "free", "price_cents": 0, "currency": "usd"},
        },
        "version": {
            "version": "0.1.0",
            "manifest": {
                "slug": slug,
                "required_features": ["agent"],
                "source_visibility": "public",
                "forkable": True,
            },
            "bundle_b64": _bundle_for(slug),
        },
    }
    res = await client.post("/v1/publish/agent", json=payload, headers=auth_headers)
    assert res.status_code == 201
    return res.json()["id"]


async def _seed_in_flight_submission(*, kind: str, slug: str, stage: str = "stage1") -> str:
    """Insert a Submission row directly so we can test the admin overrides
    against a non-terminal state. The publish path always auto-runs to
    terminal in the in-process pipeline."""
    import uuid as _uuid

    from app.database import session_scope
    from app.models import Submission

    sub_id = _uuid.uuid4()
    async with session_scope() as session:
        session.add(
            Submission(
                id=sub_id,
                kind=kind,
                slug=slug,
                version="0.1.0",
                state="stage1_static",
                stage=stage,
                manifest={"slug": slug, "required_features": ["agent"]},
                submitter_handle="seeded",
            )
        )
    return str(sub_id)


# ---------------------------------------------------------------------------
# Force-approve
# ---------------------------------------------------------------------------


async def test_force_approve_walks_through_remaining_stages(env, client, auth_headers_superadmin):
    sub_id = await _seed_in_flight_submission(kind="agent", slug="force-approve-target")

    res = await client.post(
        f"/v1/admin/submissions/{sub_id}/force-approve",
        json={"decision_reason": "shipped under exception"},
        headers=auth_headers_superadmin,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stage"] == "approved"
    assert body["decision"] == "approved"
    # Audit row added.
    names = {c["name"] for c in body["checks"]}
    assert "admin_override_approve" in names


async def test_force_approve_requires_admin_scope(env, client, auth_headers):
    """Token without ``admin.write`` scope cannot force-approve."""
    sub_id = await _seed_in_flight_submission(kind="agent", slug="force-approve-noauth")
    res = await client.post(
        f"/v1/admin/submissions/{sub_id}/force-approve",
        json={"decision_reason": "ill-gotten approval"},
        headers=auth_headers,
    )
    assert res.status_code == 403
    body = res.json()
    assert body["detail"]["error"] == "insufficient_scope"
    assert body["detail"]["required_scope"] == "admin.write"


# ---------------------------------------------------------------------------
# Force-reject
# ---------------------------------------------------------------------------


async def test_force_reject_immediately_terminates(env, client, auth_headers_superadmin):
    sub_id = await _seed_in_flight_submission(kind="agent", slug="force-reject-target")

    res = await client.post(
        f"/v1/admin/submissions/{sub_id}/force-reject",
        json={"decision_reason": "policy violation"},
        headers=auth_headers_superadmin,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["stage"] == "rejected"
    assert body["decision"] == "rejected"
    assert body["decision_reason"] == "policy violation"
    names = {c["name"] for c in body["checks"]}
    assert "admin_override_reject" in names


async def test_force_reject_requires_admin_scope(env, client, auth_headers):
    sub_id = await _seed_in_flight_submission(kind="agent", slug="force-reject-noauth")
    res = await client.post(
        f"/v1/admin/submissions/{sub_id}/force-reject",
        json={"decision_reason": "should not pass"},
        headers=auth_headers,
    )
    assert res.status_code == 403
    assert res.json()["detail"]["required_scope"] == "admin.write"


async def test_force_reject_rejects_terminal(client, env, auth_headers, auth_headers_superadmin):
    """Already-terminal submission cannot be re-rejected."""
    sub_id = await _create_open_submission(client, auth_headers, slug="terminal-already")
    res = await client.post(
        f"/v1/admin/submissions/{sub_id}/force-reject",
        json={"decision_reason": "too late"},
        headers=auth_headers_superadmin,
    )
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# Override yank
# ---------------------------------------------------------------------------


async def test_override_yank_resolves_critical_open(client, seeded, auth_headers, auth_headers_superadmin):
    """A superuser can flip a critical yank to resolved without a second admin appeal."""
    res = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "incident response",
            "severity": "critical",
        },
        headers=auth_headers,
    )
    yid = res.json()["id"]
    assert res.json()["state"] == "open"

    override = await client.post(
        f"/v1/admin/yanks/{yid}/override",
        json={"new_state": "resolved", "resolution": "incident_resolved", "note": "hot-patched"},
        headers=auth_headers_superadmin,
    )
    assert override.status_code == 200, override.text
    body = override.json()
    assert body["state"] == "resolved"
    assert body["resolution"] == "incident_resolved"
    assert body["resolved_at"] is not None


async def test_override_yank_requires_admin_scope(client, seeded, auth_headers):
    res = await client.post(
        "/v1/yanks",
        json={
            "kind": "agent",
            "slug": "tesslate-agent",
            "version": "0.1.0",
            "reason": "just kidding",
            "severity": "critical",
        },
        headers=auth_headers,
    )
    yid = res.json()["id"]

    override = await client.post(
        f"/v1/admin/yanks/{yid}/override",
        json={"new_state": "resolved"},
        headers=auth_headers,
    )
    assert override.status_code == 403
    assert override.json()["detail"]["required_scope"] == "admin.write"


# ---------------------------------------------------------------------------
# Anonymous + missing-token
# ---------------------------------------------------------------------------


async def test_admin_endpoints_refuse_anonymous(env, client):
    sub_id = await _seed_in_flight_submission(kind="agent", slug="anon")
    for path, body in [
        (f"/v1/admin/submissions/{sub_id}/force-approve", {}),
        (f"/v1/admin/submissions/{sub_id}/force-reject", {"decision_reason": "x"}),
        (f"/v1/admin/yanks/{sub_id}/override", {"new_state": "resolved"}),
    ]:
        res = await client.post(path, json=body)
        assert res.status_code == 401, f"{path}: {res.text}"
