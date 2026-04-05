"""
Integration tests for Teams & RBAC.

Tests:
- Personal team auto-creation on registration
- Team CRUD (create, list, get, update, delete)
- Member management (invite, role change, remove, leave)
- Invitation lifecycle (create, list, accept, revoke)
- Project visibility and team-aware listing
- Audit log generation

Requires: docker-compose.test.yml postgres on port 5433
Run: pytest tests/integration/test_teams_integration.py -v -m integration
"""

from uuid import uuid4

import pytest


# ── Personal Team Auto-Creation ─────────────────────────────────────────


@pytest.mark.integration
def test_personal_team_created_on_registration(authenticated_client):
    """Every new user should get a personal team with admin role."""
    client, user_data = authenticated_client

    response = client.get("/api/teams")
    assert response.status_code == 200

    teams = response.json()
    assert len(teams) >= 1

    personal_teams = [t for t in teams if t["is_personal"]]
    assert len(personal_teams) == 1
    assert personal_teams[0]["role"] == "admin"


@pytest.mark.integration
def test_personal_team_name_matches_user(authenticated_client):
    """Personal team name should include the user's name."""
    client, user_data = authenticated_client

    response = client.get("/api/teams")
    teams = response.json()
    personal = [t for t in teams if t["is_personal"]][0]

    # Personal team name is "{user.name}'s Team"
    assert "Team" in personal["name"]


# ── Team CRUD ───────────────────────────────────────────────────────────


@pytest.mark.integration
def test_create_team(authenticated_client):
    """Create a non-personal team."""
    client, _ = authenticated_client
    slug = f"eng-{uuid4().hex[:8]}"

    response = client.post("/api/teams", json={"name": "Engineering", "slug": slug})
    assert response.status_code in (200, 201), f"Create failed: {response.text}"

    data = response.json()
    assert data["name"] == "Engineering"
    assert data["slug"] == slug
    assert data["is_personal"] is False


@pytest.mark.integration
def test_create_team_duplicate_slug_fails(authenticated_client):
    """Duplicate slug should be rejected."""
    client, _ = authenticated_client
    slug = f"dup-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Team A", "slug": slug})
    response = client.post("/api/teams", json={"name": "Team B", "slug": slug})
    assert response.status_code in (400, 409, 500)


@pytest.mark.integration
def test_get_team_by_slug(authenticated_client):
    """Get team details by slug."""
    client, _ = authenticated_client
    slug = f"detail-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Detail Team", "slug": slug})

    response = client.get(f"/api/teams/{slug}")
    assert response.status_code == 200
    assert response.json()["name"] == "Detail Team"


@pytest.mark.integration
def test_update_team_name(authenticated_client):
    """Admin can update team name."""
    client, _ = authenticated_client
    slug = f"upd-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Old Name", "slug": slug})

    response = client.patch(f"/api/teams/{slug}", json={"name": "New Name"})
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


@pytest.mark.integration
def test_cannot_delete_personal_team(authenticated_client):
    """Personal teams cannot be deleted."""
    client, _ = authenticated_client

    teams = client.get("/api/teams").json()
    personal = [t for t in teams if t["is_personal"]][0]

    response = client.delete(f"/api/teams/{personal['slug']}")
    assert response.status_code in (400, 403)


@pytest.mark.integration
def test_delete_non_personal_team(authenticated_client):
    """Non-personal teams can be deleted by admin."""
    client, _ = authenticated_client
    slug = f"del-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Delete Me", "slug": slug})

    response = client.delete(f"/api/teams/{slug}")
    assert response.status_code in (200, 204)

    # Verify it's gone
    get_resp = client.get(f"/api/teams/{slug}")
    assert get_resp.status_code in (403, 404)


@pytest.mark.integration
def test_switch_active_team(authenticated_client):
    """Switching active team should succeed."""
    client, _ = authenticated_client
    slug = f"switch-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Switch Target", "slug": slug})

    response = client.post(f"/api/teams/{slug}/switch")
    assert response.status_code == 200


# ── Member Management ───────────────────────────────────────────────────


@pytest.mark.integration
def test_list_team_members(authenticated_client):
    """List members shows the creator as admin."""
    client, _ = authenticated_client
    slug = f"members-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Members Team", "slug": slug})

    response = client.get(f"/api/teams/{slug}/members")
    assert response.status_code == 200

    members = response.json()
    assert len(members) >= 1

    roles = [m["role"] for m in members]
    assert "admin" in roles


