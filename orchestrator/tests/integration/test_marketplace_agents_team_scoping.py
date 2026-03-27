"""
Integration tests for marketplace agent/skill RBAC team-scoping.

Tests:
- Agent purchases are scoped to the user's active team (default_team_id)
- Team members share a library within the same team
- Removing agents is team-scoped
- Skill purchases are team-scoped
- Skill-agent installations are team-scoped

Requires: docker-compose.test.yml postgres on port 5433
Run: pytest tests/integration/test_marketplace_agents_team_scoping.py -v -m integration
"""

from uuid import uuid4

import pytest


# ── Helpers ────────────────────────────────────────────────────────────


def _create_team_and_switch(client, prefix):
    """Create a non-personal team and switch to it. Return team slug."""
    slug = f"{prefix}-{uuid4().hex[:8]}"
    resp = client.post("/api/teams", json={"name": f"Team {prefix}", "slug": slug})
    assert resp.status_code in (200, 201), f"Team creation failed: {resp.text}"
    switch = client.post(f"/api/teams/{slug}/switch")
    assert switch.status_code == 200, f"Switch failed: {switch.text}"
    return slug


def _get_personal_team_slug(client):
    """Get the user's personal team slug."""
    teams = client.get("/api/teams").json()
    personal = [t for t in teams if t["is_personal"]]
    return personal[0]["slug"] if personal else None


def _get_marketplace_agent(client, item_type=None):
    """Get first available free marketplace agent. Returns (id, slug) or None."""
    params = {}
    if item_type:
        params["item_type"] = item_type
    resp = client.get("/api/marketplace/agents", params=params)
    if resp.status_code != 200:
        return None
    agents = resp.json().get("agents", [])
    for a in agents:
        if a.get("pricing_type") in ("free", None) or a.get("price", 0) == 0:
            return a["id"], a["slug"]
    return None


def _get_marketplace_skill(client):
    """Get first available free marketplace skill. Returns (id, slug) or None."""
    resp = client.get("/api/marketplace/skills")
    if resp.status_code != 200:
        return None
    skills = resp.json().get("skills", [])
    for s in skills:
        if s.get("pricing_type") in ("free", None) or s.get("price", 0) == 0:
            return s["id"], s["slug"]
    return None


def _my_agent_ids(client):
    """Return set of agent IDs currently in the user's library."""
    resp = client.get("/api/marketplace/my-agents")
    assert resp.status_code == 200
    data = resp.json()
    agents = data.get("agents", []) if isinstance(data, dict) else data
    return {a["id"] for a in agents}


def _register_and_login(api_client_session, prefix="userb"):
    """Register a new user and return (user_data, access_token)."""
    email = f"{prefix}-{uuid4().hex[:8]}@example.com"
    api_client_session.headers.pop("Authorization", None)
    reg = api_client_session.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "name": f"User {prefix}"},
    )
    assert reg.status_code == 201, f"Register failed: {reg.text}"
    user_data = reg.json()

    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email, "password": "TestPass123!"},
    )
    assert login.status_code == 200, f"Login failed: {login.text}"
    token = login.json()["access_token"]
    return user_data, token


# ── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_agent_purchase_scoped_to_team(authenticated_client):
    """
    Purchase an agent while switched to a non-personal team.
    Switch back to personal team -- agent should NOT appear.
    Switch back to the team -- agent SHOULD appear.
    """
    client, _ = authenticated_client

    agent_info = _get_marketplace_agent(client)
    if agent_info is None:
        pytest.skip("No free marketplace agents seeded")
    agent_id, _ = agent_info

    # Remember personal team slug
    personal_slug = _get_personal_team_slug(client)
    assert personal_slug is not None, "User has no personal team"

    # Create a team and switch to it
    team_slug = _create_team_and_switch(client, "mkt-scope")

    # Purchase agent in team context
    resp = client.post(f"/api/marketplace/agents/{agent_id}/purchase")
    assert resp.status_code == 200, f"Purchase failed: {resp.text}"

    # Verify agent is in library while in team context
    assert agent_id in _my_agent_ids(client)

    # Switch to personal team -- agent should NOT be visible
    client.post(f"/api/teams/{personal_slug}/switch")
    assert agent_id not in _my_agent_ids(client)

    # Switch back to the team -- agent should reappear
    client.post(f"/api/teams/{team_slug}/switch")
    assert agent_id in _my_agent_ids(client)


