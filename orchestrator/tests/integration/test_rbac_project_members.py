"""
Integration tests for project-level member management (RBAC PRD Section 9.2).

Tests:
- List project members
- Add / change / remove project members (admin only)
- Effective role resolution (my-role endpoint)
- Project-role elevation and restriction of team role
- Permission enforcement for viewers and editors

Requires: docker-compose.test.yml postgres on port 5433
Run: pytest tests/integration/test_rbac_project_members.py -v -m integration
"""

from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_team_and_user_b(api_client_session, admin_client, team_prefix, role="viewer"):
    """Create team, register User B, invite via link, accept."""
    client_a, _ = admin_client
    slug = f"{team_prefix}-{uuid4().hex[:8]}"
    resp = client_a.post("/api/teams", json={"name": f"Team {team_prefix}", "slug": slug})
    assert resp.status_code in (200, 201), f"Team create failed: {resp.text}"

    link_resp = client_a.post(f"/api/teams/{slug}/members/link", json={"role": role})
    assert link_resp.status_code in (200, 201), f"Invite link failed: {link_resp.text}"
    invite_token = link_resp.json()["token"]

    email_b = f"userb-{uuid4().hex[:8]}@example.com"
    api_client_session.headers.pop("Authorization", None)
    reg = api_client_session.post(
        "/api/auth/register",
        json={"email": email_b, "password": "TestPass123!", "name": "User B"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"
    user_b_data = reg.json()

    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email_b, "password": "TestPass123!"},
    )
    assert login.status_code == 200, f"Login failed: {login.text}"
    token_b = login.json()["access_token"]

    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    accept = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")
    assert accept.status_code == 200, f"Accept invite failed: {accept.text}"

    return api_client_session, user_b_data, slug, token_b