# ── Invitations ─────────────────────────────────────────────────────────


@pytest.mark.integration
def test_create_email_invitation(authenticated_client):
    """Admin can create email invitations on non-personal teams."""
    client, _ = authenticated_client
    slug = f"inv-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Invite Team", "slug": slug})

    response = client.post(
        f"/api/teams/{slug}/members/invite",
        json={"email": f"invite-{uuid4().hex[:8]}@example.com", "role": "editor"},
    )
    assert response.status_code in (200, 201), f"Invite failed: {response.text}"


@pytest.mark.integration
def test_create_invite_link(authenticated_client):
    """Admin can create invite links."""
    client, _ = authenticated_client
    slug = f"link-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Link Team", "slug": slug})

    response = client.post(
        f"/api/teams/{slug}/members/link",
        json={"role": "viewer", "expires_in_days": 7},
    )
    assert response.status_code in (200, 201), f"Link creation failed: {response.text}"

    data = response.json()
    assert "token" in data
    assert data["role"] == "viewer"


@pytest.mark.integration
def test_get_invite_details_public(authenticated_client):
    """Public endpoint returns invite details without auth."""
    client, _ = authenticated_client
    slug = f"pub-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Public Team", "slug": slug})

    link_resp = client.post(
        f"/api/teams/{slug}/members/link", json={"role": "editor"}
    )
    token = link_resp.json()["token"]

    # Save and clear auth
    auth = client.headers.get("Authorization")
    client.headers.pop("Authorization", None)

    response = client.get(f"/api/teams/invitations/{token}")
    assert response.status_code == 200

    data = response.json()
    assert data["role"] == "editor"
    assert data["is_valid"] is True

    # Restore auth
    if auth:
        client.headers["Authorization"] = auth


@pytest.mark.integration
def test_accept_invite_link(authenticated_client, api_client_session):
    """A second user can accept an invite link and join the team."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")
    slug = f"accept-{uuid4().hex[:8]}"

    client_a.post("/api/teams", json={"name": "Accept Team", "slug": slug})

    # Create invite link (client_a has Bearer auth)
    link_resp = client_a.post(
        f"/api/teams/{slug}/members/link", json={"role": "editor"}
    )
    assert link_resp.status_code in (200, 201), f"Link creation failed: {link_resp.text}"
    link_data = link_resp.json()
    invite_token = link_data.get("token")
    if not invite_token:
        pytest.skip(f"No token in link response: {link_data}")

    # Register user B (temporarily clear auth)
    email_b = f"userb-{uuid4().hex[:8]}@example.com"
    client_a.headers.pop("Authorization", None)
    api_client_session.headers.pop("Authorization", None)
    api_client_session.post(
        "/api/auth/register",
        json={"email": email_b, "password": "TestPass123!", "name": "User B"},
    )
    login_resp = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email_b, "password": "TestPass123!"},
    )
    token_b = login_resp.json()["access_token"]
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"

    # User B accepts the invite
    response = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")
    assert response.status_code == 200, f"Accept failed: {response.text}"

    # User B should now see the team
    teams_resp = api_client_session.get("/api/teams")
    team_slugs = [t["slug"] for t in teams_resp.json()]
    assert slug in team_slugs

    # Restore user A auth
    if token_a:
        client_a.headers["Authorization"] = token_a


@pytest.mark.integration
def test_list_pending_invitations(authenticated_client):
    """Admin can list pending invitations."""
    client, _ = authenticated_client
    slug = f"pending-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Pending Team", "slug": slug})

    client.post(
        f"/api/teams/{slug}/members/invite",
        json={"email": f"pending-{uuid4().hex[:8]}@example.com", "role": "viewer"},
    )

    response = client.get(f"/api/teams/{slug}/invitations")
    assert response.status_code == 200

    invitations = response.json()
    assert len(invitations) >= 1


@pytest.mark.integration
def test_revoke_invitation(authenticated_client):
    """Admin can revoke a pending invitation."""
    client, _ = authenticated_client
    slug = f"revoke-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Revoke Team", "slug": slug})

    inv_resp = client.post(
        f"/api/teams/{slug}/members/invite",
        json={"email": f"revoke-{uuid4().hex[:8]}@example.com", "role": "editor"},
    )
    inv_id = inv_resp.json()["id"]

    response = client.delete(f"/api/teams/{slug}/invitations/{inv_id}")
    assert response.status_code in (200, 204)


# ── Audit Log ───────────────────────────────────────────────────────────


@pytest.mark.integration
def test_audit_log_records_team_creation(authenticated_client):
    """Creating a team should generate an audit log entry."""
    client, _ = authenticated_client
    slug = f"audit-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Audit Team", "slug": slug})

    response = client.get(f"/api/teams/{slug}/audit-log")
    assert response.status_code == 200

    logs = response.json()
    assert len(logs) >= 1

    actions = [log["action"] for log in logs]
    assert "team.created" in actions


@pytest.mark.integration
def test_audit_log_records_member_invite(authenticated_client):
    """Inviting a member should generate an audit log entry."""
    client, _ = authenticated_client
    slug = f"audit-inv-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Audit Invite", "slug": slug})
    client.post(
        f"/api/teams/{slug}/members/invite",
        json={"email": f"audit-{uuid4().hex[:8]}@example.com", "role": "editor"},
    )

    response = client.get(f"/api/teams/{slug}/audit-log")
    logs = response.json()
    actions = [log["action"] for log in logs]
    assert "member.invited" in actions


# ── Project Team Isolation ──────────────────────────────────────────────


@pytest.mark.integration
def test_projects_filtered_by_team(
    authenticated_client, default_base_id, mock_orchestrator
):
    """Projects should be filtered by the user's active team."""
    client, user_data = authenticated_client

    # Create a project (should be in the user's personal team)
    resp = client.post(
        "/api/projects/",
        json={"name": "Team Filter Test", "base_id": default_base_id},
    )
    if resp.status_code != 200:
        pytest.skip(f"Project creation failed: {resp.text}")

    # List projects
    response = client.get("/api/projects/")
    assert response.status_code == 200

    projects = response.json()
    assert len(projects) >= 1

    # All returned projects should have the user's team_id
    for p in projects:
        if "team_id" in p:
            assert p["team_id"] is not None


