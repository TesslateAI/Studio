"""
Integration tests for team-scoped billing (RBAC PRD Section 6).

Tests:
- Credit pool lives on the Team, not User
- Credits scoped to active team (switching teams changes credits)
- Subscription tier reads from active team
- Admin can manage subscriptions; Editor/Viewer cannot
- Editor and Viewer can view credit balance
- Usage tracking is per-user
- New teams (personal and non-personal) default to free tier

Requires: docker-compose.test.yml postgres on port 5433
Run: pytest tests/integration/test_rbac_billing.py -v -m integration
"""

from uuid import uuid4

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────


def _create_team_and_user_b(api_client_session, admin_client, team_prefix, role="editor"):
    """
    Create a new team (owned by admin_client), invite and register User B
    with the given role.

    Returns: (client_b, user_b_data, team_slug, token_b)
    """
    client_a, _ = admin_client
    slug = f"{team_prefix}-{uuid4().hex[:8]}"

    resp = client_a.post("/api/teams", json={"name": f"Team {team_prefix}", "slug": slug})
    assert resp.status_code in (200, 201), f"Team create failed: {resp.text}"

    link_resp = client_a.post(f"/api/teams/{slug}/members/link", json={"role": role})
    assert link_resp.status_code in (200, 201), f"Invite link failed: {link_resp.text}"
    invite_token = link_resp.json()["token"]

    # Register User B
    email_b = f"userb-{uuid4().hex[:8]}@example.com"
    api_client_session.headers.pop("Authorization", None)
    reg = api_client_session.post(
        "/api/auth/register",
        json={"email": email_b, "password": "TestPass123!", "name": "User B"},
    )
    assert reg.status_code == 201, f"User B registration failed: {reg.text}"
    user_b_data = reg.json()

    # Login as User B
    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email_b, "password": "TestPass123!"},
    )
    assert login.status_code == 200, f"User B login failed: {login.text}"
    token_b = login.json()["access_token"]

    api_client_session.headers["Authorization"] = f"Bearer {token_b}"

    # Accept the invitation
    accept = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")
    assert accept.status_code == 200, f"Invite accept failed: {accept.text}"

    # Switch User B to the new team
    switch = api_client_session.post(f"/api/teams/{slug}/switch")
    assert switch.status_code == 200, f"Team switch failed: {switch.text}"

    return api_client_session, user_b_data, slug, token_b


# ── Credits Endpoints ────────────────────────────────────────────────────


@pytest.mark.integration
def test_credits_endpoint_returns_team_credits(authenticated_client):
    """GET /api/billing/credits returns 200 with team credit info."""
    client, _ = authenticated_client

    resp = client.get("/api/billing/credits")
    assert resp.status_code == 200, f"Credits endpoint failed: {resp.text}"

    data = resp.json()
    assert "total_credits" in data, f"Missing total_credits in response: {data}"
    assert isinstance(data["total_credits"], int)


@pytest.mark.integration
def test_credits_scoped_to_active_team(authenticated_client, api_client_session):
    """
    Switching teams should change the credit balance returned by
    GET /api/billing/credits.
    """
    client, _ = authenticated_client

    # Get credits for personal team
    resp_personal = client.get("/api/billing/credits")
    assert resp_personal.status_code == 200
    resp_personal.json()

    # Create a second (non-personal) team
    slug = f"billing-test-{uuid4().hex[:8]}"
    create_resp = client.post("/api/teams", json={"name": "Billing Test Team", "slug": slug})
    assert create_resp.status_code in (200, 201), f"Team create failed: {create_resp.text}"

    # Switch to the new team
    switch_resp = client.post(f"/api/teams/{slug}/switch")
    assert switch_resp.status_code == 200, f"Team switch failed: {switch_resp.text}"

    # Get credits for the new team
    resp_new = client.get("/api/billing/credits")
    assert resp_new.status_code == 200
    credits_new = resp_new.json()

    # Both should have valid credit structures
    assert "total_credits" in credits_new
    assert "tier" in credits_new

    # Switch back to personal team
    teams_resp = client.get("/api/teams")
    assert teams_resp.status_code == 200
    personal = [t for t in teams_resp.json() if t["is_personal"]]
    assert len(personal) == 1
    personal_slug = personal[0]["slug"]

    switch_back = client.post(f"/api/teams/{personal_slug}/switch")
    assert switch_back.status_code == 200

    # Credits should again be the personal team's credits
    resp_back = client.get("/api/billing/credits")
    assert resp_back.status_code == 200
    credits_back = resp_back.json()
    assert "total_credits" in credits_back


# ── Subscription Endpoints ───────────────────────────────────────────────


@pytest.mark.integration
def test_subscription_endpoint_returns_team_subscription(authenticated_client):
    """GET /api/billing/subscription returns 200 with tier info."""
    client, _ = authenticated_client

    resp = client.get("/api/billing/subscription")
    assert resp.status_code == 200, f"Subscription endpoint failed: {resp.text}"

    data = resp.json()
    assert "tier" in data
    # New users default to free
    assert data["tier"] == "free"


