"""
Integration tests for POST /api/auth/refresh endpoint.

Tests:
- Valid token refresh (bearer)
- No token provided
- Invalid/garbage token
- Token signed with wrong secret
- Expired token within 30-min grace window
- Expired token beyond grace window
- Token with non-existent user
- Token with invalid UUID in sub claim
- Inactive user token
- Cookie-based refresh
"""

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt as jose_jwt


@pytest.mark.integration
def test_refresh_valid_token(authenticated_client):
    """Refresh with a valid Bearer token returns a new access_token."""
    client, _user_data = authenticated_client

    response = client.post("/api/auth/refresh")

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 0


@pytest.mark.integration
def test_refresh_returns_valid_new_token(authenticated_client):
    """The refreshed token should decode successfully with exp >= the original."""
    client, _user_data = authenticated_client

    old_token = client.headers["Authorization"].replace("Bearer ", "")
    response = client.post("/api/auth/refresh")

    assert response.status_code == 200
    new_token = response.json()["access_token"]

    # Decode both tokens and verify the new one has a valid exp
    from app.config import get_settings

    settings = get_settings()
    old_payload = jose_jwt.decode(
        old_token,
        settings.secret_key,
        algorithms=[settings.algorithm],
        options={"verify_exp": False, "verify_aud": False},
    )
    new_payload = jose_jwt.decode(
        new_token,
        settings.secret_key,
        algorithms=[settings.algorithm],
        options={"verify_exp": False, "verify_aud": False},
    )

    # New token's exp should be >= old token's exp (freshly issued)
    assert new_payload["exp"] >= old_payload["exp"]
    # Both tokens should be for the same user
    assert new_payload["sub"] == old_payload["sub"]


@pytest.mark.integration
def test_refresh_new_token_is_valid(authenticated_client):
    """The refreshed token should work for authenticated API calls."""
    client, user_data = authenticated_client

    # Get new token
    response = client.post("/api/auth/refresh")
    assert response.status_code == 200
    new_token = response.json()["access_token"]

    # Use new token for /api/users/me
    client.headers["Authorization"] = f"Bearer {new_token}"
    me_response = client.get("/api/users/me")

    assert me_response.status_code == 200
    assert me_response.json()["id"] == user_data["id"]