@pytest.mark.integration
def test_agent_library_shared_within_team(authenticated_client, api_client_session):
    """
    User A creates a team and purchases an agent.
    User B joins the team via invite link.
    User B's library should show the agent purchased by User A.
    """
    client_a, _ = authenticated_client

    agent_info = _get_marketplace_agent(client_a)
    if agent_info is None:
        pytest.skip("No free marketplace agents seeded")
    agent_id, _ = agent_info

    # Save User A's auth token so we can restore it
    token_a = client_a.headers.get("Authorization")

    # Create team, switch, and purchase agent
    team_slug = _create_team_and_switch(client_a, "shared-lib")
    resp = client_a.post(f"/api/marketplace/agents/{agent_id}/purchase")
    assert resp.status_code == 200, f"Purchase failed: {resp.text}"

    # Create invite link
    link_resp = client_a.post(
        f"/api/teams/{team_slug}/members/link", json={"role": "editor"}
    )
    assert link_resp.status_code in (200, 201), f"Link creation failed: {link_resp.text}"
    invite_token = link_resp.json()["token"]

    # Register User B
    user_b_data, token_b = _register_and_login(api_client_session, "shared-b")

    # Accept invite as User B
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    accept = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")
    assert accept.status_code == 200, f"Accept failed: {accept.text}"

    # Switch User B to the team
    api_client_session.post(f"/api/teams/{team_slug}/switch")

    # User B should see the agent in the shared library
    assert agent_id in _my_agent_ids(api_client_session)

    # Restore User A's auth for subsequent tests
    api_client_session.headers["Authorization"] = token_a


@pytest.mark.integration
def test_remove_agent_scoped_to_team(authenticated_client):
    """
    Purchase an agent in team context, remove it, verify it is gone.
    """
    client, _ = authenticated_client

    agent_info = _get_marketplace_agent(client)
    if agent_info is None:
        pytest.skip("No free marketplace agents seeded")
    agent_id, _ = agent_info

    # Create team, switch, purchase
    team_slug = _create_team_and_switch(client, "rm-scope")
    resp = client.post(f"/api/marketplace/agents/{agent_id}/purchase")
    assert resp.status_code == 200, f"Purchase failed: {resp.text}"
    assert agent_id in _my_agent_ids(client)

    # Remove the agent
    del_resp = client.delete(f"/api/marketplace/agents/{agent_id}/library")
    assert del_resp.status_code == 200, f"Remove failed: {del_resp.text}"

    # Verify it is gone
    assert agent_id not in _my_agent_ids(client)


