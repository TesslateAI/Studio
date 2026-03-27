"""
Integration tests for MCP team-scoping under RBAC.

Tests:
- MCP installs are scoped to the user's active team (team_id)
- Installs made in Team A are not visible when switched to Team B
- Installs are shared among team members
- Uninstall, single-get, assign, and unassign all respect team scope

Requires: docker-compose.test.yml postgres on port 5433
Run: pytest tests/integration/test_mcp_team_scoping.py -v -m integration
"""

from uuid import uuid4

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────


def _create_team_and_switch(client, prefix):
    """Create a non-personal team and switch to it. Return team slug."""
    slug = f"{prefix}-{uuid4().hex[:8]}"
    resp = client.post("/api/teams", json={"name": f"Team {prefix}", "slug": slug})
    assert resp.status_code in (200, 201), f"Team creation failed: {resp.text}"
    client.post(f"/api/teams/{slug}/switch")
    return slug


def _get_personal_team_slug(client):
    """Get the user's personal team slug."""
    teams = client.get("/api/teams").json()
    personal = [t for t in teams if t["is_personal"]]
    return personal[0]["slug"] if personal else None


def _get_mcp_server_id(client):
    """Get first available MCP server from marketplace. Returns marketplace_agent_id or None."""
    resp = client.get("/api/marketplace/mcp-servers")
    if resp.status_code != 200:
        return None
    data = resp.json()
    servers = data if isinstance(data, list) else data.get("servers", data.get("agents", []))
    if servers:
        return servers[0]["id"]
    return None


def _get_marketplace_agent_id(client):
    """Get first available agent from marketplace for assignment tests. Returns agent_id or None."""
    resp = client.get("/api/marketplace/agents")
    if resp.status_code != 200:
        return None
    agents = resp.json().get("agents", [])
    for a in agents:
        if a.get("item_type") not in ("skill", "subagent", "mcp_server"):
            return a["id"]
    return None


def _install_mcp(client, mcp_server_id):
    """Install an MCP server and return the config id."""
    resp = client.post(
        "/api/mcp/install",
        json={"marketplace_agent_id": mcp_server_id, "credentials": {}},
    )
    assert resp.status_code == 201, f"MCP install failed: {resp.text}"
    return resp.json()["id"]


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_mcp_install_scoped_to_team(authenticated_client):
    """MCP installs in Team A are not visible when switched to personal team."""
    client, _ = authenticated_client

    mcp_server_id = _get_mcp_server_id(client)
    if not mcp_server_id:
        pytest.skip("No MCP servers available in marketplace")

    personal_slug = _get_personal_team_slug(client)
    assert personal_slug, "User has no personal team"

    # Create a team and switch to it
    team_slug = _create_team_and_switch(client, "mcpscope")

    # Install MCP server in team context
    config_id = _install_mcp(client, mcp_server_id)

    # Verify it shows up in team context
    installed = client.get("/api/mcp/installed").json()
    config_ids = [c["id"] for c in installed]
    assert config_id in config_ids, "Install should be visible in team context"

    # Switch back to personal team
    client.post(f"/api/teams/{personal_slug}/switch")

    # Should NOT be visible in personal team
    installed_personal = client.get("/api/mcp/installed").json()
    config_ids_personal = [c["id"] for c in installed_personal]
    assert config_id not in config_ids_personal, "Install should NOT be visible in personal team"

    # Switch back to the team — should be visible again
    client.post(f"/api/teams/{team_slug}/switch")

    installed_team = client.get("/api/mcp/installed").json()
    config_ids_team = [c["id"] for c in installed_team]
    assert config_id in config_ids_team, "Install should be visible again after switching back"