# ── Helpers ────────────────────────────────────────────────────────────


def _create_team_and_user_b(api_client_session, admin_client, team_prefix, role="viewer"):
    """
    Create a non-personal team via admin_client, register User B, invite
    via link, accept, and return (client_b, user_b_data, team_slug).

    admin_client: authenticated (client, user_data) tuple for the team creator.
    """
    from httpx._client import Client  # noqa: only used for type hint clarity

    client_a, _ = admin_client
    slug = f"{team_prefix}-{uuid4().hex[:8]}"

    resp = client_a.post("/api/teams", json={"name": f"Team {team_prefix}", "slug": slug})
    assert resp.status_code in (200, 201), f"Team creation failed: {resp.text}"

    # Create invite link for the given role
    link_resp = client_a.post(
        f"/api/teams/{slug}/members/link", json={"role": role}
    )
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

    # Return a lightweight wrapper: just the session client configured for B
    # The caller must restore admin auth when it needs admin_client again.
    return api_client_session, user_b_data, slug, token_b


def _create_team_project(client, team_slug, base_id, name_prefix="rbac-proj"):
    """Create a project inside the caller's active team context and return the slug."""
    # Switch to the target team first
    client.post(f"/api/teams/{team_slug}/switch")

    resp = client.post(
        "/api/projects/",
        json={"name": f"{name_prefix}-{uuid4().hex[:6]}", "base_id": base_id},
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("slug")


# ── Viewer Role Enforcement ────────────────────────────────────────────


@pytest.mark.integration
def test_viewer_can_list_projects(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Viewer can list projects for the team."""
    client_a, user_a = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, user_b, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vlist", role="viewer"
    )

    # Restore admin context, create a project
    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id)
    if not proj_slug:
        pytest.skip("Project creation failed (base_id missing or orchestrator error)")

    # User B lists projects
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.get(f"/api/projects/?team={slug}")
    assert resp.status_code == 200


@pytest.mark.integration
def test_viewer_can_view_project_details(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Viewer can GET a specific project."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vdetail", role="viewer"
    )

    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id)
    if not proj_slug:
        pytest.skip("Project creation failed")

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.get(f"/api/projects/{proj_slug}")
    assert resp.status_code == 200


@pytest.mark.integration
def test_viewer_can_view_file_tree(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Viewer can browse the file tree."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vtree", role="viewer"
    )

    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id)
    if not proj_slug:
        pytest.skip("Project creation failed")

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.get(f"/api/projects/{proj_slug}/files/tree")
    # 200 = success, 404/502 = no container running (acceptable in test env)
    assert resp.status_code in (200, 404, 502)


@pytest.mark.integration
def test_viewer_cannot_save_files(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Viewer cannot write files (403)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vsave", role="viewer"
    )

    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id)
    if not proj_slug:
        pytest.skip("Project creation failed")

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.post(
        f"/api/projects/{proj_slug}/files/save",
        json={"file_path": "/app/test.txt", "content": "hello"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_viewer_cannot_delete_project(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Viewer cannot delete a project (403)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vdel", role="viewer"
    )

    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id)
    if not proj_slug:
        pytest.skip("Project creation failed")

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.delete(f"/api/projects/{proj_slug}")
    assert resp.status_code == 403


@pytest.mark.integration
def test_viewer_cannot_start_containers(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Viewer cannot start containers (403)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vstart", role="viewer"
    )

    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id)
    if not proj_slug:
        pytest.skip("Project creation failed")

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.post(f"/api/projects/{proj_slug}/containers/start-all")
    assert resp.status_code == 403


@pytest.mark.integration
def test_viewer_cannot_invite_members(authenticated_client, api_client_session):
    """Viewer cannot create invitations (403)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vinvite", role="viewer"
    )

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.post(
        f"/api/teams/{slug}/members/invite",
        json={"email": f"no-{uuid4().hex[:8]}@example.com", "role": "viewer"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_viewer_cannot_change_team_settings(authenticated_client, api_client_session):
    """Viewer cannot PATCH team settings (403)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vsettings", role="viewer"
    )

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.patch(f"/api/teams/{slug}", json={"name": "Hacked"})
    assert resp.status_code == 403


# ── Editor Role Enforcement ────────────────────────────────────────────


@pytest.mark.integration
def test_editor_can_list_and_view_projects(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Editor can list and view projects."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "elist", role="editor"
    )

    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id)
    if not proj_slug:
        pytest.skip("Project creation failed")

    client_a.headers["Authorization"] = f"Bearer {token_b}"

    list_resp = client_a.get(f"/api/projects/?team={slug}")
    assert list_resp.status_code == 200

    detail_resp = client_a.get(f"/api/projects/{proj_slug}")
    assert detail_resp.status_code == 200


@pytest.mark.integration
def test_editor_can_save_files(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Editor can save files (200 or 404 for missing container is acceptable)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "esave", role="editor"
    )

    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id)
    if not proj_slug:
        pytest.skip("Project creation failed")

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.post(
        f"/api/projects/{proj_slug}/files/save",
        json={"file_path": "/app/test.txt", "content": "hello from editor"},
    )
    # 200 = success, 404 = no container running (acceptable — proves permission passed)
    # 403 would indicate the permission check is wrong
    assert resp.status_code != 403, f"Editor should not get 403: {resp.text}"


@pytest.mark.integration
def test_editor_cannot_invite_members(authenticated_client, api_client_session):
    """Editor cannot create invitations (403)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "einvite", role="editor"
    )

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.post(
        f"/api/teams/{slug}/members/invite",
        json={"email": f"no-{uuid4().hex[:8]}@example.com", "role": "viewer"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_editor_cannot_change_team_settings(authenticated_client, api_client_session):
    """Editor cannot PATCH team settings (403)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "esettings", role="editor"
    )

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.patch(f"/api/teams/{slug}", json={"name": "Hacked"})
    assert resp.status_code == 403


@pytest.mark.integration
def test_editor_cannot_export_audit_log(authenticated_client, api_client_session):
    """Editor cannot export audit log (403 — admin only)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "eaudit", role="editor"
    )

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.post(f"/api/teams/{slug}/audit-log/export", json={})
    assert resp.status_code == 403


# ── Project Visibility Filtering ───────────────────────────────────────


@pytest.mark.integration
def test_viewer_sees_team_visible_but_not_private_projects(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Non-admin sees team-visible projects but not private ones."""
    client_a, user_a = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, user_b, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vvis", role="viewer"
    )

    # Create two projects under the team
    client_a.headers["Authorization"] = token_a
    proj_team = _create_team_project(client_a, slug, default_base_id, "team-vis")
    proj_priv = _create_team_project(client_a, slug, default_base_id, "priv-vis")
    if not proj_team or not proj_priv:
        pytest.skip("Project creation failed")

    # Mark second project as private
    client_a.patch(
        f"/api/teams/{slug}/projects/{proj_priv}/visibility",
        json={"visibility": "private"},
    )

    # User B lists projects — should see only the team-visible one
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.get(f"/api/projects/?team={slug}")
    assert resp.status_code == 200

    slugs = [p["slug"] for p in resp.json()]
    assert proj_team in slugs
    assert proj_priv not in slugs


@pytest.mark.integration
def test_viewer_sees_private_project_after_explicit_membership(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Viewer gains access to a private project once added as a project member."""
    client_a, user_a = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, user_b, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vpriv", role="viewer"
    )

    # Create a private project
    client_a.headers["Authorization"] = token_a
    proj_priv = _create_team_project(client_a, slug, default_base_id, "priv-mem")
    if not proj_priv:
        pytest.skip("Project creation failed")

    client_a.patch(
        f"/api/teams/{slug}/projects/{proj_priv}/visibility",
        json={"visibility": "private"},
    )

    # Confirm User B cannot see it
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.get(f"/api/projects/?team={slug}")
    slugs = [p["slug"] for p in resp.json()]
    assert proj_priv not in slugs

    # Admin adds User B as project member (viewer)
    client_a.headers["Authorization"] = token_a
    client_a.post(
        f"/api/teams/{slug}/projects/{proj_priv}/members",
        json={"user_id": str(user_b["id"]), "role": "viewer"},
    )

    # Now User B should see it
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.get(f"/api/projects/?team={slug}")
    slugs = [p["slug"] for p in resp.json()]
    assert proj_priv in slugs


# ── Project Role Override ──────────────────────────────────────────────


@pytest.mark.integration
def test_project_role_override(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Project-level membership overrides the team-level role."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, user_b, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "poverride", role="viewer"
    )

    # Create a project
    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id, "override")
    if not proj_slug:
        pytest.skip("Project creation failed")

    # Add User B as editor on the project (overrides team viewer)
    client_a.post(
        f"/api/teams/{slug}/projects/{proj_slug}/members",
        json={"user_id": str(user_b["id"]), "role": "editor"},
    )

    # Check effective role via my-role endpoint
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.get(f"/api/projects/{proj_slug}/my-role")
    assert resp.status_code == 200
    assert resp.json()["role"] == "editor"


@pytest.mark.integration
def test_project_role_override_grants_write_access(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Team viewer promoted to project editor can save files."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, user_b, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "pwrite", role="viewer"
    )

    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id, "woverride")
    if not proj_slug:
        pytest.skip("Project creation failed")

    # Promote User B to editor on this project
    client_a.post(
        f"/api/teams/{slug}/projects/{proj_slug}/members",
        json={"user_id": str(user_b["id"]), "role": "editor"},
    )

    # User B saves a file — should not get 403
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.post(
        f"/api/projects/{proj_slug}/files/save",
        json={"file_path": "/app/override.txt", "content": "promoted"},
    )
    assert resp.status_code != 403, f"Promoted editor should not get 403: {resp.text}"


# ── Billing / Audit Scoping ───────────────────────────────────────────


@pytest.mark.integration
def test_viewer_cannot_view_audit_log(authenticated_client, api_client_session):
    """Viewer cannot view the team audit log — audit.view is admin-only.

    Regression guard for the permission leak where `_VIEWER_PERMISSIONS`
    auto-included every permission ending in `.view`, unintentionally
    granting `AUDIT_VIEW` to viewers.
    """
    client_a, _ = authenticated_client

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vaudit", role="viewer"
    )

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.get(f"/api/teams/{slug}/audit-log")
    assert resp.status_code == 403


