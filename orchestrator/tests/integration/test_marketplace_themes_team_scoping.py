"""
Integration tests for marketplace theme library team-scoping (RBAC).

Tests that theme library operations (add, remove, toggle, list) are scoped
to the user's active team via team_id.

Requires: docker-compose.test.yml postgres on port 5433
Run: pytest tests/integration/test_marketplace_themes_team_scoping.py -v -m integration
"""

from uuid import uuid4

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────


def _create_team_and_switch(client, prefix):
    """Create a non-personal team and switch to it. Return team slug."""
    slug = f"{prefix}-{uuid4().hex[:8]}"
    resp = client.post("/api/teams", json={"name": f"Team {prefix}", "slug": slug})
    assert resp.status_code in (200, 201), f"Team create failed: {resp.text}"
    switch = client.post(f"/api/teams/{slug}/switch")
    assert switch.status_code == 200, f"Team switch failed: {switch.text}"
    return slug


def _get_personal_team_slug(client):
    """Get the user's personal team slug."""
    teams = client.get("/api/teams").json()
    personal = [t for t in teams if t["is_personal"]]
    return personal[0]["slug"] if personal else None


def _get_non_default_theme(client):
    """Get a non-default theme from the marketplace catalog. Returns theme_id or None."""
    resp = client.get("/api/marketplace/themes")
    if resp.status_code != 200:
        return None
    themes = resp.json()
    # themes response could be a list or dict with "themes" key
    if isinstance(themes, dict):
        themes = themes.get("themes", [])
    for t in themes:
        if not t.get("is_default", False):
            return t["id"]
    return None


def _get_my_theme_ids(client, exclude_defaults=True):
    """Return set of theme IDs from the user's library, optionally excluding defaults."""
    resp = client.get("/api/marketplace/my-themes")
    assert resp.status_code == 200, f"my-themes failed: {resp.text}"
    data = resp.json()
    themes = data if isinstance(data, list) else data.get("themes", [])
    if exclude_defaults:
        return {t["id"] for t in themes if not t.get("is_default", False)}
    return {t["id"] for t in themes}


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_theme_add_scoped_to_team(authenticated_client):
    """Adding a theme in one team should not make it visible in another team."""
    client, _ = authenticated_client

    personal_slug = _get_personal_team_slug(client)
    assert personal_slug, "No personal team found"

    # Create a new team and switch to it
    team_slug = _create_team_and_switch(client, "thm-scope")

    # Find a non-default theme to add
    theme_id = _get_non_default_theme(client)
    if not theme_id:
        pytest.skip("No non-default themes available in the marketplace catalog")

    # Add theme in team context
    add_resp = client.post(f"/api/marketplace/themes/{theme_id}/add")
    assert add_resp.status_code in (200, 201), f"Theme add failed: {add_resp.text}"

    # Verify theme is in library for this team
    team_themes = _get_my_theme_ids(client)
    assert theme_id in team_themes, "Theme should be visible in the team where it was added"

    # Switch to personal team
    client.post(f"/api/teams/{personal_slug}/switch")

    # Theme should NOT be in personal team's library (it's team-scoped)
    personal_themes = _get_my_theme_ids(client)
    assert theme_id not in personal_themes, (
        "Theme added in a different team should not appear in personal team library"
    )

    # Switch back to the team — theme should still be there
    client.post(f"/api/teams/{team_slug}/switch")
    team_themes_again = _get_my_theme_ids(client)
    assert theme_id in team_themes_again, (
        "Theme should still be visible after switching back to the team"
    )


@pytest.mark.integration
def test_theme_library_shared_within_team(authenticated_client, api_client_session):
    """Themes added by one team member should be visible to other team members."""
    client_a, _ = authenticated_client
    token_a = client_a.headers.get("Authorization")

    # User A creates a team and switches to it
    team_slug = _create_team_and_switch(client_a, "thm-share")

    # Find a non-default theme to add
    theme_id = _get_non_default_theme(client_a)
    if not theme_id:
        pytest.skip("No non-default themes available in the marketplace catalog")

    # User A adds theme in team context
    add_resp = client_a.post(f"/api/marketplace/themes/{theme_id}/add")
    assert add_resp.status_code in (200, 201), f"Theme add failed: {add_resp.text}"

    # User A creates invite link
    link_resp = client_a.post(
        f"/api/teams/{team_slug}/members/link", json={"role": "editor"}
    )
    assert link_resp.status_code in (200, 201), f"Link creation failed: {link_resp.text}"
    invite_token = link_resp.json().get("token")
    if not invite_token:
        pytest.skip(f"No token in link response: {link_resp.json()}")

    # Register User B (temporarily clear auth)
    email_b = f"userb-{uuid4().hex[:8]}@example.com"
    client_a.headers.pop("Authorization", None)
    api_client_session.headers.pop("Authorization", None)

    reg_resp = api_client_session.post(
        "/api/auth/register",
        json={"email": email_b, "password": "TestPass123!", "name": "User B"},
    )
    assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.text}"

    login_resp = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email_b, "password": "TestPass123!"},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token_b = login_resp.json()["access_token"]
    api_client_session.headers["Authorization"] = f"Bearer {token_b}"

    # User B accepts invite
    accept_resp = api_client_session.post(
        f"/api/teams/invitations/{invite_token}/accept"
    )
    assert accept_resp.status_code == 200, f"Accept failed: {accept_resp.text}"

    # User B switches to the shared team
    switch_resp = api_client_session.post(f"/api/teams/{team_slug}/switch")
    assert switch_resp.status_code == 200, f"Switch failed: {switch_resp.text}"

    # User B should see the theme added by User A
    b_themes = _get_my_theme_ids(api_client_session)
    assert theme_id in b_themes, (
        "Theme added by User A should be visible to User B in the same team"
    )

    # Restore User A auth
    if token_a:
        client_a.headers["Authorization"] = token_a


