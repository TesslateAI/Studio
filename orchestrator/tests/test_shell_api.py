"""
Integration tests for Shell API
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from app.main import app
from app.models import User, Project, ShellSession
from app.database import Base, engine


@pytest.fixture
async def async_client():
    """Create async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
async def db_session():
    """Create test database session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def test_user(db_session):
    """Create a test user."""
    from app.auth import get_password_hash

    user = User(
        name="Test User",
        username="testuser",
        email="test@example.com",
        hashed_password=get_password_hash("testpass"),
        is_active=True
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_project(db_session, test_user):
    """Create a test project."""
    project = Project(
        name="Test Project",
        description="Test project for shell sessions",
        owner_id=test_user.id
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def auth_token(async_client, test_user):
    """Get auth token for test user."""
    response = await async_client.post("/api/auth/token", data={
        "username": "testuser",
        "password": "testpass"
    })
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
class TestShellSessionAPI:
    """Test Shell Session REST API endpoints."""

    async def test_create_session_success(
        self,
        async_client,
        auth_token,
        test_project
    ):
        """Test creating a shell session successfully."""
        with patch('app.services.shell_session_manager.get_shell_session_manager') as mock_manager:
            mock_instance = Mock()
            mock_instance.create_session = AsyncMock(return_value={
                "session_id": "test-session-123",
                "status": "active",
                "created_at": datetime.utcnow().isoformat()
            })
            mock_manager.return_value = mock_instance

            response = await async_client.post(
                "/api/shell/sessions",
                json={
                    "project_id": test_project.id,
                    "command": "/bin/bash",
                    "cwd": "/app/project"
                },
                headers={"Authorization": f"Bearer {auth_token}"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "session_id" in data
            assert data["status"] == "active"

    async def test_create_session_unauthorized(self, async_client, test_project):
        """Test creating session without authentication fails."""
        response = await async_client.post(
            "/api/shell/sessions",
            json={"project_id": test_project.id}
        )

        assert response.status_code == 401

    async def test_write_to_session(
        self,
        async_client,
        auth_token,
        db_session,
        test_user,
        test_project
    ):
        """Test writing to a shell session."""
        # Create a mock session in DB
        shell_session = ShellSession(
            session_id="test-session-123",
            user_id=test_user.id,
            project_id=test_project.id,
            container_name="test-container",
            status="active"
        )
        db_session.add(shell_session)
        await db_session.commit()

        with patch('app.services.shell_session_manager.get_shell_session_manager') as mock_manager:
            mock_instance = Mock()
            mock_instance.write_to_session = AsyncMock()
            mock_manager.return_value = mock_instance

            response = await async_client.post(
                f"/api/shell/sessions/{shell_session.session_id}/write",
                json={"data": "echo test\n"},
                headers={"Authorization": f"Bearer {auth_token}"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["bytes_written"] > 0

    async def test_read_session_output(
        self,
        async_client,
        auth_token,
        db_session,
        test_user,
        test_project
    ):
        """Test reading output from a shell session."""
        import base64

        # Create a mock session in DB
        shell_session = ShellSession(
            session_id="test-session-123",
            user_id=test_user.id,
            project_id=test_project.id,
            container_name="test-container",
            status="active"
        )
        db_session.add(shell_session)
        await db_session.commit()

        with patch('app.services.shell_session_manager.get_shell_session_manager') as mock_manager:
            mock_instance = Mock()
            mock_output = b"test output\n"
            mock_instance.read_output = AsyncMock(return_value={
                "output": base64.b64encode(mock_output).decode('utf-8'),
                "bytes": len(mock_output),
                "is_eof": False
            })
            mock_manager.return_value = mock_instance

            response = await async_client.get(
                f"/api/shell/sessions/{shell_session.session_id}/output",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "output" in data
            assert data["bytes"] > 0
            assert data["is_eof"] is False

    async def test_list_sessions(
        self,
        async_client,
        auth_token,
        db_session,
        test_user,
        test_project
    ):
        """Test listing all active sessions."""
        with patch('app.services.shell_session_manager.get_shell_session_manager') as mock_manager:
            mock_instance = Mock()
            mock_instance.list_sessions = AsyncMock(return_value=[
                {
                    "session_id": "session-1",
                    "project_id": test_project.id,
                    "command": "/bin/bash",
                    "working_dir": "/app/project",
                    "created_at": datetime.utcnow().isoformat(),
                    "last_activity_at": datetime.utcnow().isoformat(),
                    "bytes_read": 0,
                    "bytes_written": 0,
                    "total_reads": 0
                }
            ])
            mock_manager.return_value = mock_instance

            response = await async_client.get(
                "/api/shell/sessions",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "sessions" in data
            assert isinstance(data["sessions"], list)

    async def test_close_session(
        self,
        async_client,
        auth_token,
        db_session,
        test_user,
        test_project
    ):
        """Test closing a shell session."""
        # Create a mock session in DB
        shell_session = ShellSession(
            session_id="test-session-123",
            user_id=test_user.id,
            project_id=test_project.id,
            container_name="test-container",
            status="active"
        )
        db_session.add(shell_session)
        await db_session.commit()

        with patch('app.services.shell_session_manager.get_shell_session_manager') as mock_manager:
            mock_instance = Mock()
            mock_instance.close_session = AsyncMock()
            mock_manager.return_value = mock_instance

            response = await async_client.delete(
                f"/api/shell/sessions/{shell_session.session_id}",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "message" in data

    async def test_get_session_details(
        self,
        async_client,
        auth_token,
        db_session,
        test_user,
        test_project
    ):
        """Test getting session details."""
        # Create a mock session in DB
        shell_session = ShellSession(
            session_id="test-session-123",
            user_id=test_user.id,
            project_id=test_project.id,
            container_name="test-container",
            command="/bin/bash",
            working_dir="/app/project",
            status="active"
        )
        db_session.add(shell_session)
        await db_session.commit()

        response = await async_client.get(
            f"/api/shell/sessions/{shell_session.session_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == shell_session.session_id
        assert data["project_id"] == test_project.id
        assert data["status"] == "active"

    async def test_access_other_user_session_fails(
        self,
        async_client,
        auth_token,
        db_session,
        test_project
    ):
        """Test that users cannot access other users' sessions."""
        # Create a session for a different user
        shell_session = ShellSession(
            session_id="test-session-123",
            user_id=999,  # Different user
            project_id=test_project.id,
            container_name="test-container",
            status="active"
        )
        db_session.add(shell_session)
        await db_session.commit()

        response = await async_client.get(
            f"/api/shell/sessions/{shell_session.session_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )

        assert response.status_code == 404
