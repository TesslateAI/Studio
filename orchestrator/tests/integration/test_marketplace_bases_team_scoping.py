"""
Integration tests for marketplace base purchases with RBAC team-scoping.

Tests:
- Base purchases are scoped to the active team via team_id
- Bases purchased in one team are NOT visible in another team's library
- Bases purchased by any team member are visible to all team members
- Combined my-items endpoint respects team scoping
- Idempotent purchase within the same team context

Requires: docker-compose.test.yml postgres on port 5433
Run: pytest tests/integration/test_marketplace_bases_team_scoping.py -v -m integration
"""

from uuid import uuid4

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────


def _create_team_and_switch(client, prefix):
    """Create a non-personal team and switch to it. Return team slug."""
    slug = f"{prefix}-{uuid4().hex[:8]}"
    resp = client.post("/api/teams", json={"name": f"Team {prefix}", "slug": slug})
    assert resp.status_code in (200, 201), f"Team creation failed: {resp.text}"
    switch = client.post(f"/api/teams/{slug}/switch")
    assert switch.status_code == 200, f"Team switch failed: {switch.text}"
    return slug


def _get_personal_team_slug(client):
    """Get the user's personal team slug."""
    teams = client.get("/api/teams").json()
    personal = [t for t in teams if t["is_personal"]]
    return personal[0]["slug"] if personal else None


def _get_free_base(client):
    """Get first available free marketplace base. Returns base_id or None."""
    resp = client.get("/api/marketplace/bases")
    if resp.status_code != 200:
        return None
    bases = resp.json().get("bases", [])
    for b in bases:
        if b.get("price_type") in ("free", None) or b.get("price", 0) == 0:
            return b["id"]
    return None


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_base_purchase_scoped_to_team(authenticated_client):
    """Bases purchased in Team A should NOT appear in personal team library."""
    client, _ = authenticated_client

    personal_slug = _get_personal_team_slug(client)
    assert personal_slug, "User should have a personal team"

    # Get a free base to purchase
    base_id = _get_free_base(client)
    if not base_id:
        pytest.skip("No marketplace bases seeded — cannot test purchase scoping")

    # Create a team and switch to it
    team_slug = _create_team_and_switch(client, "scope")

    # Purchase the base in team context
    purchase_resp = client.post(f"/api/marketplace/bases/{base_id}/purchase")
    assert purchase_resp.status_code == 200, f"Purchase failed: {purchase_resp.text}"

    # Verify the base appears in team library
    my_bases = client.get("/api/marketplace/my-bases")
    assert my_bases.status_code == 200
    team_base_ids = [b["id"] for b in my_bases.json().get("bases", [])]
    assert base_id in team_base_ids, "Purchased base should appear in team library"

    # Switch back to personal team
    client.post(f"/api/teams/{personal_slug}/switch")

    # Verify the base does NOT appear in personal library
    my_bases_personal = client.get("/api/marketplace/my-bases")
    assert my_bases_personal.status_code == 200
    personal_base_ids = [b["id"] for b in my_bases_personal.json().get("bases", [])]
    assert base_id not in personal_base_ids, (
        "Base purchased in team context should NOT appear in personal library"
    )

    # Switch back to team — should still be there
    client.post(f"/api/teams/{team_slug}/switch")
    my_bases_team = client.get("/api/marketplace/my-bases")
    assert my_bases_team.status_code == 200
    team_base_ids_again = [b["id"] for b in my_bases_team.json().get("bases", [])]
    assert base_id in team_base_ids_again, (
        "Base should still appear after switching back to team"
    )


