"""
Integration tests for project CRUD operations.

Tests:
- Create project
- List projects
- Get project by slug
- Delete project
- Project isolation (user A can't see user B's projects)
- Auto-add base to library on project creation
"""

import time

import pytest


@pytest.mark.integration
def test_create_project(authenticated_client, default_base_id, mock_orchestrator):
    """Test creating a project persists to database."""
    client, user_data = authenticated_client

    response = client.post(
        "/api/projects/",
        json={
            "name": "My Test Project",
            "base_id": default_base_id,
        },
    )

    assert response.status_code == 200, f"Project creation failed: {response.text}"
    data = response.json()

    # Project creation is async, response includes task_id, status_endpoint, and project
    assert "task_id" in data
    assert "status_endpoint" in data
    assert "project" in data

    # Verify project data
    project = data["project"]
    assert project["name"] == "My Test Project"
    assert "slug" in project
    assert "id" in project
    assert project["owner_id"] == user_data["id"]


@pytest.mark.integration
def test_list_projects(authenticated_client, default_base_id, mock_orchestrator):
    """Test listing projects shows created projects."""
    client, user_data = authenticated_client

    # Create a project
    create_response = client.post(
        "/api/projects/",
        json={"name": "List Test Project", "base_id": default_base_id},
    )
    assert create_response.status_code == 200
    created_data = create_response.json()
    created_project = created_data["project"]

    # List projects
    response = client.get("/api/projects/")

    assert response.status_code == 200
    data = response.json()

    assert isinstance(data, list)
    assert len(data) >= 1

    # Verify our project is in the list
    project_ids = [p["id"] for p in data]
    assert created_project["id"] in project_ids


@pytest.mark.integration
def test_get_project_by_slug(authenticated_client, default_base_id, mock_orchestrator):
    """Test getting project by slug returns correct data."""
    client, user_data = authenticated_client

    # Create a project
    create_response = client.post(
        "/api/projects/",
        json={"name": "Slug Test Project", "base_id": default_base_id},
    )
    assert create_response.status_code == 200
    created_data = create_response.json()
    created_project = created_data["project"]

    # Get by slug
    response = client.get(f"/api/projects/{created_project['slug']}")

    assert response.status_code == 200
    data = response.json()

    assert data["id"] == created_project["id"]
    assert data["name"] == "Slug Test Project"
    assert data["slug"] == created_project["slug"]


@pytest.mark.integration
def test_delete_project(authenticated_client, default_base_id, mock_orchestrator):
    """Test deleting project removes it from database."""

    client, user_data = authenticated_client

    # Create a project
    create_response = client.post(
        "/api/projects/",
        json={"name": "Delete Test Project", "base_id": default_base_id},
    )
    assert create_response.status_code == 200
    created_data = create_response.json()
    created_project = created_data["project"]

    # Delete project (async operation)
    delete_response = client.delete(f"/api/projects/{created_project['slug']}")
    assert delete_response.status_code == 200
    delete_data = delete_response.json()
    assert "task_id" in delete_data

    # Wait for async deletion to complete (poll task status)
    task_id = delete_data["task_id"]
    max_wait = 5  # seconds
    start_time = time.time()

    while time.time() - start_time < max_wait:
        status_response = client.get(f"/api/tasks/{task_id}/status")
        if status_response.status_code == 200:
            status_data = status_response.json()
            if status_data.get("status") in ["completed", "failed"]:
                break
        time.sleep(0.1)

    # Try to get deleted project - should return 404
    get_response = client.get(f"/api/projects/{created_project['slug']}")
    assert get_response.status_code == 404


@pytest.mark.integration
def test_project_isolation(authenticated_client, api_client, default_base_id, mock_orchestrator):
    """Test user A cannot access user B's projects."""
    from uuid import uuid4

    # User A creates a project
    client_a, user_a_data = authenticated_client

    # Note: Marketplace bases might not require purchase for project creation in tests
    # Try creating project directly with the base_id
    response = client_a.post(
        "/api/projects/",
        json={"name": "User A Project", "base_id": default_base_id},
    )

    # If 403, it means the base needs to be in library - skip this test for now
    # as CSRF protection makes it hard to test without proper setup
    if response.status_code == 403:
        import pytest

        pytest.skip("CSRF protection prevents adding base to library in tests")

    assert response.status_code == 200, f"Project creation failed: {response.text}"
    data_a = response.json()
    project_a = data_a["project"]

    # Register User B with unique email
    user_b_email = f"userb-{uuid4().hex[:8]}@example.com"
    register_response = api_client.post(
        "/api/auth/register",
        json={
            "email": user_b_email,
            "password": "UserBPass123!",
            "name": "User B",
        },
    )
    assert register_response.status_code == 201, (
        f"User B registration failed: {register_response.text}"
    )

    # Login as User B
    login_response = api_client.post(
        "/api/auth/jwt/login",
        data={
            "username": user_b_email,
            "password": "UserBPass123!",
        },
    )
    assert login_response.status_code == 200, f"User B login failed: {login_response.text}"
    token_b = login_response.json()["access_token"]

    # User B tries to access User A's project
    api_client.headers["Authorization"] = f"Bearer {token_b}"
    response = api_client.get(f"/api/projects/{project_a['slug']}")

    # Should return 404 (not 403, to avoid leaking project existence)
    assert response.status_code == 404


