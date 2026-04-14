"""
Integration tests for RBAC edge cases (PRD Section 12).

Tests:
- Sole admin cannot leave team
- Admin can leave after promoting another admin
- Invite existing member rejected (409)
- Link invite max_uses enforcement
- Expired invite rejection
- Removed user loses project access
- Private project invisible to editor without membership
- Editor who creates project becomes project admin

Requires: docker-compose.test.yml postgres on port 5433
Run: pytest tests/integration/test_rbac_edge_cases.py -v -m integration
"""

from uuid import uuid4

import pytest

# ── Helpers ────────────────────────────────────────────────────────────


def _create_team_and_user_b(api_client_session, admin_client, team_prefix, role="viewer"):
    """
    Create a non-personal team via admin_client, register User B, invite
    via link, accept, and return (client_b, user_b_data, team_slug, token_b).

    admin_client: authenticated (client, user_data) tuple for the team creator.
    """
    client_a, _ = admin_client
    slug = f"{team_prefix}-{uuid4().hex[:8]}"

    resp = client_a.post("/api/teams", json={"name": f"Team {team_prefix}", "slug": slug})
    assert resp.status_code in (200, 201), f"Team creation failed: {resp.text}"

    # Create invite link for the given role
    link_resp = client_a.post(f"/api/teams/{slug}/members/link", json={"role": role})
    assert link_resp.status_code in (200, 201), f"Link creation failed: {link_resp.text}"
    invite_token = link_resp.json()["token"]

    # Register User B with a fresh session-scoped client
    email_b = f"userb-{uuid4().hex[:8]}@example.com"
    api_client_session.headers.pop("Authorization", None)
    reg = api_client_session.post(
        "/api/auth/register",
        json={"email": email_b, "password": "TestPass123!", "name": "User B"},
    )
    assert reg.status_code == 201, f"Register B failed: {reg.text}"
    user_b_data = reg.json()

    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email_b, "password": "TestPass123!"},
    )
    assert login.status_code == 200, f"Login B failed: {login.text}"
    token_b = login.json()["access_token"]

    # Accept invite as User B
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    accept = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")
    assert accept.status_code == 200, f"Accept failed: {accept.text}"

    return api_client_session, user_b_data, slug, token_b


def _register_user(api_client_session, name="User"):
    """Register a new user, login, and return (user_data, token)."""
    email = f"{name.lower().replace(' ', '')}-{uuid4().hex[:8]}@example.com"
    api_client_session.headers.pop("Authorization", None)

    reg = api_client_session.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "name": name},
    )
    assert reg.status_code == 201, f"Register {name} failed: {reg.text}"
    user_data = reg.json()

    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email, "password": "TestPass123!"},
    )
    assert login.status_code == 200, f"Login {name} failed: {login.text}"
    token = login.json()["access_token"]

    return user_data, token