@pytest.mark.integration
def test_mcp_install_shared_within_team(authenticated_client, api_client_session):
    """MCP installs made by User A are visible to User B in the same team."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    mcp_server_id = _get_mcp_server_id(client_a)
    if not mcp_server_id:
        pytest.skip("No MCP servers available in marketplace")

    # User A creates a team
    team_slug = _create_team_and_switch(client_a, "mcpshare")

    # User A installs MCP server in team context
    config_id = _install_mcp(client_a, mcp_server_id)

    # User A creates invite link
    link_resp = client_a.post(
        f"/api/teams/{team_slug}/members/link", json={"role": "editor"}
    )
    assert link_resp.status_code in (200, 201), f"Link creation failed: {link_resp.text}"
    invite_token = link_resp.json().get("token")
    if not invite_token:
        pytest.skip(f"No token in link response: {link_resp.json()}")

    # Register User B
    email_b = f"userb-{uuid4().hex[:8]}@example.com"
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
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"

    # User B accepts invite
    accept = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")
    assert accept.status_code == 200, f"Accept failed: {accept.text}"

    # User B switches to the shared team
    api_client_session.post(f"/api/teams/{team_slug}/switch")

    # User B should see User A's MCP install
    installed = api_client_session.get("/api/mcp/installed").json()
    config_ids = [c["id"] for c in installed]
    assert config_id in config_ids, "User B should see User A's MCP install in same team"

    # Restore User A's auth for fixture cleanup
    if token_a:
        api_client_session.headers["Authorization"] = token_a


@pytest.mark.integration
def test_mcp_uninstall_scoped_to_team(authenticated_client):
    """Uninstalled MCP server no longer appears in installed list."""
    client, _ = authenticated_client

    mcp_server_id = _get_mcp_server_id(client)
    if not mcp_server_id:
        pytest.skip("No MCP servers available in marketplace")

    team_slug = _create_team_and_switch(client, "mcpuninst")

    config_id = _install_mcp(client, mcp_server_id)

    # Uninstall
    resp = client.delete(f"/api/mcp/installed/{config_id}")
    assert resp.status_code == 204

    # Should no longer appear
    installed = client.get("/api/mcp/installed").json()
    config_ids = [c["id"] for c in installed]
    assert config_id not in config_ids, "Uninstalled MCP should not appear in list"


@pytest.mark.integration
def test_mcp_get_single_install_scoped_to_team(authenticated_client):
    """Single-get of an MCP install returns 404 when queried from wrong team."""
    client, _ = authenticated_client

    mcp_server_id = _get_mcp_server_id(client)
    if not mcp_server_id:
        pytest.skip("No MCP servers available in marketplace")

    personal_slug = _get_personal_team_slug(client)
    assert personal_slug, "User has no personal team"

    # Install in Team A
    team_slug = _create_team_and_switch(client, "mcpget")
    config_id = _install_mcp(client, mcp_server_id)

    # Accessible from Team A
    resp_a = client.get(f"/api/mcp/installed/{config_id}")
    assert resp_a.status_code == 200, "Should be accessible from Team A"

    # Switch to personal team (Team B)
    client.post(f"/api/teams/{personal_slug}/switch")

    # NOT accessible from personal team
    resp_b = client.get(f"/api/mcp/installed/{config_id}")
    assert resp_b.status_code == 404, "Should NOT be accessible from personal team"


@pytest.mark.integration
def test_mcp_assign_to_agent_scoped_to_team(authenticated_client):
    """MCP-to-agent assignment is scoped to team; invisible from other teams."""
    client, _ = authenticated_client

    mcp_server_id = _get_mcp_server_id(client)
    if not mcp_server_id:
        pytest.skip("No MCP servers available in marketplace")

    agent_id = _get_marketplace_agent_id(client)
    if not agent_id:
        pytest.skip("No marketplace agents available for assignment test")

    personal_slug = _get_personal_team_slug(client)
    assert personal_slug, "User has no personal team"

    # Create team and install MCP
    team_slug = _create_team_and_switch(client, "mcpassign")
    config_id = _install_mcp(client, mcp_server_id)

    # Purchase agent in team context (non-fatal if already purchased or free)
    client.post(f"/api/marketplace/agents/{agent_id}/purchase")

    # Assign MCP to agent
    assign_resp = client.post(f"/api/mcp/installed/{config_id}/assign/{agent_id}")
    assert assign_resp.status_code == 200, f"Assign failed: {assign_resp.text}"

    # Verify assignment visible in team context
    servers_resp = client.get(f"/api/mcp/agent/{agent_id}/servers")
    assert servers_resp.status_code == 200
    server_ids = [s["mcp_config_id"] for s in servers_resp.json()]
    assert config_id in server_ids, "Assignment should be visible in team context"

    # Switch to personal team
    client.post(f"/api/teams/{personal_slug}/switch")

    # Assignment should NOT be visible from personal team
    servers_personal = client.get(f"/api/mcp/agent/{agent_id}/servers")
    assert servers_personal.status_code == 200
    server_ids_personal = [s["mcp_config_id"] for s in servers_personal.json()]
    assert config_id not in server_ids_personal, (
        "Assignment should NOT be visible from personal team"
    )


@pytest.mark.integration
def test_mcp_unassign_from_agent_scoped_to_team(authenticated_client):
    """Unassigning MCP from agent removes it from the agent's server list."""
    client, _ = authenticated_client

    mcp_server_id = _get_mcp_server_id(client)
    if not mcp_server_id:
        pytest.skip("No MCP servers available in marketplace")

    agent_id = _get_marketplace_agent_id(client)
    if not agent_id:
        pytest.skip("No marketplace agents available for assignment test")

    # Create team, install, assign
    team_slug = _create_team_and_switch(client, "mcpunassign")
    config_id = _install_mcp(client, mcp_server_id)

    client.post(f"/api/marketplace/agents/{agent_id}/purchase")

    assign_resp = client.post(f"/api/mcp/installed/{config_id}/assign/{agent_id}")
    assert assign_resp.status_code == 200, f"Assign failed: {assign_resp.text}"

    # Unassign
    unassign_resp = client.delete(f"/api/mcp/installed/{config_id}/assign/{agent_id}")
    assert unassign_resp.status_code == 204

    # Should no longer appear in agent's servers
    servers_resp = client.get(f"/api/mcp/agent/{agent_id}/servers")
    assert servers_resp.status_code == 200
    server_ids = [s["mcp_config_id"] for s in servers_resp.json()]
    assert config_id not in server_ids, "Unassigned MCP should not appear in agent's servers"