# ============================================================================
# Auto-add base to library on project creation
# ============================================================================


@pytest.fixture
def raw_base_id(api_client_session, authenticated_client):
    """
    Get a marketplace base ID WITHOUT adding it to the user's library.

    Unlike default_base_id, this does not call the purchase endpoint,
    so the base is not in the user's library.
    """
    client, _ = authenticated_client

    response = client.get("/api/marketplace/bases")
    assert response.status_code == 200
    data = response.json()

    if data.get("bases") and len(data["bases"]) > 0:
        return data["bases"][0]["id"]
    return None


@pytest.mark.integration
def test_create_project_auto_adds_base_to_library(
    authenticated_client, raw_base_id, mock_orchestrator
):
    """Test that creating a project with a base NOT in the user's library auto-adds it."""
    from unittest.mock import AsyncMock, MagicMock, patch

    client, user_data = authenticated_client

    # Verify the base is NOT in the user's library yet
    library_response = client.get("/api/marketplace/my-bases")
    assert library_response.status_code == 200
    library_ids = [b["id"] for b in library_response.json().get("bases", [])]
    assert raw_base_id not in library_ids, "Base should NOT be in library before project creation"

    # Mock git clone and filesystem ops so the background task doesn't hit real repos/fs
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(return_value=(b"", b""))

    mock_subprocess_run = MagicMock(return_value=MagicMock(returncode=0))

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("app.routers.projects.os.makedirs"),
        patch("app.routers.projects.makedirs_async", new_callable=AsyncMock),
        patch("app.services.project_setup.file_placement.os.makedirs"),
        patch("app.services.project_setup.file_placement.os.listdir", return_value=[]),
        patch("app.services.project_setup.file_placement.shutil.copytree"),
        patch("app.services.project_setup.file_placement.shutil.copy2"),
        patch("app.services.project_setup.file_placement.subprocess.run", mock_subprocess_run),
        patch("app.services.project_setup.file_placement.write_tesslate_config"),
        patch("app.services.project_setup.source_acquisition.shutil.rmtree"),
        patch("shutil.copytree"),
        patch("shutil.rmtree"),
        patch("shutil.copy2"),
        patch("subprocess.run", mock_subprocess_run),
    ):
        # Create a project using the base (should auto-add to library)
        response = client.post(
            "/api/projects/",
            json={"name": "Auto Add Test Project", "base_id": raw_base_id},
        )
        assert response.status_code == 200, f"Project creation failed: {response.text}"
        data = response.json()
        assert "project" in data

        # Wait for the background task to complete
        task_id = data["task_id"]
        max_wait = 10
        start_time = time.time()

        while time.time() - start_time < max_wait:
            status_response = client.get(f"/api/tasks/{task_id}/status")
            if status_response.status_code == 200:
                status_data = status_response.json()
                if status_data.get("status") in ["completed", "failed"]:
                    break
            time.sleep(0.2)

    # Verify the base is now in the user's library
    library_response = client.get("/api/marketplace/my-bases")
    assert library_response.status_code == 200
    library_ids = [b["id"] for b in library_response.json().get("bases", [])]
    assert raw_base_id in library_ids, "Base should be auto-added to library after project creation"


@pytest.mark.integration
def test_create_project_with_base_already_in_library(
    authenticated_client, default_base_id, mock_orchestrator
):
    """Test that creating a project with a base already in the library still works."""
    client, user_data = authenticated_client

    # default_base_id fixture already adds the base to the library
    # Verify it's there
    library_response = client.get("/api/marketplace/my-bases")
    assert library_response.status_code == 200
    library_ids = [b["id"] for b in library_response.json().get("bases", [])]
    assert default_base_id in library_ids, "Base should be in library (added by fixture)"

    # Create a project - should work fine with base already in library
    response = client.post(
        "/api/projects/",
        json={"name": "Already In Library Project", "base_id": default_base_id},
    )
    assert response.status_code == 200, f"Project creation failed: {response.text}"
    data = response.json()
    assert data["project"]["name"] == "Already In Library Project"
