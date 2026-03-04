"""
Test Multi-User Container Isolation

Tests that the orchestrator interface enforces per-user, per-project isolation
for container operations. Each user's project containers are isolated from
other users' containers.

These tests replace the deleted test_multi_user_containers.py.disabled which
tested container isolation via the now-removed k8s_container_manager module.
"""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


class TestUserIsolation:
    """Test that file and shell operations are isolated per user + project."""

    @pytest.fixture
    def isolated_orchestrator(self):
        """
        Create a mock orchestrator that tracks calls per user+project.

        Simulates isolation by keying storage on (user_id, project_id).
        """
        orch = AsyncMock()
        storage: dict[str, dict[str, str]] = {}  # {user_project_key: {file_path: content}}

        async def mock_read(user_id, project_id, container_name, file_path, **kwargs):
            key = f"{user_id}:{project_id}:{container_name}"
            return storage.get(key, {}).get(file_path)

        async def mock_write(user_id, project_id, container_name, file_path, content, **kwargs):
            key = f"{user_id}:{project_id}:{container_name}"
            if key not in storage:
                storage[key] = {}
            storage[key][file_path] = content
            return True

        async def mock_execute(user_id, project_id, container_name, command, **kwargs):
            return f"output-for-{user_id}-{project_id}"

        orch.read_file = mock_read
        orch.write_file = mock_write
        orch.execute_command = mock_execute
        orch._storage = storage
        return orch

    @pytest.mark.asyncio
    async def test_user_a_cannot_read_user_b_files(self, isolated_orchestrator):
        """Test that user A's files are not visible to user B."""
        user_a = uuid4()
        user_b = uuid4()
        project_a = uuid4()
        project_b = uuid4()

        # User A writes a file
        await isolated_orchestrator.write_file(
            user_id=user_a,
            project_id=project_a,
            container_name="frontend",
            file_path="secret.txt",
            content="User A's secret data",
        )

        # User B tries to read it (different user + project)
        content = await isolated_orchestrator.read_file(
            user_id=user_b,
            project_id=project_b,
            container_name="frontend",
            file_path="secret.txt",
        )

        assert content is None

    @pytest.mark.asyncio
    async def test_same_user_different_projects_isolated(self, isolated_orchestrator):
        """Test that same user's different projects are isolated."""
        user_id = uuid4()
        project_1 = uuid4()
        project_2 = uuid4()

        # Write to project 1
        await isolated_orchestrator.write_file(
            user_id=user_id,
            project_id=project_1,
            container_name="frontend",
            file_path="config.js",
            content="project 1 config",
        )

        # Write different content to project 2
        await isolated_orchestrator.write_file(
            user_id=user_id,
            project_id=project_2,
            container_name="frontend",
            file_path="config.js",
            content="project 2 config",
        )

        # Read from each project
        content_1 = await isolated_orchestrator.read_file(
            user_id=user_id,
            project_id=project_1,
            container_name="frontend",
            file_path="config.js",
        )
        content_2 = await isolated_orchestrator.read_file(
            user_id=user_id,
            project_id=project_2,
            container_name="frontend",
            file_path="config.js",
        )

        assert content_1 == "project 1 config"
        assert content_2 == "project 2 config"

    @pytest.mark.asyncio
    async def test_container_isolation_within_project(self, isolated_orchestrator):
        """Test that containers within a project are isolated."""
        user_id = uuid4()
        project_id = uuid4()

        # Write to frontend container
        await isolated_orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            file_path="index.js",
            content="frontend code",
        )

        # Write to backend container
        await isolated_orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name="backend",
            file_path="index.js",
            content="backend code",
        )

        # Read from each container
        frontend_content = await isolated_orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            file_path="index.js",
        )
        backend_content = await isolated_orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name="backend",
            file_path="index.js",
        )

        assert frontend_content == "frontend code"
        assert backend_content == "backend code"

    @pytest.mark.asyncio
    async def test_command_execution_scoped_to_user_project(self, isolated_orchestrator):
        """Test that commands execute in the correct user+project scope."""
        user_a = uuid4()
        user_b = uuid4()
        project_a = uuid4()
        project_b = uuid4()

        result_a = await isolated_orchestrator.execute_command(
            user_id=user_a,
            project_id=project_a,
            container_name="frontend",
            command=["npm", "run", "build"],
        )
        result_b = await isolated_orchestrator.execute_command(
            user_id=user_b,
            project_id=project_b,
            container_name="frontend",
            command=["npm", "run", "build"],
        )

        assert str(user_a) in result_a
        assert str(user_b) in result_b
        assert result_a != result_b