def _create_team_project(client, team_slug, base_id, name_prefix="edge-proj"):
    """Create a project inside the caller's active team context and return the slug."""
    client.post(f"/api/teams/{team_slug}/switch")

    resp = client.post(
        "/api/projects/",
        json={"name": f"{name_prefix}-{uuid4().hex[:6]}", "base_id": base_id},
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("slug")


# ── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_sole_admin_cannot_leave_team(authenticated_client):
    """Sole admin of a team should be blocked from leaving."""
    client, _ = authenticated_client
    slug = f"sole-admin-{uuid4().hex[:8]}"

    resp = client.post("/api/teams", json={"name": "Sole Admin Team", "slug": slug})
    assert resp.status_code in (200, 201), f"Team creation failed: {resp.text}"

    # Try to leave as the only admin
    leave_resp = client.post(f"/api/teams/{slug}/leave")
    assert leave_resp.status_code in (400, 403), (
        f"Expected 400/403 for sole admin leave, got {leave_resp.status_code}: {leave_resp.text}"
    )

    # Verify error message mentions sole admin
    detail = leave_resp.json().get("detail", "")
    assert "sole admin" in detail.lower() or "admin" in detail.lower(), (
        f"Expected error about sole admin, got: {detail}"
    )


@pytest.mark.integration
def test_admin_can_leave_after_promoting_another(authenticated_client, api_client_session):
    """Admin can leave once another admin exists."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    # Create team and invite User B as editor
    _, user_b, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "promo-leave", role="editor"
    )

    # Restore admin auth
    client_a.headers["Authorization"] = token_a

    # Get User B's ID from members list
    members_resp = client_a.get(f"/api/teams/{slug}/members")
    assert members_resp.status_code == 200
    members = members_resp.json()
    user_b_member = [m for m in members if m["role"] == "editor"]
    assert len(user_b_member) > 0, "User B not found as editor in members"
    user_b_id = user_b_member[0]["user_id"]

    # Promote User B to admin
    promote_resp = client_a.patch(f"/api/teams/{slug}/members/{user_b_id}", json={"role": "admin"})
    assert promote_resp.status_code == 200, f"Promote failed: {promote_resp.text}"

    # Now original admin should be able to leave
    leave_resp = client_a.post(f"/api/teams/{slug}/leave")
    assert leave_resp.status_code == 200, (
        f"Expected 200 for leave after promoting another admin, got {leave_resp.status_code}: {leave_resp.text}"
    )


@pytest.mark.integration
def test_invite_existing_member_rejected(authenticated_client, api_client_session):
    """Inviting an already-joined member by email should return 409."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    # Create team and invite User B (who joins)
    email_b = f"userb-{uuid4().hex[:8]}@example.com"
    slug = f"dup-invite-{uuid4().hex[:8]}"

    client_a.post("/api/teams", json={"name": "Dup Invite Team", "slug": slug})

    # Create invite link
    link_resp = client_a.post(f"/api/teams/{slug}/members/link", json={"role": "editor"})
    assert link_resp.status_code in (200, 201), f"Link creation failed: {link_resp.text}"
    invite_token = link_resp.json()["token"]

    # Register and login User B
    api_client_session.headers.pop("Authorization", None)
    reg = api_client_session.post(
        "/api/auth/register",
        json={"email": email_b, "password": "TestPass123!", "name": "User B"},
    )
    assert reg.status_code == 201, f"Register B failed: {reg.text}"

    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email_b, "password": "TestPass123!"},
    )
    assert login.status_code == 200, f"Login B failed: {login.text}"
    token_b = login.json()["access_token"]

    # User B accepts invite
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    accept = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")
    assert accept.status_code == 200, f"Accept failed: {accept.text}"

    # Restore admin auth and try to send email invite to the SAME email
    client_a.headers["Authorization"] = token_a
    invite_resp = client_a.post(
        f"/api/teams/{slug}/members/invite",
        json={"email": email_b, "role": "viewer"},
    )
    assert invite_resp.status_code == 409, (
        f"Expected 409 for existing member invite, got {invite_resp.status_code}: {invite_resp.text}"
    )

    detail = invite_resp.json().get("detail", "")
    assert "already" in detail.lower(), f"Expected 'already a member' detail, got: {detail}"


@pytest.mark.integration
def test_link_invite_max_uses_enforced(authenticated_client, api_client_session):
    """Link invite with max_uses=1 should reject the second acceptance."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")
    slug = f"maxuse-{uuid4().hex[:8]}"

    client_a.post("/api/teams", json={"name": "MaxUse Team", "slug": slug})

    # Create invite link with max_uses=1
    link_resp = client_a.post(
        f"/api/teams/{slug}/members/link", json={"role": "viewer", "max_uses": 1}
    )
    assert link_resp.status_code in (200, 201), f"Link creation failed: {link_resp.text}"
    invite_token = link_resp.json()["token"]

    # Register and login User B
    user_b_data, token_b = _register_user(api_client_session, "User B MaxUse")

    # User B accepts (should succeed — first use)
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    accept_b = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")
    assert accept_b.status_code == 200, f"User B accept failed: {accept_b.text}"

    # Register and login User C
    user_c_data, token_c = _register_user(api_client_session, "User C MaxUse")

    # User C tries to accept the same link (should fail — max uses reached)
    api_client_session.headers["Authorization"] = f"Bearer {token_c}"
    accept_c = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")
    assert accept_c.status_code == 410, (
        f"Expected 410 for max uses exceeded, got {accept_c.status_code}: {accept_c.text}"
    )

    detail = accept_c.json().get("detail", "")
    assert "maximum" in detail.lower() or "max" in detail.lower(), (
        f"Expected max uses error, got: {detail}"
    )

    # Restore admin auth
    client_a.headers["Authorization"] = token_a


@pytest.mark.integration
def test_expired_invite_rejected(authenticated_client, api_client_session):
    """Expired invites should be rejected. Skipped if time-based expiry cannot be tested."""
    client_a, _ = authenticated_client
    slug = f"expire-{uuid4().hex[:8]}"

    client_a.post("/api/teams", json={"name": "Expire Team", "slug": slug})

    # Try to create an invite link with expires_in_days=0 to get immediate expiry
    link_resp = client_a.post(
        f"/api/teams/{slug}/members/link",
        json={"role": "viewer", "expires_in_days": 0},
    )

    # If the API rejects expires_in_days=0 (validation error), we cannot test this
    if link_resp.status_code not in (200, 201):
        pytest.skip(
            "Cannot test time-based expiry in integration tests: "
            f"API rejected expires_in_days=0 ({link_resp.status_code}: {link_resp.text})"
        )

    invite_token = link_resp.json().get("token")
    if not invite_token:
        pytest.skip("No token returned for zero-day invite")

    # Register User B and attempt to accept the expired invite
    user_b_data, token_b = _register_user(api_client_session, "User B Expire")

    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    accept_resp = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")

    # Should be 410 (expired) — but if the server creates it with expires_at in the past,
    # acceptance should fail
    assert accept_resp.status_code in (410, 400), (
        f"Expected 410/400 for expired invite, got {accept_resp.status_code}: {accept_resp.text}"
    )


@pytest.mark.integration
def test_removed_user_loses_project_access(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """A member removed from a team should lose access to team projects."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    # Create team and invite User B as editor
    _, user_b, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "rm-access", role="editor"
    )

    # Restore admin, create project
    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id, "rm-proj")
    if not proj_slug:
        pytest.skip("Project creation failed (base_id missing or orchestrator error)")

    # Verify User B can access the project
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    client_a.post(f"/api/teams/{slug}/switch")
    resp = client_a.get(f"/api/projects/{proj_slug}")
    assert resp.status_code == 200, (
        f"User B should be able to access project before removal, got {resp.status_code}: {resp.text}"
    )

    # Restore admin auth, get User B's ID, remove them
    client_a.headers["Authorization"] = token_a
    members = client_a.get(f"/api/teams/{slug}/members").json()
    user_b_id = [m for m in members if m["role"] == "editor"][0]["user_id"]

    remove_resp = client_a.delete(f"/api/teams/{slug}/members/{user_b_id}")
    assert remove_resp.status_code in (200, 204), f"Remove member failed: {remove_resp.text}"

    # User B tries to access the project again — should be denied
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.get(f"/api/projects/{proj_slug}")
    assert resp.status_code in (403, 404), (
        f"Expected 403/404 after removal, got {resp.status_code}: {resp.text}"
    )

    # Restore admin auth
    client_a.headers["Authorization"] = token_a