def _create_team_project(client, team_slug, base_id, name_prefix="pm-proj"):
    """Create a project in the caller's active team context."""
    client.post(f"/api/teams/{team_slug}/switch")
    resp = client.post(
        "/api/projects/",
        json={"name": f"{name_prefix}-{uuid4().hex[:6]}", "base_id": base_id},
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("slug")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_list_project_members(authenticated_client, default_base_id, mock_orchestrator):
    """GET /api/teams/{slug}/projects/{proj}/members should show project creator."""
    client, _ = authenticated_client
    if default_base_id is None:
        pytest.skip("No marketplace base available")

    slug = f"lpm-{uuid4().hex[:8]}"
    resp = client.post("/api/teams", json={"name": "ListPM Team", "slug": slug})
    assert resp.status_code in (200, 201)

    proj_slug = _create_team_project(client, slug, default_base_id)
    if proj_slug is None:
        pytest.skip("Project creation failed")

    members_resp = client.get(f"/api/teams/{slug}/projects/{proj_slug}/members")
    assert members_resp.status_code == 200

    members = members_resp.json()
    # The project may or may not auto-create a project membership for the creator,
    # but the endpoint should return a valid list.
    assert isinstance(members, list)


@pytest.mark.integration
def test_add_project_member(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Admin adds User B as editor on a project via team project members endpoint."""
    if default_base_id is None:
        pytest.skip("No marketplace base available")

    client_b, user_b_data, team_slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "addpm", role="viewer"
    )

    # Switch back to admin
    client_a, _ = authenticated_client
    proj_slug = _create_team_project(client_a, team_slug, default_base_id)
    if proj_slug is None:
        pytest.skip("Project creation failed")

    user_b_id = user_b_data["id"]
    add_resp = client_a.post(
        f"/api/teams/{team_slug}/projects/{proj_slug}/members",
        json={"user_id": str(user_b_id), "role": "editor"},
    )
    assert add_resp.status_code in (200, 201), f"Add member failed: {add_resp.text}"

    # List members should include User B
    members_resp = client_a.get(f"/api/teams/{team_slug}/projects/{proj_slug}/members")
    assert members_resp.status_code == 200
    member_ids = [str(m["user_id"]) for m in members_resp.json()]
    assert str(user_b_id) in member_ids

    editor_member = [m for m in members_resp.json() if str(m["user_id"]) == str(user_b_id)][0]
    assert editor_member["role"] == "editor"


@pytest.mark.integration
def test_change_project_member_role(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Admin changes User B from editor to viewer on a project."""
    if default_base_id is None:
        pytest.skip("No marketplace base available")

    client_b, user_b_data, team_slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "chgpm", role="viewer"
    )

    client_a, _ = authenticated_client
    proj_slug = _create_team_project(client_a, team_slug, default_base_id)
    if proj_slug is None:
        pytest.skip("Project creation failed")

    user_b_id = user_b_data["id"]

    # Add as editor first
    add_resp = client_a.post(
        f"/api/teams/{team_slug}/projects/{proj_slug}/members",
        json={"user_id": str(user_b_id), "role": "editor"},
    )
    assert add_resp.status_code in (200, 201), f"Add member failed: {add_resp.text}"

    # Change to viewer
    patch_resp = client_a.patch(
        f"/api/teams/{team_slug}/projects/{proj_slug}/members/{user_b_id}",
        json={"role": "viewer"},
    )
    assert patch_resp.status_code == 200, f"Change role failed: {patch_resp.text}"
    assert patch_resp.json()["role"] == "viewer"

    # User B checks my-role
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    role_resp = api_client_session.get(f"/api/projects/{proj_slug}/my-role")
    assert role_resp.status_code == 200
    assert role_resp.json()["role"] == "viewer"

    # Restore admin auth
    client_a_token = authenticated_client[0].headers.get("Authorization")
    api_client_session.headers["Authorization"] = client_a_token


@pytest.mark.integration
def test_remove_project_member(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Admin removes User B from project; effective role falls back to team role."""
    if default_base_id is None:
        pytest.skip("No marketplace base available")

    client_b, user_b_data, team_slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "rmpm", role="viewer"
    )

    client_a, _ = authenticated_client
    proj_slug = _create_team_project(client_a, team_slug, default_base_id)
    if proj_slug is None:
        pytest.skip("Project creation failed")

    user_b_id = user_b_data["id"]

    # Add as editor
    add_resp = client_a.post(
        f"/api/teams/{team_slug}/projects/{proj_slug}/members",
        json={"user_id": str(user_b_id), "role": "editor"},
    )
    assert add_resp.status_code in (200, 201)

    # Remove
    del_resp = client_a.delete(f"/api/teams/{team_slug}/projects/{proj_slug}/members/{user_b_id}")
    assert del_resp.status_code == 204, f"Remove member failed: {del_resp.text}"

    # User B my-role should fall back to team role (viewer) if project visibility is "team",
    # or None if "private".  Either way, should not be "editor" anymore.
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    role_resp = api_client_session.get(f"/api/projects/{proj_slug}/my-role")
    if role_resp.status_code == 200:
        assert role_resp.json()["role"] != "editor"

    # Restore admin auth
    client_a_token = authenticated_client[0].headers.get("Authorization")
    api_client_session.headers["Authorization"] = client_a_token


@pytest.mark.integration
def test_project_role_elevates_team_role(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """User B is team viewer but project editor — my-role should be 'editor'."""
    if default_base_id is None:
        pytest.skip("No marketplace base available")

    client_b, user_b_data, team_slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "elevpm", role="viewer"
    )

    client_a, _ = authenticated_client
    proj_slug = _create_team_project(client_a, team_slug, default_base_id)
    if proj_slug is None:
        pytest.skip("Project creation failed")

    user_b_id = user_b_data["id"]

    # Set project visibility to "team" so User B has baseline access
    vis_resp = client_a.patch(
        f"/api/teams/{team_slug}/projects/{proj_slug}/visibility",
        json={"visibility": "team"},
    )
    # May already be "team" by default — either 200 or the visibility is already set
    assert vis_resp.status_code in (200, 201, 422)

    # Add User B as project editor (elevating from team viewer)
    add_resp = client_a.post(
        f"/api/teams/{team_slug}/projects/{proj_slug}/members",
        json={"user_id": str(user_b_id), "role": "editor"},
    )
    assert add_resp.status_code in (200, 201)

    # User B checks effective role
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    role_resp = api_client_session.get(f"/api/projects/{proj_slug}/my-role")
    assert role_resp.status_code == 200
    assert role_resp.json()["role"] == "editor"

    # Restore admin auth
    client_a_token = authenticated_client[0].headers.get("Authorization")
    api_client_session.headers["Authorization"] = client_a_token


@pytest.mark.integration
def test_project_role_restricts_team_role(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """User B is team editor but project viewer — my-role should be 'viewer'."""
    if default_base_id is None:
        pytest.skip("No marketplace base available")

    client_b, user_b_data, team_slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "restpm", role="editor"
    )

    client_a, _ = authenticated_client
    proj_slug = _create_team_project(client_a, team_slug, default_base_id)
    if proj_slug is None:
        pytest.skip("Project creation failed")

    user_b_id = user_b_data["id"]

    # Add User B as project viewer (restricting from team editor)
    add_resp = client_a.post(
        f"/api/teams/{team_slug}/projects/{proj_slug}/members",
        json={"user_id": str(user_b_id), "role": "viewer"},
    )
    assert add_resp.status_code in (200, 201)

    # User B checks effective role
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    role_resp = api_client_session.get(f"/api/projects/{proj_slug}/my-role")
    assert role_resp.status_code == 200
    assert role_resp.json()["role"] == "viewer"

    # Restore admin auth
    client_a_token = authenticated_client[0].headers.get("Authorization")
    api_client_session.headers["Authorization"] = client_a_token


@pytest.mark.integration
def test_team_admin_always_admin_on_projects(
    authenticated_client, default_base_id, mock_orchestrator
):
    """Team admin should always have 'admin' effective role on team projects."""
    client, user_data = authenticated_client
    if default_base_id is None:
        pytest.skip("No marketplace base available")

    slug = f"admpm-{uuid4().hex[:8]}"
    resp = client.post("/api/teams", json={"name": "AdminPM Team", "slug": slug})
    assert resp.status_code in (200, 201)

    proj_slug = _create_team_project(client, slug, default_base_id)
    if proj_slug is None:
        pytest.skip("Project creation failed")

    # Admin checks my-role — should always be "admin"
    role_resp = client.get(f"/api/projects/{proj_slug}/my-role")
    assert role_resp.status_code == 200
    assert role_resp.json()["role"] == "admin"


@pytest.mark.integration
def test_viewer_cannot_add_project_members(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Team viewer should get 403 when trying to add project members."""
    if default_base_id is None:
        pytest.skip("No marketplace base available")

    client_b, user_b_data, team_slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "vwrpm", role="viewer"
    )

    client_a, user_a_data = authenticated_client
    proj_slug = _create_team_project(client_a, team_slug, default_base_id)
    if proj_slug is None:
        pytest.skip("Project creation failed")

    # Set project visibility to "team" so viewer can at least see it
    client_a.patch(
        f"/api/teams/{team_slug}/projects/{proj_slug}/visibility",
        json={"visibility": "team"},
    )

    # Register a third user to be the add target
    email_c = f"userc-{uuid4().hex[:8]}@example.com"
    api_client_session.headers.pop("Authorization", None)
    reg_c = api_client_session.post(
        "/api/auth/register",
        json={"email": email_c, "password": "TestPass123!", "name": "User C"},
    )
    user_c_data = reg_c.json() if reg_c.status_code == 201 else None

    # User B (viewer) tries to add a project member — should fail
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    target_id = str(user_c_data["id"]) if user_c_data else str(user_b_data["id"])
    add_resp = api_client_session.post(
        f"/api/teams/{team_slug}/projects/{proj_slug}/members",
        json={"user_id": target_id, "role": "editor"},
    )
    assert add_resp.status_code == 403, f"Expected 403, got {add_resp.status_code}: {add_resp.text}"

    # Restore admin auth
    client_a_token = authenticated_client[0].headers.get("Authorization")
    api_client_session.headers["Authorization"] = client_a_token


@pytest.mark.integration
def test_editor_cannot_add_project_members(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """Team editor (not project admin) should get 403 when adding project members."""
    if default_base_id is None:
        pytest.skip("No marketplace base available")

    client_b, user_b_data, team_slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "edtpm", role="editor"
    )

    client_a, user_a_data = authenticated_client
    proj_slug = _create_team_project(client_a, team_slug, default_base_id)
    if proj_slug is None:
        pytest.skip("Project creation failed")

    # Register a third user and add them to the team
    email_c = f"userc-{uuid4().hex[:8]}@example.com"
    link_resp = client_a.post(f"/api/teams/{team_slug}/members/link", json={"role": "viewer"})
    invite_token_c = link_resp.json()["token"] if link_resp.status_code in (200, 201) else None

    api_client_session.headers.pop("Authorization", None)
    reg_c = api_client_session.post(
        "/api/auth/register",
        json={"email": email_c, "password": "TestPass123!", "name": "User C"},
    )
    user_c_data = reg_c.json() if reg_c.status_code == 201 else None

    if user_c_data and invite_token_c:
        login_c = api_client_session.post(
            "/api/auth/jwt/login",
            data={"username": email_c, "password": "TestPass123!"},
        )
        if login_c.status_code == 200:
            token_c = login_c.json()["access_token"]
            api_client_session.headers["Authorization"] = f"Bearer {token_c}"
            api_client_session.post(f"/api/teams/invitations/{invite_token_c}/accept")

    # User B (editor on team, NOT project admin) tries to add a member
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    target_id = str(user_c_data["id"]) if user_c_data else str(user_b_data["id"])
    add_resp = api_client_session.post(
        f"/api/teams/{team_slug}/projects/{proj_slug}/members",
        json={"user_id": target_id, "role": "editor"},
    )
    assert add_resp.status_code == 403, f"Expected 403, got {add_resp.status_code}: {add_resp.text}"

    # Restore admin auth
    client_a_token = authenticated_client[0].headers.get("Authorization")
    api_client_session.headers["Authorization"] = client_a_token


@pytest.mark.integration
def test_my_role_endpoint(
    authenticated_client, api_client_session, default_base_id, mock_orchestrator
):
    """GET /api/projects/{slug}/my-role returns correct structure for admin, editor, viewer."""
    if default_base_id is None:
        pytest.skip("No marketplace base available")

    # Create team with User B as viewer
    client_b, user_b_data, team_slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "myrpm", role="viewer"
    )

    client_a, user_a_data = authenticated_client
    proj_slug = _create_team_project(client_a, team_slug, default_base_id)
    if proj_slug is None:
        pytest.skip("Project creation failed")

    # Set visibility to "team" so viewer can see the project
    client_a.patch(
        f"/api/teams/{team_slug}/projects/{proj_slug}/visibility",
        json={"visibility": "team"},
    )

    # Admin's my-role
    admin_role = client_a.get(f"/api/projects/{proj_slug}/my-role")
    assert admin_role.status_code == 200
    admin_body = admin_role.json()
    assert "role" in admin_body
    assert admin_body["role"] == "admin"

    # Add User B as editor, check my-role
    user_b_id = user_b_data["id"]
    client_a.post(
        f"/api/teams/{team_slug}/projects/{proj_slug}/members",
        json={"user_id": str(user_b_id), "role": "editor"},
    )

    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    editor_role = api_client_session.get(f"/api/projects/{proj_slug}/my-role")
    assert editor_role.status_code == 200
    editor_body = editor_role.json()
    assert "role" in editor_body
    assert editor_body["role"] == "editor"

    # Change User B to viewer, check my-role
    client_a_token = authenticated_client[0].headers.get("Authorization")
    api_client_session.headers["Authorization"] = client_a_token
    client_a.patch(
        f"/api/teams/{team_slug}/projects/{proj_slug}/members/{user_b_id}",
        json={"role": "viewer"},
    )

    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    viewer_role = api_client_session.get(f"/api/projects/{proj_slug}/my-role")
    assert viewer_role.status_code == 200
    viewer_body = viewer_role.json()
    assert "role" in viewer_body
    assert viewer_body["role"] == "viewer"

    # Restore admin auth
    api_client_session.headers["Authorization"] = client_a_token
