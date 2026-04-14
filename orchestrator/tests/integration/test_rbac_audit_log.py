"""
Integration tests for the RBAC Audit Log system (PRD Sections 8 & 9.3).

Tests:
- Audit log entries for team updates, member joins, removals, invitation revocations
- Filtering by action, resource_type
- Pagination
- CSV export (admin only)
- Viewer access to audit log
- Required fields validation
- Member leave audit entry

Requires: docker-compose.test.yml postgres on port 5433
Run: pytest tests/integration/test_rbac_audit_log.py -v -m integration
"""

from uuid import uuid4

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────


def _create_team_and_user_b(api_client_session, admin_client, team_prefix, role="editor"):
    """Create a team with admin_client, invite and join User B via link.

    Returns (client_b, user_b_data, slug, token_b).
    """
    client_a, _ = admin_client
    slug = f"{team_prefix}-{uuid4().hex[:8]}"
    resp = client_a.post("/api/teams", json={"name": f"Team {team_prefix}", "slug": slug})
    assert resp.status_code in (200, 201), f"Team create failed: {resp.text}"

    link_resp = client_a.post(f"/api/teams/{slug}/members/link", json={"role": role})
    assert link_resp.status_code in (200, 201), f"Link create failed: {link_resp.text}"
    invite_token = link_resp.json()["token"]

    email_b = f"userb-{uuid4().hex[:8]}@example.com"
    api_client_session.headers.pop("Authorization", None)
    reg = api_client_session.post(
        "/api/auth/register",
        json={"email": email_b, "password": "TestPass123!", "name": "User B"},
    )
    assert reg.status_code == 201, f"Register failed: {reg.text}"
    user_b_data = reg.json()

    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email_b, "password": "TestPass123!"},
    )
    assert login.status_code == 200, f"Login failed: {login.text}"
    token_b = login.json()["access_token"]

    api_client_session.headers["Authorization"] = f"Bearer {token_b}"
    accept = api_client_session.post(f"/api/teams/invitations/{invite_token}/accept")
    assert accept.status_code == 200, f"Accept failed: {accept.text}"

    return api_client_session, user_b_data, slug, token_b


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_audit_log_records_team_update(authenticated_client):
    """Updating a team name should generate a team.updated audit entry."""
    client, _ = authenticated_client
    slug = f"al-upd-{uuid4().hex[:8]}"

    resp = client.post("/api/teams", json={"name": "Before Update", "slug": slug})
    assert resp.status_code in (200, 201), f"Team create failed: {resp.text}"

    patch_resp = client.patch(f"/api/teams/{slug}", json={"name": "After Update"})
    assert patch_resp.status_code == 200, f"Team update failed: {patch_resp.text}"

    log_resp = client.get(f"/api/teams/{slug}/audit-log")
    assert log_resp.status_code == 200, f"Audit log fetch failed: {log_resp.text}"

    logs = log_resp.json()
    actions = [entry["action"] for entry in logs]
    assert "team.updated" in actions, f"Expected team.updated in {actions}"


@pytest.mark.integration
def test_audit_log_records_member_joined(authenticated_client, api_client_session):
    """Accepting an invite should generate a member.joined audit entry."""
    # Capture admin auth BEFORE helper overwrites the shared session headers
    client_a, _ = authenticated_client
    admin_token = api_client_session.headers.get("Authorization")

    _, _, slug, _ = _create_team_and_user_b(api_client_session, authenticated_client, "al-joined")

    # Restore admin auth to read audit log (helper left User B's token on the shared session)
    api_client_session.headers["Authorization"] = admin_token
    log_resp = client_a.get(f"/api/teams/{slug}/audit-log")
    assert log_resp.status_code == 200, f"Audit log fetch failed: {log_resp.text}"

    logs = log_resp.json()
    actions = [entry["action"] for entry in logs]
    assert "member.joined" in actions, f"Expected member.joined in {actions}"