@pytest.mark.integration
def test_private_project_invisible_to_editor_without_membership(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Editor should see team-visible projects but not private ones (without explicit membership)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    # Create team and invite User B as editor
    _, user_b, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "priv-vis", role="editor"
    )

    # Restore admin, create two projects
    client_a.headers["Authorization"] = token_a
    proj_team = _create_team_project(client_a, slug, default_base_id, "team-vis")
    proj_priv = _create_team_project(client_a, slug, default_base_id, "priv-vis")
    if not proj_team or not proj_priv:
        pytest.skip("Project creation failed (base_id missing or orchestrator error)")

    # Mark second project as private
    client_a.patch(
        f"/api/teams/{slug}/projects/{proj_priv}/visibility",
        json={"visibility": "private"},
    )

    # User B lists projects — should see team-visible but not private
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    client_a.post(f"/api/teams/{slug}/switch")
    resp = client_a.get(f"/api/projects/?team={slug}")
    assert resp.status_code == 200

    slugs = [p["slug"] for p in resp.json()]
    assert proj_team in slugs, f"Editor should see team-visible project, got slugs: {slugs}"
    assert proj_priv not in slugs, f"Editor should NOT see private project, got slugs: {slugs}"

    # Restore admin auth
    client_a.headers["Authorization"] = token_a


@pytest.mark.integration
def test_editor_creates_project_becomes_project_admin(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Editor who creates a project should become project admin (creator privilege)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    # Create team and invite User B as editor
    _, user_b, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "ecreate", role="editor"
    )

    # User B switches to the team and creates a project
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    client_a.post(f"/api/teams/{slug}/switch")

    proj_name = f"editor-proj-{uuid4().hex[:6]}"
    create_resp = client_a.post(
        "/api/projects/",
        json={"name": proj_name, "base_id": default_base_id},
    )
    if create_resp.status_code != 200:
        pytest.skip(
            f"Project creation by editor failed ({create_resp.status_code}): {create_resp.text}"
        )

    proj_slug = create_resp.json().get("slug")
    if not proj_slug:
        pytest.skip("No slug in project creation response")

    # Check User B's role on the project — should be admin as project creator
    role_resp = client_a.get(f"/api/projects/{proj_slug}/my-role")
    assert role_resp.status_code == 200, (
        f"my-role endpoint failed: {role_resp.status_code}: {role_resp.text}"
    )

    role_data = role_resp.json()
    assert role_data.get("role") == "admin", (
        f"Expected project creator to have 'admin' role, got: {role_data}"
    )

    # Restore admin auth
    client_a.headers["Authorization"] = token_a