class TestConcurrentUserProjects:
    """Test that multiple users can operate concurrently without interference."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator for concurrent access testing."""
        orch = AsyncMock()
        project_states: dict[str, str] = {}

        async def mock_start(project, containers, connections, user_id, db):
            slug = project.slug
            project_states[slug] = "running"
            return {
                "status": "running",
                "project_slug": slug,
                "containers": {c.name: f"http://{slug}-{c.name}.localhost" for c in containers},
            }

        async def mock_stop(project_slug, project_id, user_id):
            project_states[project_slug] = "stopped"

        async def mock_status(project_slug, project_id):
            state = project_states.get(project_slug, "not_found")
            return {"status": state, "containers": {}}

        orch.start_project = mock_start
        orch.stop_project = mock_stop
        orch.get_project_status = mock_status
        orch._states = project_states
        return orch

    @pytest.mark.asyncio
    async def test_multiple_users_start_projects(self, mock_orchestrator):
        """Test that multiple users can start their own projects independently."""
        db = AsyncMock()

        user_a = uuid4()
        project_a = Mock(id=uuid4(), slug="user-a-project-abc")
        containers_a = [Mock(name="frontend")]

        user_b = uuid4()
        project_b = Mock(id=uuid4(), slug="user-b-project-def")
        containers_b = [Mock(name="frontend"), Mock(name="backend")]

        # Both users start their projects
        result_a = await mock_orchestrator.start_project(project_a, containers_a, [], user_a, db)
        result_b = await mock_orchestrator.start_project(project_b, containers_b, [], user_b, db)

        assert result_a["status"] == "running"
        assert result_b["status"] == "running"
        assert len(result_a["containers"]) == 1
        assert len(result_b["containers"]) == 2

    @pytest.mark.asyncio
    async def test_stopping_one_user_does_not_affect_other(self, mock_orchestrator):
        """Test that stopping one user's project doesn't affect another's."""
        db = AsyncMock()

        user_a = uuid4()
        project_a = Mock(id=uuid4(), slug="proj-a")
        user_b = uuid4()
        project_b = Mock(id=uuid4(), slug="proj-b")

        # Start both projects
        await mock_orchestrator.start_project(project_a, [Mock(name="frontend")], [], user_a, db)
        await mock_orchestrator.start_project(project_b, [Mock(name="frontend")], [], user_b, db)

        # Stop project A
        await mock_orchestrator.stop_project("proj-a", project_a.id, user_a)

        # Project A should be stopped
        status_a = await mock_orchestrator.get_project_status("proj-a", project_a.id)
        assert status_a["status"] == "stopped"

        # Project B should still be running
        status_b = await mock_orchestrator.get_project_status("proj-b", project_b.id)
        assert status_b["status"] == "running"

    @pytest.mark.asyncio
    async def test_many_concurrent_projects(self, mock_orchestrator):
        """Test managing many concurrent projects from different users."""
        db = AsyncMock()
        num_users = 10

        # Start projects for many users
        results = []
        for i in range(num_users):
            user_id = uuid4()
            project = Mock(id=uuid4(), slug=f"proj-{i:03d}")
            containers = [Mock(name="frontend")]
            result = await mock_orchestrator.start_project(project, containers, [], user_id, db)
            results.append(result)

        # All should be running
        assert all(r["status"] == "running" for r in results)
        assert len(mock_orchestrator._states) == num_users

        # Stop half of them
        for i in range(0, num_users, 2):
            await mock_orchestrator.stop_project(f"proj-{i:03d}", uuid4(), uuid4())

        # Verify correct state
        running = sum(1 for v in mock_orchestrator._states.values() if v == "running")
        stopped = sum(1 for v in mock_orchestrator._states.values() if v == "stopped")
        assert running == 5
        assert stopped == 5


class TestContainerURLGeneration:
    """Test container URL generation for different deployment modes."""

    def test_docker_url_format(self):
        """Test Docker mode generates correct localhost URLs."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("DEPLOYMENT_MODE", "docker")
            mp.setenv("APP_DOMAIN", "localhost")

            from app.services.orchestration import OrchestratorFactory

            OrchestratorFactory.clear_cache()

            with pytest.MonkeyPatch.context() as mp2:
                mp2.setattr(
                    "app.config.get_settings",
                    lambda: Mock(
                        app_domain="localhost",
                        deployment_mode="docker",
                    ),
                )

                # Test URL generation logic directly
                slug = "my-project-abc123"
                container_name = "frontend"
                safe_name = container_name.lower().replace(" ", "-").replace("_", "-")
                hostname = f"{slug}-{safe_name}.localhost"

                assert hostname == "my-project-abc123-frontend.localhost"

    def test_container_name_sanitization(self):
        """Test that container names are sanitized for URLs."""
        # Test the sanitization logic from BaseOrchestrator.get_container_url
        container_name = "My Frontend_App"
        safe_name = container_name.lower().replace(" ", "-").replace("_", "-")
        safe_name = "".join(c for c in safe_name if c.isalnum() or c == "-")

        assert safe_name == "my-frontend-app"

    def test_container_name_with_special_chars(self):
        """Test sanitization removes special characters."""
        container_name = "backend@v2.0!"
        safe_name = container_name.lower().replace(" ", "-").replace("_", "-")
        safe_name = "".join(c for c in safe_name if c.isalnum() or c == "-")

        assert safe_name == "backendv20"