@pytest.mark.integration
def test_audit_log_records_member_removed(authenticated_client, api_client_session):
    """Admin removing a member should generate a member.removed audit entry."""
    # Save admin auth before helper overwrites the shared session headers
    client_a, _ = authenticated_client
    admin_token = api_client_session.headers.get("Authorization")

    client_b, user_b_data, slug, _ = _create_team_and_user_b(
        api_client_session, authenticated_client, "al-removed"
    )

    user_b_id = user_b_data.get("id") or user_b_data.get("user_id")
    if not user_b_id:
        pytest.skip(f"Cannot determine user B id from registration response: {user_b_data}")

    # Restore admin auth
    api_client_session.headers["Authorization"] = admin_token
    remove_resp = client_a.delete(f"/api/teams/{slug}/members/{user_b_id}")
    assert remove_resp.status_code in (200, 204), f"Remove failed: {remove_resp.text}"

    log_resp = client_a.get(f"/api/teams/{slug}/audit-log")
    assert log_resp.status_code == 200, f"Audit log fetch failed: {log_resp.text}"

    logs = log_resp.json()
    actions = [entry["action"] for entry in logs]
    assert "member.removed" in actions, f"Expected member.removed in {actions}"


@pytest.mark.integration
def test_audit_log_records_invitation_revoked(authenticated_client):
    """Revoking an email invitation should generate an invitation.revoked entry."""
    client, _ = authenticated_client
    slug = f"al-revoke-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Revoke Audit", "slug": slug})

    inv_resp = client.post(
        f"/api/teams/{slug}/members/invite",
        json={"email": f"revokee-{uuid4().hex[:8]}@example.com", "role": "editor"},
    )
    assert inv_resp.status_code in (200, 201), f"Invite failed: {inv_resp.text}"
    inv_id = inv_resp.json().get("id")
    if not inv_id:
        pytest.skip(f"No invitation id in response: {inv_resp.json()}")

    revoke_resp = client.delete(f"/api/teams/{slug}/invitations/{inv_id}")
    assert revoke_resp.status_code in (200, 204), f"Revoke failed: {revoke_resp.text}"

    log_resp = client.get(f"/api/teams/{slug}/audit-log")
    assert log_resp.status_code == 200, f"Audit log fetch failed: {log_resp.text}"

    logs = log_resp.json()
    actions = [entry["action"] for entry in logs]
    assert "invitation.revoked" in actions, f"Expected invitation.revoked in {actions}"


@pytest.mark.integration
def test_audit_log_filter_by_action(authenticated_client):
    """Filtering by action should return only matching entries."""
    client, _ = authenticated_client
    slug = f"al-filt-act-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Filter Action", "slug": slug})
    # Invite generates member.invited
    client.post(
        f"/api/teams/{slug}/members/invite",
        json={"email": f"filter-{uuid4().hex[:8]}@example.com", "role": "viewer"},
    )

    # Filter for team.created only
    resp_created = client.get(f"/api/teams/{slug}/audit-log", params={"action": "team.created"})
    assert resp_created.status_code == 200
    logs_created = resp_created.json()
    for entry in logs_created:
        assert entry["action"] == "team.created", (
            f"Expected only team.created, got {entry['action']}"
        )

    # Filter for member.invited only
    resp_invited = client.get(f"/api/teams/{slug}/audit-log", params={"action": "member.invited"})
    assert resp_invited.status_code == 200
    logs_invited = resp_invited.json()
    for entry in logs_invited:
        assert entry["action"] == "member.invited", (
            f"Expected only member.invited, got {entry['action']}"
        )


