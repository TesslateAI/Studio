"""
Integration tests for the access + refresh token pair system.

Tests:
- Login sets refresh cookie + returns access JWT
- Refresh via cookie returns new access token + rotates refresh token
- Refresh without cookie returns 401
- Refresh with revoked token returns 401
- Refresh with expired refresh token returns 401
- Logout revokes refresh token
- Post-logout refresh fails
- Token lifetime (15-min access JWT)
- Refresh chain (multiple consecutive refreshes)
- Cookie auth + refresh
"""

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt as jose_jwt


def _decode_token(token: str) -> dict:
    from app.config import get_settings

    settings = get_settings()
    return jose_jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.algorithm],
        options={"verify_exp": False, "verify_aud": False},
    )


def _extract_refresh_cookie(response) -> str | None:
    """Extract tesslate_refresh value from Set-Cookie header."""
    import re

    # httpx Response uses .headers.get_list() or multi_items()
    for key, value in response.headers.multi_items():
        if key.lower() == "set-cookie" and "tesslate_refresh=" in value:
            match = re.match(r"tesslate_refresh=([^;]+)", value)
            if match:
                return match.group(1)
    return None


def _login(client) -> tuple[dict, str]:
    """Register + login, return (user_data, access_token). Sets refresh cookie on client."""
    # Ensure clean state
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    from uuid import uuid4

    email = f"test-{uuid4().hex}@example.com"
    reg = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "SecurePass123!",
            "name": "Test User",
        },
    )
    assert reg.status_code == 201
    user_data = reg.json()

    login_resp = client.post(
        "/api/auth/login",
        data={
            "username": email,
            "password": "SecurePass123!",
        },
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    data = login_resp.json()
    assert "access_token" in data

    # Manually set the refresh cookie (TestClient doesn't auto-collect domain-scoped cookies)
    refresh_value = _extract_refresh_cookie(login_resp)
    assert refresh_value, "Login did not set tesslate_refresh cookie"
    client.cookies.set("tesslate_refresh", refresh_value)

    # Set Bearer header for authenticated calls
    client.headers["Authorization"] = f"Bearer {data['access_token']}"

    return user_data, data["access_token"]


# ---------------------------------------------------------------------------
# Login + access token
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_login_returns_access_token_and_sets_refresh_cookie(api_client_session):
    """Login should return access JWT and set tesslate_refresh cookie."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    _user_data, access_token = _login(client)

    # Access token should be a valid JWT
    payload = _decode_token(access_token)
    assert "sub" in payload
    assert "exp" in payload

    # Refresh cookie was already verified by _login helper
    assert client.cookies.get("tesslate_refresh") is not None

    client.headers.pop("Authorization", None)
    client.cookies.clear()


@pytest.mark.integration
def test_access_token_expires_in_15_minutes(api_client_session):
    """Freshly issued access token should expire ~15 minutes from now."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    _user_data, access_token = _login(client)

    payload = _decode_token(access_token)
    exp_dt = datetime.fromtimestamp(payload["exp"], tz=UTC)
    delta = exp_dt - datetime.now(UTC)

    assert timedelta(minutes=14) < delta < timedelta(minutes=16), (
        f"Token exp is {delta} from now, expected ~15 minutes"
    )

    client.headers.pop("Authorization", None)
    client.cookies.clear()


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_refresh_returns_new_access_token(api_client_session):
    """POST /api/auth/refresh with valid cookie returns new access JWT."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    _user_data, old_token = _login(client)

    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 200

    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 0

    # Update cookie for subsequent calls
    new_refresh = _extract_refresh_cookie(resp)
    if new_refresh:
        client.cookies.set("tesslate_refresh", new_refresh)

    client.headers.pop("Authorization", None)
    client.cookies.clear()


@pytest.mark.integration
def test_refresh_rotates_cookie(api_client_session):
    """Refresh should set a new tesslate_refresh cookie (rotation)."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    _login(client)

    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 200

    # The Set-Cookie header should contain a new tesslate_refresh
    set_cookie = resp.headers.get("set-cookie", "")
    assert "tesslate_refresh" in set_cookie

    client.headers.pop("Authorization", None)
    client.cookies.clear()


@pytest.mark.integration
def test_refresh_without_cookie_returns_401(api_client_session):
    """Refresh without any cookie returns 401."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "No refresh token"


@pytest.mark.integration
def test_refresh_with_invalid_cookie_returns_401(api_client_session):
    """Refresh with a garbage cookie returns 401."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()
    client.cookies.set("tesslate_refresh", "totally_invalid_token")

    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid refresh token"

    client.cookies.clear()


@pytest.mark.integration
def test_refreshed_token_works_for_api_calls(api_client_session):
    """The new access token from refresh should work for authenticated endpoints."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    user_data, _old_token = _login(client)

    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 200
    new_token = resp.json()["access_token"]

    # Update refresh cookie for future calls
    new_refresh = _extract_refresh_cookie(resp)
    if new_refresh:
        client.cookies.set("tesslate_refresh", new_refresh)

    client.headers["Authorization"] = f"Bearer {new_token}"
    me_resp = client.get("/api/users/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["id"] == user_data["id"]

    client.headers.pop("Authorization", None)
    client.cookies.clear()


# ---------------------------------------------------------------------------
# Logout + revocation
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_logout_revokes_refresh_token(api_client_session):
    """POST /api/auth/logout should revoke the refresh token."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    _login(client)

    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Logged out"

    client.headers.pop("Authorization", None)
    client.cookies.clear()


@pytest.mark.integration
def test_refresh_after_logout_fails(api_client_session):
    """After logout, the old refresh cookie should be rejected."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    _login(client)
    refresh_cookie = client.cookies.get("tesslate_refresh")

    # Logout
    client.post("/api/auth/logout")

    # Try to use the old refresh token
    client.cookies.clear()
    client.cookies.set("tesslate_refresh", refresh_cookie)

    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid refresh token"

    client.cookies.clear()


# ---------------------------------------------------------------------------
# Refresh chain
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_refresh_chain_three_consecutive(api_client_session):
    """Three consecutive refreshes should all succeed with token rotation."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    user_data, _token = _login(client)

    for i in range(3):
        resp = client.post("/api/auth/refresh")
        assert resp.status_code == 200, f"Refresh #{i + 1} failed: {resp.text}"

        new_token = resp.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {new_token}"

        # Update refresh cookie (rotation)
        new_refresh = _extract_refresh_cookie(resp)
        assert new_refresh, f"Refresh #{i + 1} did not set new cookie"
        client.cookies.set("tesslate_refresh", new_refresh)

        me_resp = client.get("/api/users/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["id"] == user_data["id"]

    client.headers.pop("Authorization", None)
    client.cookies.clear()


@pytest.mark.integration
def test_rotated_token_accepted_within_grace_window(api_client_session):
    """A just-rotated refresh token should still work within the 30s grace window (multi-tab safety)."""
    client = api_client_session
    client.headers.pop("Authorization", None)
    client.cookies.clear()

    _login(client)
    first_refresh = client.cookies.get("tesslate_refresh")

    # Refresh once (rotates the token)
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 200

    # Use the old (just-rotated) token immediately — should succeed due to grace window
    client.cookies.clear()
    client.cookies.set("tesslate_refresh", first_refresh)

    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 200
    assert "access_token" in resp.json()

    client.cookies.clear()