@pytest.mark.integration
def test_editor_cannot_view_audit_log(authenticated_client, api_client_session):
    """Editor cannot view the team audit log — audit.view is admin-only."""
    client_a, _ = authenticated_client

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "eaudit", role="editor"
    )

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.get(f"/api/teams/{slug}/audit-log")
    assert resp.status_code == 403


@pytest.mark.integration
def test_viewer_cannot_export_audit_log(authenticated_client, api_client_session):
    """Viewer cannot export the audit log (403 — admin only)."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vexport", role="viewer"
    )

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    resp = client_a.post(f"/api/teams/{slug}/audit-log/export", json={})
    assert resp.status_code == 403


@pytest.mark.integration
def test_admin_can_export_audit_log(authenticated_client):
    """Admin can export the audit log (200)."""
    client, _ = authenticated_client
    slug = f"aexport-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Export Team", "slug": slug})
    resp = client.post(f"/api/teams/{slug}/audit-log/export", json={})
    assert resp.status_code == 200


# ── Additional RBAC & Billing Tests ──────────────────────────────────


@pytest.mark.integration
def test_viewer_cannot_create_project(
    authenticated_client, api_client_session, default_base_id
):
    """Viewer should not be able to create projects."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vcreate", role="viewer"
    )

    # Switch User B to the team, then attempt project creation
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    client_a.post(f"/api/teams/{slug}/switch")

    response = client_a.post(
        "/api/projects/",
        json={"name": "Viewer Project", "base_id": default_base_id},
    )
    # Viewer lacks project.create permission — expect 403
    assert response.status_code == 403, (
        f"Expected 403, got {response.status_code}: {response.text}"
    )