@pytest.mark.integration
def test_audit_log_filter_by_resource_type(authenticated_client, api_client_session):
    """Filtering by resource_type should return only matching entries."""
    # Capture admin auth BEFORE helper overwrites the shared session headers
    client_a, _ = authenticated_client
    admin_token = api_client_session.headers.get("Authorization")

    _, _, slug, _ = _create_team_and_user_b(api_client_session, authenticated_client, "al-filt-rt")

    # Restore admin auth (helper left User B's token on the shared session)
    api_client_session.headers["Authorization"] = admin_token

    # Filter for team resource type
    resp_team = client_a.get(f"/api/teams/{slug}/audit-log", params={"resource_type": "team"})
    assert resp_team.status_code == 200
    logs_team = resp_team.json()
    for entry in logs_team:
        assert entry["resource_type"] == "team", (
            f"Expected resource_type=team, got {entry['resource_type']}"
        )

    # Filter for team_membership resource type
    resp_membership = client_a.get(
        f"/api/teams/{slug}/audit-log", params={"resource_type": "team_membership"}
    )
    assert resp_membership.status_code == 200
    logs_membership = resp_membership.json()
    for entry in logs_membership:
        assert entry["resource_type"] == "team_membership", (
            f"Expected resource_type=team_membership, got {entry['resource_type']}"
        )


@pytest.mark.integration
def test_audit_log_pagination(authenticated_client):
    """Pagination should limit results correctly."""
    client, _ = authenticated_client
    slug = f"al-page-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Pagination Team", "slug": slug})

    # Generate extra audit entries via updates and invites
    for i in range(3):
        client.patch(f"/api/teams/{slug}", json={"name": f"Paginated {i}"})

    # Request page 1 with per_page=2
    resp_p1 = client.get(f"/api/teams/{slug}/audit-log", params={"page": 1, "per_page": 2})
    assert resp_p1.status_code == 200
    logs_p1 = resp_p1.json()
    assert len(logs_p1) <= 2, f"Expected at most 2 entries, got {len(logs_p1)}"

    # Request page 2 with per_page=2
    resp_p2 = client.get(f"/api/teams/{slug}/audit-log", params={"page": 2, "per_page": 2})
    assert resp_p2.status_code == 200
    logs_p2 = resp_p2.json()

    # Pages should not overlap (different ids)
    ids_p1 = {entry["id"] for entry in logs_p1}
    ids_p2 = {entry["id"] for entry in logs_p2}
    assert ids_p1.isdisjoint(ids_p2), "Page 1 and page 2 should not share entries"


@pytest.mark.integration
def test_audit_log_export_admin_only(authenticated_client, api_client_session):
    """Only admins can export audit log as CSV. Editors and viewers get 403."""
    # Save admin auth before helper overwrites the shared session headers
    client_a, _ = authenticated_client
    admin_token = api_client_session.headers.get("Authorization")

    # Create team and add User B as editor
    client_b, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "al-export", role="editor"
    )

    export_body = {}

    # Restore admin auth
    api_client_session.headers["Authorization"] = admin_token
    admin_resp = client_a.post(f"/api/teams/{slug}/audit-log/export", json=export_body)
    assert admin_resp.status_code == 200, f"Admin export failed: {admin_resp.text}"

    # Editor should be denied
    client_b.headers["Authorization"] = f"Bearer {token_b}"
    editor_resp = client_b.post(f"/api/teams/{slug}/audit-log/export", json=export_body)
    assert editor_resp.status_code == 403, (
        f"Editor export should be 403, got {editor_resp.status_code}: {editor_resp.text}"
    )

    # Create viewer User C — restore admin auth first
    api_client_session.headers["Authorization"] = admin_token
    email_c = f"userc-{uuid4().hex[:8]}@example.com"
    link_resp = client_a.post(f"/api/teams/{slug}/members/link", json={"role": "viewer"})
    assert link_resp.status_code in (200, 201)
    viewer_token_link = link_resp.json()["token"]

    api_client_session.headers.pop("Authorization", None)
    reg_c = api_client_session.post(
        "/api/auth/register",
        json={"email": email_c, "password": "TestPass123!", "name": "User C"},
    )
    assert reg_c.status_code == 201
    login_c = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email_c, "password": "TestPass123!"},
    )
    token_c = login_c.json()["access_token"]
    api_client_session.headers["Authorization"] = f"Bearer {token_c}"
    accept_c = api_client_session.post(f"/api/teams/invitations/{viewer_token_link}/accept")
    assert accept_c.status_code == 200

    # Viewer should be denied
    api_client_session.headers["Authorization"] = f"Bearer {token_c}"
    viewer_resp = api_client_session.post(f"/api/teams/{slug}/audit-log/export", json=export_body)
    assert viewer_resp.status_code == 403, (
        f"Viewer export should be 403, got {viewer_resp.status_code}: {viewer_resp.text}"
    )


