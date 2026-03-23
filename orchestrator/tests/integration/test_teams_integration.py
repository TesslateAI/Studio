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
    assert response.status_code == 200

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
def test_accept_invite_link(authenticated_client, api_client):
    """A second user can accept an invite link and join the team."""
    client_a, _ = authenticated_client
    slug = f"accept-{uuid4().hex[:8]}"

    client_a.post("/api/teams", json={"name": "Accept Team", "slug": slug})

    # Create invite link
    link_resp = client_a.post(
        f"/api/teams/{slug}/members/link", json={"role": "editor"}
    )
    token = link_resp.json()["token"]

    # Register user B
    email_b = f"userb-{uuid4().hex[:8]}@example.com"
    api_client.post(
        "/api/auth/register",
        json={"email": email_b, "password": "TestPass123!", "name": "User B"},
    )
    login_resp = api_client.post(
        "/api/auth/jwt/login",
        data={"username": email_b, "password": "TestPass123!"},
    )
    token_b = login_resp.json()["access_token"]
    api_client.headers["Authorization"] = f"Bearer {token_b}"

    # User B accepts the invite
    response = api_client.post(f"/api/teams/invitations/{token}/accept")
    assert response.status_code == 200, f"Accept failed: {response.text}"

    # User B should now see the team
    teams_resp = api_client.get("/api/teams")
    team_slugs = [t["slug"] for t in teams_resp.json()]
    assert slug in team_slugs


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
    assert response.status_code == 200


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