@pytest.mark.integration
def test_base_library_shared_within_team(authenticated_client, api_client_session):
    """Bases purchased by User A in a team should be visible to User B in the same team."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    # Get a free base
    base_id = _get_free_base(client_a)
    if not base_id:
        pytest.skip("No marketplace bases seeded — cannot test team sharing")

    # User A creates a team and switches to it
    team_slug = _create_team_and_switch(client_a, "shared")

    # User A purchases the base in team context
    purchase_resp = client_a.post(f"/api/marketplace/bases/{base_id}/purchase")
    assert purchase_resp.status_code == 200, f"Purchase failed: {purchase_resp.text}"

    # User A creates an invite link
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
    assert reg.status_code == 201, f"User B registration failed: {reg.text}"

    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email_b, "password": "TestPass123!"},
    )
    assert login.status_code == 200, f"User B login failed: {login.text}"
    token_b = login.json()["access_token"]
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"

    # User B accepts the invite
    accept_resp = api_client_session.post(
        f"/api/teams/invitations/{invite_token}/accept"
    )
    assert accept_resp.status_code == 200, f"Invite accept failed: {accept_resp.text}"

    # User B switches to the team
    switch_resp = api_client_session.post(f"/api/teams/{team_slug}/switch")
    assert switch_resp.status_code == 200, f"Team switch failed: {switch_resp.text}"

    # User B should see the base in the team library
    my_bases_b = api_client_session.get("/api/marketplace/my-bases")
    assert my_bases_b.status_code == 200
    b_base_ids = [b["id"] for b in my_bases_b.json().get("bases", [])]
    assert base_id in b_base_ids, (
        "User B should see base purchased by User A in the shared team"
    )

    # Restore User A's auth for fixture cleanup
    api_client_session.headers["Authorization"] = token_a


@pytest.mark.integration
def test_my_items_scoped_to_team(authenticated_client):
    """The combined my-items endpoint should respect team scoping for bases."""
    client, _ = authenticated_client

    personal_slug = _get_personal_team_slug(client)
    assert personal_slug, "User should have a personal team"

    base_id = _get_free_base(client)
    if not base_id:
        pytest.skip("No marketplace bases seeded — cannot test my-items scoping")

    # Create team and purchase base
    team_slug = _create_team_and_switch(client, "items")
    purchase_resp = client.post(f"/api/marketplace/bases/{base_id}/purchase")
    assert purchase_resp.status_code == 200, f"Purchase failed: {purchase_resp.text}"

    # Verify my-items includes the base in team context
    my_items = client.get("/api/marketplace/my-items")
    assert my_items.status_code == 200
    items_data = my_items.json()
    # my-items may return bases under various keys; check for the base_id
    team_item_ids = set()
    for key in ("bases", "items", "agents"):
        for item in items_data.get(key, []):
            team_item_ids.add(item.get("id") or item.get("base_id"))
    assert base_id in team_item_ids, (
        "Purchased base should appear in my-items for team context"
    )

    # Switch to personal team
    client.post(f"/api/teams/{personal_slug}/switch")

    my_items_personal = client.get("/api/marketplace/my-items")
    assert my_items_personal.status_code == 200
    personal_data = my_items_personal.json()
    personal_item_ids = set()
    for key in ("bases", "items", "agents"):
        for item in personal_data.get(key, []):
            personal_item_ids.add(item.get("id") or item.get("base_id"))
    assert base_id not in personal_item_ids, (
        "Base purchased in team context should NOT appear in personal my-items"
    )


@pytest.mark.integration
def test_base_purchase_idempotent_within_team(authenticated_client):
    """Purchasing the same base twice in the same team should not create duplicates."""
    client, _ = authenticated_client

    base_id = _get_free_base(client)
    if not base_id:
        pytest.skip("No marketplace bases seeded — cannot test idempotent purchase")

    team_slug = _create_team_and_switch(client, "idem")

    # First purchase
    resp1 = client.post(f"/api/marketplace/bases/{base_id}/purchase")
    assert resp1.status_code == 200, f"First purchase failed: {resp1.text}"

    # Second purchase — should succeed without error
    resp2 = client.post(f"/api/marketplace/bases/{base_id}/purchase")
    assert resp2.status_code == 200, f"Second purchase failed: {resp2.text}"

    # Verify only one entry in library (no duplicates)
    my_bases = client.get("/api/marketplace/my-bases")
    assert my_bases.status_code == 200
    bases = my_bases.json().get("bases", [])
    matching = [b for b in bases if b["id"] == base_id]
    assert len(matching) == 1, (
        f"Expected exactly 1 entry for base {base_id}, got {len(matching)}"
    )
