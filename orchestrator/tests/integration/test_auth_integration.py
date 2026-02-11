"""
Integration tests for authentication flows.

Tests:
- User registration
- Login (JWT bearer token)
- Authenticated endpoints (/api/users/me)
- Duplicate email handling
- Invalid credentials
"""

import pytest


@pytest.mark.integration
def test_register_new_user(api_client):
    """Test user registration creates user with correct fields."""
    from uuid import uuid4

    test_email = f"newuser-{uuid4().hex}@example.com"
    response = api_client.post(
        "/api/auth/register",
        json={
            "email": test_email,
            "password": "SecurePass123!",
            "name": "New User",
        },
    )

    assert response.status_code == 201, f"Registration failed with: {response.text}"
    data = response.json()

    # Verify response fields
    assert data["email"] == test_email
    assert data["name"] == "New User"
    assert "id" in data
    assert "slug" in data
    assert "referral_code" in data
    assert "username" in data

    # Verify password is NOT in response
    assert "password" not in data
    assert "hashed_password" not in data


@pytest.mark.integration
def test_register_duplicate_email(api_client):
    """Test registering with duplicate email returns 400."""
    # Register first user
    api_client.post(
        "/api/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "Pass123!",
            "name": "First User",
        },
    )

    # Try to register again with same email
    response = api_client.post(
        "/api/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "DifferentPass456!",
            "name": "Second User",
        },
    )

    assert response.status_code == 400
    assert (
        "REGISTER_USER_ALREADY_EXISTS" in response.text or "already exists" in response.text.lower()
    )


@pytest.mark.integration
def test_login_with_jwt(api_client):
    """Test login returns JWT access token."""
    # Register user
    api_client.post(
        "/api/auth/register",
        json={
            "email": "logintest@example.com",
            "password": "LoginPass123!",
            "name": "Login Test",
        },
    )

    # Login
    response = api_client.post(
        "/api/auth/jwt/login",
        data={  # form data, not JSON
            "username": "logintest@example.com",  # fastapi-users uses "username" field
            "password": "LoginPass123!",
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.integration
def test_login_wrong_password(api_client):
    """Test login with wrong password returns 400."""
    # Register user
    api_client.post(
        "/api/auth/register",
        json={
            "email": "wrongpass@example.com",
            "password": "CorrectPass123!",
            "name": "Wrong Pass Test",
        },
    )

    # Try to login with wrong password
    response = api_client.post(
        "/api/auth/jwt/login",
        data={
            "username": "wrongpass@example.com",
            "password": "WrongPassword456!",
        },
    )

    assert response.status_code == 400
    assert "LOGIN_BAD_CREDENTIALS" in response.text or "credentials" in response.text.lower()


@pytest.mark.integration
def test_authenticated_users_me(authenticated_client):
    """Test /api/users/me returns current user profile."""
    client, user_data = authenticated_client

    response = client.get("/api/users/me")

    assert response.status_code == 200
    data = response.json()

    assert data["id"] == user_data["id"]
    assert data["email"] == user_data["email"]
    assert "slug" in data
    assert "subscription_tier" in data


@pytest.mark.integration
def test_unauthenticated_projects_list(api_client):
    """Test accessing protected endpoints without auth returns 401."""
    response = api_client.get("/api/projects/")

    assert response.status_code == 401