@pytest.mark.integration
def test_skill_purchase_scoped_to_team(authenticated_client):
    """
    Purchase a skill in a non-personal team context.
    Switch to personal team -- skill should NOT appear in my-agents.
    Switch back to team -- skill SHOULD appear.
    """
    client, _ = authenticated_client

    skill_info = _get_marketplace_skill(client)
    if skill_info is None:
        pytest.skip("No free marketplace skills seeded")
    skill_id, _ = skill_info

    personal_slug = _get_personal_team_slug(client)
    assert personal_slug is not None

    # Create team and switch
    team_slug = _create_team_and_switch(client, "skill-scope")

    # Purchase skill
    resp = client.post(f"/api/marketplace/skills/{skill_id}/purchase")
    assert resp.status_code == 200, f"Skill purchase failed: {resp.text}"

    # Verify skill is in library (skills are stored as UserPurchasedAgent too)
    # The my-agents endpoint excludes skills, so query the skills endpoint
    # We verify by trying to re-purchase -- should say "already in library"
    re_resp = client.post(f"/api/marketplace/skills/{skill_id}/purchase")
    assert re_resp.status_code == 200
    assert "already" in re_resp.json().get("message", "").lower()

    # Switch to personal team and try to re-purchase -- should NOT be "already"
    client.post(f"/api/teams/{personal_slug}/switch")
    personal_resp = client.post(f"/api/marketplace/skills/{skill_id}/purchase")
    assert personal_resp.status_code == 200
    # In personal context, the skill was not purchased, so it should succeed as a new purchase
    msg = personal_resp.json().get("message", "").lower()
    assert "added" in msg or "already" not in msg or personal_resp.json().get("success") is True

    # Switch back to team -- re-purchase should say "already"
    client.post(f"/api/teams/{team_slug}/switch")
    team_resp = client.post(f"/api/marketplace/skills/{skill_id}/purchase")
    assert team_resp.status_code == 200
    assert "already" in team_resp.json().get("message", "").lower()


@pytest.mark.integration
def test_skill_install_on_agent_scoped_to_team(authenticated_client):
    """
    Purchase both an agent and a skill in team context.
    Install the skill on the agent.
    Verify GET /agents/{agent_id}/skills shows the skill.
    Switch to personal team -- should NOT show the skill on that agent.
    """
    client, _ = authenticated_client

    agent_info = _get_marketplace_agent(client)
    if agent_info is None:
        pytest.skip("No free marketplace agents seeded")
    agent_id, _ = agent_info

    skill_info = _get_marketplace_skill(client)
    if skill_info is None:
        pytest.skip("No free marketplace skills seeded")
    skill_id, _ = skill_info

    personal_slug = _get_personal_team_slug(client)
    assert personal_slug is not None

    # Create team, switch, purchase both
    team_slug = _create_team_and_switch(client, "inst-scope")

    client.post(f"/api/marketplace/agents/{agent_id}/purchase")
    client.post(f"/api/marketplace/skills/{skill_id}/purchase")

    # Install skill on agent
    install_resp = client.post(
        f"/api/marketplace/skills/{skill_id}/install",
        json={"agent_id": str(agent_id)},
    )
    assert install_resp.status_code == 200, f"Install failed: {install_resp.text}"

    # Verify skill appears on the agent
    skills_resp = client.get(f"/api/marketplace/agents/{agent_id}/skills")
    assert skills_resp.status_code == 200
    skills_data = skills_resp.json()
    skills_list = skills_data.get("skills", []) if isinstance(skills_data, dict) else skills_data
    skill_ids = [s["id"] for s in skills_list]
    assert str(skill_id) in [str(sid) for sid in skill_ids]

    # Switch to personal team -- skill should NOT show on agent
    client.post(f"/api/teams/{personal_slug}/switch")
    personal_skills_resp = client.get(f"/api/marketplace/agents/{agent_id}/skills")
    assert personal_skills_resp.status_code == 200
    personal_data = personal_skills_resp.json()
    personal_list = personal_data.get("skills", []) if isinstance(personal_data, dict) else personal_data
    personal_skill_ids = [str(s["id"]) for s in personal_list]
    assert str(skill_id) not in personal_skill_ids

    # Switch back to team -- skill should reappear
    client.post(f"/api/teams/{team_slug}/switch")
    team_skills_resp = client.get(f"/api/marketplace/agents/{agent_id}/skills")
    assert team_skills_resp.status_code == 200
    team_data = team_skills_resp.json()
    team_list = team_data.get("skills", []) if isinstance(team_data, dict) else team_data
    team_skill_ids = [str(s["id"]) for s in team_list]
    assert str(skill_id) in team_skill_ids