@pytest.mark.integration
def test_refresh_no_token(api_client):
    """Refresh without any token returns 401."""
    response = api_client.post("/api/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "No token provided"


@pytest.mark.integration
def test_refresh_invalid_token(api_client):
    """Refresh with a garbage token returns 401."""
    api_client.headers["Authorization"] = "Bearer totally_invalid_jwt_string"

    response = api_client.post("/api/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"


@pytest.mark.integration
def test_refresh_wrong_secret_token(api_client):
    """Refresh with a token signed by a different secret returns 401."""
    # Create a JWT signed with a wrong secret
    fake_token = jose_jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000001", "aud": "fastapi-users:auth"},
        "wrong_secret_key",
        algorithm="HS256",
    )
    api_client.headers["Authorization"] = f"Bearer {fake_token}"

    response = api_client.post("/api/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"


@pytest.mark.integration
def test_refresh_expired_within_grace_window(authenticated_client):
    """Token expired less than 30 minutes ago should still refresh."""
    client, _user_data = authenticated_client
    old_token = client.headers["Authorization"].replace("Bearer ", "")

    # Decode current token to get secret/algorithm (we need to forge an expired one)
    from app.config import get_settings

    settings = get_settings()

    # Decode without verification to get payload
    payload = jose_jwt.decode(
        old_token,
        settings.secret_key,
        algorithms=[settings.algorithm],
        options={"verify_exp": False, "verify_aud": False},
    )

    # Set exp to 10 minutes ago (within 30-min grace window)
    payload["exp"] = (datetime.now(UTC) - timedelta(minutes=10)).timestamp()
    expired_token = jose_jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    client.headers["Authorization"] = f"Bearer {expired_token}"
    response = client.post("/api/auth/refresh")

    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.integration
def test_refresh_expired_beyond_grace_window(authenticated_client):
    """Token expired more than 30 minutes ago should fail."""
    client, _user_data = authenticated_client
    old_token = client.headers["Authorization"].replace("Bearer ", "")

    from app.config import get_settings

    settings = get_settings()

    payload = jose_jwt.decode(
        old_token,
        settings.secret_key,
        algorithms=[settings.algorithm],
        options={"verify_exp": False, "verify_aud": False},
    )

    # Set exp to 45 minutes ago (beyond 30-min grace window)
    payload["exp"] = (datetime.now(UTC) - timedelta(minutes=45)).timestamp()
    expired_token = jose_jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    client.headers["Authorization"] = f"Bearer {expired_token}"
    response = client.post("/api/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "Token expired beyond grace window"


@pytest.mark.integration
def test_refresh_nonexistent_user(api_client):
    """Token with a valid UUID that doesn't exist in DB returns 401."""
    from app.config import get_settings

    settings = get_settings()

    # Create a token for a user that doesn't exist
    payload = {
        "sub": "00000000-0000-0000-0000-999999999999",
        "aud": "fastapi-users:auth",
        "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
    }
    token = jose_jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    api_client.headers["Authorization"] = f"Bearer {token}"
    response = api_client.post("/api/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "User inactive or not found"


@pytest.mark.integration
def test_refresh_invalid_uuid_in_sub(api_client):
    """Token with a non-UUID sub claim returns 401."""
    from app.config import get_settings

    settings = get_settings()

    payload = {
        "sub": "not-a-valid-uuid",
        "aud": "fastapi-users:auth",
        "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
    }
    token = jose_jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    api_client.headers["Authorization"] = f"Bearer {token}"
    response = api_client.post("/api/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token payload"


@pytest.mark.integration
def test_refresh_missing_sub_claim(api_client):
    """Token with no sub claim returns 401."""
    from app.config import get_settings

    settings = get_settings()

    payload = {
        "aud": "fastapi-users:auth",
        "exp": (datetime.now(UTC) + timedelta(hours=1)).timestamp(),
    }
    token = jose_jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    api_client.headers["Authorization"] = f"Bearer {token}"
    response = api_client.post("/api/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token payload"


@pytest.mark.integration
def test_refresh_inactive_user(authenticated_client):
    """Refresh for an inactive user returns 401."""
    client, user_data = authenticated_client

    # Deactivate the user directly in DB using asyncpg
    import asyncpg

    async def set_user_active(active: bool):
        conn = await asyncpg.connect(
            "postgresql://tesslate_test:testpass@localhost:5433/tesslate_test"
        )
        try:
            await conn.execute(
                "UPDATE users SET is_active = $1 WHERE id = $2::uuid",
                active,
                user_data["id"],
            )
        finally:
            await conn.close()

    import asyncio

    asyncio.run(set_user_active(False))

    try:
        response = client.post("/api/auth/refresh")
        assert response.status_code == 401
        assert response.json()["detail"] == "User inactive or not found"
    finally:
        asyncio.run(set_user_active(True))


@pytest.mark.integration
def test_refresh_via_cookie(api_client_session):
    """Refresh via tesslate_auth cookie sets a new cookie on the response."""
    from uuid import uuid4

    # Register and login to get a token
    email = f"cookie-test-{uuid4().hex}@example.com"
    api_client_session.post(
        "/api/auth/register",
        json={"email": email, "password": "CookiePass123!", "name": "Cookie User"},
    )
    login_response = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": email, "password": "CookiePass123!"},
    )
    token = login_response.json()["access_token"]

    # Call refresh with cookie instead of header
    api_client_session.headers.pop("Authorization", None)
    api_client_session.cookies.set("tesslate_auth", token)

    try:
        response = api_client_session.post("/api/auth/refresh")

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # Verify response sets a new cookie
        set_cookie = response.headers.get("set-cookie", "")
        assert "tesslate_auth" in set_cookie
    finally:
        api_client_session.cookies.clear()