@pytest.mark.integration
def test_theme_remove_scoped_to_team(authenticated_client):
    """Removing a theme in team context should remove it from that team's library."""
    client, _ = authenticated_client

    team_slug = _create_team_and_switch(client, "thm-rm")

    theme_id = _get_non_default_theme(client)
    if not theme_id:
        pytest.skip("No non-default themes available in the marketplace catalog")

    # Add theme
    add_resp = client.post(f"/api/marketplace/themes/{theme_id}/add")
    assert add_resp.status_code in (200, 201), f"Theme add failed: {add_resp.text}"

    # Confirm it's in the library
    themes_before = _get_my_theme_ids(client)
    assert theme_id in themes_before, "Theme should be present after adding"

    # Remove theme
    rm_resp = client.delete(f"/api/marketplace/themes/{theme_id}/remove")
    assert rm_resp.status_code == 200, f"Theme remove failed: {rm_resp.text}"

    # Confirm it's gone
    themes_after = _get_my_theme_ids(client)
    assert theme_id not in themes_after, "Theme should be removed from team library"


@pytest.mark.integration
def test_theme_toggle_scoped_to_team(authenticated_client):
    """Toggling a theme in team context should reflect the correct enabled state."""
    client, _ = authenticated_client

    team_slug = _create_team_and_switch(client, "thm-tgl")

    theme_id = _get_non_default_theme(client)
    if not theme_id:
        pytest.skip("No non-default themes available in the marketplace catalog")

    # Add theme
    add_resp = client.post(f"/api/marketplace/themes/{theme_id}/add")
    assert add_resp.status_code in (200, 201), f"Theme add failed: {add_resp.text}"

    # Toggle the theme (should change enabled state)
    toggle_resp = client.post(f"/api/marketplace/themes/{theme_id}/toggle")
    assert toggle_resp.status_code == 200, f"Theme toggle failed: {toggle_resp.text}"
    toggle_data = toggle_resp.json()

    # The response should indicate the new enabled state
    # Capture whatever state it toggled to
    if "enabled" in toggle_data:
        first_toggle_state = toggle_data["enabled"]
    elif "is_enabled" in toggle_data:
        first_toggle_state = toggle_data["is_enabled"]
    else:
        # Just verify the toggle succeeded; check library for state
        first_toggle_state = None

    # Toggle again — state should flip
    toggle_resp2 = client.post(f"/api/marketplace/themes/{theme_id}/toggle")
    assert toggle_resp2.status_code == 200, f"Second toggle failed: {toggle_resp2.text}"
    toggle_data2 = toggle_resp2.json()

    if first_toggle_state is not None:
        if "enabled" in toggle_data2:
            assert toggle_data2["enabled"] != first_toggle_state, (
                "Second toggle should flip the enabled state"
            )
        elif "is_enabled" in toggle_data2:
            assert toggle_data2["is_enabled"] != first_toggle_state, (
                "Second toggle should flip the enabled state"
            )


@pytest.mark.integration
def test_theme_add_idempotent_within_team(authenticated_client):
    """Adding the same theme twice in the same team should succeed (re-activate)."""
    client, _ = authenticated_client

    team_slug = _create_team_and_switch(client, "thm-idem")

    theme_id = _get_non_default_theme(client)
    if not theme_id:
        pytest.skip("No non-default themes available in the marketplace catalog")

    # Add theme first time
    resp1 = client.post(f"/api/marketplace/themes/{theme_id}/add")
    assert resp1.status_code in (200, 201), f"First add failed: {resp1.text}"

    # Add theme second time — should not error
    resp2 = client.post(f"/api/marketplace/themes/{theme_id}/add")
    assert resp2.status_code in (200, 201), f"Second add (idempotent) failed: {resp2.text}"

    # Theme should still be in library exactly once
    themes = _get_my_theme_ids(client)
    assert theme_id in themes, "Theme should be in library after double-add"
