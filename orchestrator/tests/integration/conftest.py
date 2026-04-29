"""
Integration test fixtures for real-database testing.

Uses TestClient with real PostgreSQL database on port 5433.
Environment variables are set by tests/conftest.py before any imports.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# Add orchestrator to path (redundant if parent conftest already did this)
orchestrator_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(orchestrator_dir))


# Test database connection string (port 5433)
TEST_DATABASE_URL = "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test"


@pytest.fixture(scope="session", autouse=True)
def test_db_container():
    """
    Manage the test PostgreSQL container lifecycle.

    Checks if postgres is already accepting connections on port 5433
    (e.g. CI service container). If not, starts docker-compose.test.yml
    and tears it down after the session.
    """
    import socket
    import subprocess
    import time

    repo_root = Path(__file__).parent.parent.parent.parent

    # Check if port 5433 is already reachable (e.g., CI service container)
    def _port_open(port: int = 5433) -> bool:
        try:
            with socket.create_connection(("localhost", port), timeout=2):
                return True
        except OSError:
            return False

    if _port_open():
        # DB already available (CI service or manually started) — skip docker
        yield
        return

    started_by_us = False
    if not _port_open():
        result = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.test.yml", "up", "-d", "--wait"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start test DB: {result.stderr}")
        started_by_us = True

        # Wait for postgres to accept connections
        for _ in range(30):
            if _port_open():
                break
            time.sleep(1)
        else:
            raise RuntimeError("Test postgres did not become ready in 30s")

    yield

    # Tear down only if we started it
    if started_by_us:
        subprocess.run(
            ["docker", "compose", "-f", "docker-compose.test.yml", "down", "-v"],
            cwd=repo_root,
            capture_output=True,
        )


@pytest.fixture(scope="session", autouse=True)
def setup_database(test_db_container):
    """
    Run database migrations once per test session.

    Uses alembic to bring the test database to latest schema.
    Depends on test_db_container to ensure postgres is running first.
    """
    import subprocess

    # Get directory where alembic.ini is located
    base_dir = Path(__file__).parent.parent.parent

    # Run alembic upgrade head — invoke via current python interpreter
    # (`sys.executable -m alembic`) so the venv's alembic is used regardless
    # of PATH state. Avoids FileNotFoundError when pytest is run via
    # `.venv/bin/python -m pytest` from a non-activated shell.
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=base_dir,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
    )

    if result.returncode != 0:
        raise RuntimeError(f"Alembic migration failed: {result.stderr}")

    yield


@pytest.fixture(scope="session")
def api_client_session():
    """
    Unauthenticated TestClient for FastAPI (session-scoped).

    Session scope creates one client for all tests, avoiding event loop conflicts.
    """
    from app.main import app

    with TestClient(app, base_url="http://test") as client:
        yield client


@pytest.fixture
def api_client(api_client_session):
    """
    Per-test api_client that uses the session-scoped client.

    Clears headers between tests for isolation.
    """
    # Clear any auth headers from previous tests
    api_client_session.headers.pop("Authorization", None)
    return api_client_session


@pytest.fixture
def default_base_id(api_client_session, authenticated_client):
    """
    Get a default marketplace base ID and add it to user's library.

    Project creation requires the base to be in the user's library first.
    """
    client, user_data = authenticated_client

    # Get available bases
    response = client.get("/api/marketplace/bases")
    assert response.status_code == 200
    data = response.json()

    if data.get("bases") and len(data["bases"]) > 0:
        base_id = data["bases"][0]["id"]

        # Add base to user's library (free bases can be added without purchase)
        # This simulates clicking the "+ Add to Library" button
        client.post(f"/api/marketplace/bases/{base_id}/purchase")
        # If it's a free base or already purchased, this should succeed or return 200
        # We don't assert here since it might already be in the library

        return base_id
    return None


@pytest.fixture
def authenticated_client(api_client_session):
    """
    Authenticated client with Bearer token.

    Returns: (client, user_data) tuple
    - client: TestClient with Authorization header set
    - user_data: dict with user fields (id, email, slug, etc.)
    """
    # Register a test user with unique email
    register_data = {
        "email": f"test-{uuid4().hex}@example.com",
        "password": "TestPassword123!",
        "name": "Integration Test User",
    }

    response = api_client_session.post("/api/auth/register", json=register_data)
    assert response.status_code == 201, f"Registration failed: {response.text}"
    user_data = response.json()

    # Login to get JWT token
    login_data = {
        "username": register_data["email"],  # fastapi-users uses "username" field for email
        "password": register_data["password"],
    }

    response = api_client_session.post(
        "/api/auth/jwt/login",
        data=login_data,  # form data, not JSON
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    token_data = response.json()

    # Set Authorization header
    api_client_session.headers["Authorization"] = f"Bearer {token_data['access_token']}"

    yield api_client_session, user_data

    # Cleanup: remove auth header after test
    api_client_session.headers.pop("Authorization", None)


@pytest.fixture(scope="function")
def mock_orchestrator():
    """
    Mock Docker/Kubernetes orchestrator and file operations for project tests.

    Integration tests focus on API and database, not actual container orchestration.
    Only applies to tests that explicitly request this fixture.
    """
    with (
        patch("app.services.orchestration.get_orchestrator") as mock_get_orch,
        patch("app.routers.projects.makedirs_async") as mock_makedirs,
        patch("app.routers.projects.walk_directory_async") as mock_walk,
        patch("app.routers.projects.read_file_async") as mock_read,
        patch("pathlib.Path.mkdir") as mock_mkdir,
    ):
        # Create a mock orchestrator
        mock_orch = AsyncMock()
        mock_orch.create_project = AsyncMock(return_value=True)
        mock_orch.start_project = AsyncMock(return_value=True)
        mock_orch.stop_project = AsyncMock(return_value=True)
        mock_orch.delete_project = AsyncMock(return_value=True)
        # list_tree / read_file / write_file are called by file-tree and file
        # operations tests. Return concrete values so FastAPI can serialize the
        # response without recursing through bare AsyncMock objects.
        mock_orch.list_tree = AsyncMock(return_value=[])
        mock_orch.read_file = AsyncMock(return_value="")
        mock_orch.write_file = AsyncMock(return_value=True)
        mock_orch.delete_file = AsyncMock(return_value=True)
        mock_orch.get_project_status = AsyncMock(
            return_value={"status": "inactive", "containers": {}}
        )

        mock_get_orch.return_value = mock_orch

        # Mock file operations
        mock_makedirs.return_value = AsyncMock()
        mock_walk.return_value = AsyncMock(return_value=[])
        mock_read.return_value = AsyncMock(return_value="")
        mock_mkdir.return_value = None

        yield mock_orch


@pytest.fixture(autouse=True, scope="session")
def mock_external_services():
    """
    Auto-mock external services to prevent real API calls during tests.

    Mocks:
    - Stripe (customer creation, subscriptions)
    - LiteLLM (user provisioning)
    - Discord (webhooks)
    - Email (SMTP)

    Session-scoped to maintain unique API key generation across all tests.
    """

    def mock_create_user_key(*args, **kwargs):
        """Generate unique API keys for each user using uuid."""
        unique_id = uuid4().hex[:8]
        return {
            "api_key": f"sk-test-litellm-{unique_id}",
            "litellm_user_id": f"litellm-user-{unique_id}",
        }

    with (
        patch("app.services.stripe_service.stripe_service.create_customer") as mock_stripe,
        patch("app.services.litellm_service.litellm_service.create_user_key") as mock_litellm,
        patch(
            "app.services.discord_service.discord_service.send_signup_notification"
        ) as mock_discord,
        patch(
            "app.services.discord_service.discord_service.send_login_notification"
        ) as mock_discord_login,
    ):
        # Stripe mock
        mock_stripe.return_value = {"id": "cus_test123"}

        # LiteLLM mock - returns unique keys
        mock_litellm.side_effect = mock_create_user_key

        # Discord mocks (async)
        mock_discord.return_value = AsyncMock()
        mock_discord_login.return_value = AsyncMock()

        yield {
            "stripe": mock_stripe,
            "litellm": mock_litellm,
            "discord": mock_discord,
            "discord_login": mock_discord_login,
        }