@pytest.mark.integration
def test_viewer_cannot_view_audit_log(authenticated_client, api_client_session):
    """Viewers must NOT be able to read the audit log — AUDIT_VIEW is admin-only.

    Regression guard: `_VIEWER_PERMISSIONS` previously auto-included every
    permission whose value ended in `.view`, which unintentionally granted
    AUDIT_VIEW to viewers and editors. See docs/testing/rbac-manual-testing.md
    Bug #4 for the full history.
    """
    client_b, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "al-viewer", role="viewer"
    )

    client_b.headers["Authorization"] = f"Bearer {token_b}"
    log_resp = client_b.get(f"/api/teams/{slug}/audit-log")

    assert log_resp.status_code == 403, (
        f"Viewer must be blocked from audit log, got {log_resp.status_code}: {log_resp.text}"
    )


@pytest.mark.integration
def test_editor_cannot_view_audit_log(authenticated_client, api_client_session):
    """Editors must NOT be able to read the audit log — AUDIT_VIEW is admin-only."""
    client_b, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "al-editor-audit", role="editor"
    )

    client_b.headers["Authorization"] = f"Bearer {token_b}"
    log_resp = client_b.get(f"/api/teams/{slug}/audit-log")

    assert log_resp.status_code == 403, (
        f"Editor must be blocked from audit log, got {log_resp.status_code}: {log_resp.text}"
    )


@pytest.mark.integration
def test_audit_log_has_required_fields(authenticated_client):
    """Each audit log entry should contain required fields."""
    client, _ = authenticated_client
    slug = f"al-fields-{uuid4().hex[:8]}"

    client.post("/api/teams", json={"name": "Fields Team", "slug": slug})

    log_resp = client.get(f"/api/teams/{slug}/audit-log")
    assert log_resp.status_code == 200
    logs = log_resp.json()
    assert len(logs) >= 1, "Expected at least one audit log entry"

    required_fields = {"id", "action", "user_id", "resource_type", "created_at"}
    for entry in logs:
        missing = required_fields - set(entry.keys())
        assert not missing, f"Entry missing required fields {missing}: {entry}"


@pytest.mark.integration
def test_member_leave_creates_audit_entry(authenticated_client, api_client_session):
    """When User B leaves a team, a member.left audit entry should be created."""
    # Save admin auth before helper overwrites the shared session headers
    client_a, _ = authenticated_client
    admin_token = api_client_session.headers.get("Authorization")

    client_b, _, slug, token_b = _create_team_and_user_b(
        api_client_session, authenticated_client, "al-leave"
    )

    # User B leaves the team
    client_b.headers["Authorization"] = f"Bearer {token_b}"
    leave_resp = client_b.post(f"/api/teams/{slug}/leave")
    assert leave_resp.status_code == 200, f"Leave failed: {leave_resp.text}"

    # Restore admin auth and read the audit log
    api_client_session.headers["Authorization"] = admin_token
    log_resp = client_a.get(f"/api/teams/{slug}/audit-log")
    assert log_resp.status_code == 200, f"Audit log fetch failed: {log_resp.text}"

    logs = log_resp.json()
    actions = [entry["action"] for entry in logs]
    assert "member.left" in actions, f"Expected member.left in {actions}"