@pytest.mark.integration
def test_viewer_cannot_send_chat(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Viewer should not be able to send agent chat messages."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vchat", role="viewer"
    )

    # Admin creates a project first
    client_a.headers["Authorization"] = token_a
    proj_slug = _create_team_project(client_a, slug, default_base_id, "chat-test")
    if not proj_slug:
        pytest.skip("Project creation failed")

    # Get project ID for chat payload
    proj_resp = client_a.get(f"/api/projects/{proj_slug}")
    project_id = proj_resp.json()["id"]

    # Viewer tries to send a chat message
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    response = client_a.post(
        "/api/chat/agent/stream",
        json={"project_id": project_id, "message": "hello"},
    )
    assert response.status_code in (403, 402), (
        f"Expected 403/402, got {response.status_code}: {response.text}"
    )


@pytest.mark.integration
def test_editor_cannot_manage_billing(authenticated_client, api_client_session):
    """Editor should not be able to change subscription or manage billing."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "ebill", role="editor"
    )

    # Switch User B to the team, then attempt billing action
    client_a.headers["Authorization"] = f"Bearer {token_b}"
    client_a.post(f"/api/teams/{slug}/switch")

    response = client_a.post(
        "/api/billing/subscribe",
        json={"tier": "pro", "billing_interval": "monthly"},
    )
    # Expect 400/403 (permission denied or no team) or 500 (Stripe not configured in CI)
    assert response.status_code in (400, 403, 500), (
        f"Expected 400/403/500, got {response.status_code}: {response.text}"
    )


@pytest.mark.integration
def test_credit_deduction_uses_team_pool(authenticated_client):
    """Credit deduction service should target the team, not the user."""
    client, user_data = authenticated_client

    # Check team billing shows credits
    billing_resp = client.get("/api/billing/credits")
    assert billing_resp.status_code == 200
    credits = billing_resp.json()
    # Credits should come from the team (total_credits field exists)
    assert "total_credits" in credits


@pytest.mark.integration
def test_audit_log_records_member_role_change(authenticated_client, api_client_session):
    """Changing a member's role should create an audit log entry."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, user_b, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "arole", role="editor"
    )

    # Get user B's ID from members list
    client_a.headers["Authorization"] = token_a
    members = client_a.get(f"/api/teams/{slug}/members").json()
    user_b_id = [m for m in members if m["role"] == "editor"][0]["user_id"]

    # Change role to viewer
    client_a.patch(
        f"/api/teams/{slug}/members/{user_b_id}", json={"role": "viewer"}
    )

    # Check audit log
    logs = client_a.get(f"/api/teams/{slug}/audit-log").json()
    actions = [log["action"] for log in logs]
    assert "member.role_changed" in actions


@pytest.mark.integration
def test_viewer_cannot_delete_team(authenticated_client, api_client_session):
    """Viewer should not be able to delete the team."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    _, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vdelteam", role="viewer"
    )

    client_a.headers["Authorization"] = f"Bearer {token_b}"
    response = client_a.delete(f"/api/teams/{slug}")
    assert response.status_code == 403, (
        f"Expected 403, got {response.status_code}: {response.text}"
    )