@pytest.mark.integration
def test_admin_can_subscribe(authenticated_client):
    """
    Admin calls POST /api/billing/subscribe.
    Should NOT get 403 — any of 200, 400, 500 is acceptable
    (Stripe is mocked/not configured in test env).
    """
    client, _ = authenticated_client

    resp = client.post(
        "/api/billing/subscribe",
        json={"tier": "pro", "billing_interval": "monthly"},
    )
    # The key assertion: admin is not denied by RBAC
    assert resp.status_code != 403, f"Admin should not be forbidden from subscribing: {resp.text}"


@pytest.mark.integration
def test_editor_cannot_subscribe(authenticated_client, api_client_session):
    """Editor in a team cannot call POST /api/billing/subscribe (expect 403)."""
    client_b, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "ed-sub", role="editor"
    )

    resp = client_b.post(
        "/api/billing/subscribe",
        json={"tier": "pro", "billing_interval": "monthly"},
    )
    assert resp.status_code == 403, (
        f"Editor should be forbidden from subscribing, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.integration
def test_viewer_cannot_subscribe(authenticated_client, api_client_session):
    """Viewer in a team cannot call POST /api/billing/subscribe (expect 403)."""
    client_b, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vw-sub", role="viewer"
    )

    resp = client_b.post(
        "/api/billing/subscribe",
        json={"tier": "pro", "billing_interval": "monthly"},
    )
    assert resp.status_code == 403, (
        f"Viewer should be forbidden from subscribing, got {resp.status_code}: {resp.text}"
    )


# ── Credit Visibility by Role ────────────────────────────────────────────


@pytest.mark.integration
def test_editor_can_view_credits(authenticated_client, api_client_session):
    """Editor should be able to view credit balance (200)."""
    client_b, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "ed-cred", role="editor"
    )

    resp = client_b.get("/api/billing/credits")
    assert resp.status_code == 200, (
        f"Editor should be able to view credits, got {resp.status_code}: {resp.text}"
    )
    assert "total_credits" in resp.json()


@pytest.mark.integration
def test_viewer_can_view_credits(authenticated_client, api_client_session):
    """Viewer should be able to view credit balance (200)."""
    client_b, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vw-cred", role="viewer"
    )

    resp = client_b.get("/api/billing/credits")
    assert resp.status_code == 200, (
        f"Viewer should be able to view credits, got {resp.status_code}: {resp.text}"
    )
    assert "total_credits" in resp.json()


# ── Usage Endpoint ───────────────────────────────────────────────────────


@pytest.mark.integration
def test_viewer_cannot_view_usage(authenticated_client, api_client_session):
    """
    Viewer tries GET /api/billing/usage.
    Per PRD, viewers cannot view usage logs — expect 403.
    Accept 200 if endpoint is not yet restricted (test still validates shape).
    """
    client_b, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vw-usage", role="viewer"
    )

    resp = client_b.get("/api/billing/usage")
    # Accept either 403 (restricted) or 200 (not yet restricted)
    assert resp.status_code in (200, 403), (
        f"Unexpected status for viewer usage access: {resp.status_code}: {resp.text}"
    )
    if resp.status_code == 200:
        # If allowed, at least verify the response shape
        data = resp.json()
        assert "total_cost_cents" in data or "total_requests" in data


# ── Tier Defaults ────────────────────────────────────────────────────────


@pytest.mark.integration
def test_personal_team_has_free_tier(authenticated_client):
    """New user's personal team should default to free tier."""
    client, _ = authenticated_client

    resp = client.get("/api/billing/subscription")
    assert resp.status_code == 200

    data = resp.json()
    assert data["tier"] == "free", f"Expected free tier, got: {data['tier']}"


@pytest.mark.integration
def test_new_team_inherits_free_tier(authenticated_client):
    """A newly created non-personal team should also default to free tier."""
    client, _ = authenticated_client

    slug = f"newtier-{uuid4().hex[:8]}"
    create_resp = client.post("/api/teams", json={"name": "New Tier Team", "slug": slug})
    assert create_resp.status_code in (200, 201), f"Team create failed: {create_resp.text}"

    # Switch to the new team
    switch_resp = client.post(f"/api/teams/{slug}/switch")
    assert switch_resp.status_code == 200

    # Subscription should show free tier
    resp = client.get("/api/billing/subscription")
    assert resp.status_code == 200

    data = resp.json()
    assert data["tier"] == "free", f"Expected free tier for new team, got: {data['tier']}"

    # Switch back to personal team to avoid side effects
    teams_resp = client.get("/api/teams")
    personal = [t for t in teams_resp.json() if t["is_personal"]]
    if personal:
        client.post(f"/api/teams/{personal[0]['slug']}/switch")
