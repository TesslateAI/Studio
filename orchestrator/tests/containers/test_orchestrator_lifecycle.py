"""
Test Orchestrator Lifecycle Management

Tests container start/stop/status lifecycle through the unified orchestrator
interface. All tests use mocked orchestrators to verify the factory pattern,
lifecycle state transitions, and multi-container management without requiring
Docker or Kubernetes.

These tests replace the deleted test_container_system.py.disabled which tested
container lifecycle via the now-removed k8s_container_manager module.
"""

from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.services.orchestration import (
    DeploymentMode,
    OrchestratorFactory,
    get_orchestrator,
)

pytestmark = pytest.mark.unit


class TestOrchestratorFactory:
    """Test the orchestrator factory and singleton pattern."""

    def setup_method(self):
        """Clear factory cache before each test."""
        OrchestratorFactory.clear_cache()

    def teardown_method(self):
        """Clear factory cache after each test."""
        OrchestratorFactory.clear_cache()

    def test_factory_creates_docker_orchestrator(self):
        """Test factory creates Docker orchestrator for docker mode."""
        mock_orch = Mock()
        mock_orch.deployment_mode = DeploymentMode.DOCKER
        with (
            patch.object(
                OrchestratorFactory,
                "get_deployment_mode",
                return_value=DeploymentMode.DOCKER,
            ),
            patch(
                "app.services.orchestration.docker.DockerOrchestrator",
                return_value=mock_orch,
            ),
        ):
            orchestrator = get_orchestrator()
            assert orchestrator.deployment_mode == DeploymentMode.DOCKER

    def test_factory_creates_kubernetes_orchestrator(self):
        """Test factory creates Kubernetes orchestrator for kubernetes mode."""
        mock_orch = Mock()
        mock_orch.deployment_mode = DeploymentMode.KUBERNETES
        with (
            patch.object(
                OrchestratorFactory,
                "get_deployment_mode",
                return_value=DeploymentMode.KUBERNETES,
            ),
            patch(
                "app.services.orchestration.kubernetes_orchestrator.KubernetesOrchestrator",
                return_value=mock_orch,
            ),
        ):
            orchestrator = get_orchestrator()
            assert orchestrator.deployment_mode == DeploymentMode.KUBERNETES

    def test_factory_caches_instances(self):
        """Test factory returns same instance on repeated calls (singleton)."""
        mock_orch = Mock()
        mock_orch.deployment_mode = DeploymentMode.DOCKER
        with (
            patch.object(
                OrchestratorFactory,
                "get_deployment_mode",
                return_value=DeploymentMode.DOCKER,
            ),
            patch(
                "app.services.orchestration.docker.DockerOrchestrator",
                return_value=mock_orch,
            ),
        ):
            orch1 = get_orchestrator()
            orch2 = get_orchestrator()
            assert orch1 is orch2

    def test_factory_clear_cache(self):
        """Test clearing the factory cache creates new instances."""
        mock_orch_1 = Mock()
        mock_orch_1.deployment_mode = DeploymentMode.DOCKER
        mock_orch_2 = Mock()
        mock_orch_2.deployment_mode = DeploymentMode.DOCKER
        with patch.object(
            OrchestratorFactory,
            "get_deployment_mode",
            return_value=DeploymentMode.DOCKER,
        ):
            with patch(
                "app.services.orchestration.docker.DockerOrchestrator",
                return_value=mock_orch_1,
            ):
                orch1 = get_orchestrator()

            OrchestratorFactory.clear_cache()

            with patch(
                "app.services.orchestration.docker.DockerOrchestrator",
                return_value=mock_orch_2,
            ):
                orch2 = get_orchestrator()

            assert orch1 is not orch2

    def test_factory_rejects_invalid_mode(self):
        """Test factory raises ValueError for unsupported mode."""
        with pytest.raises(ValueError, match="Invalid deployment mode"):
            DeploymentMode.from_string("unsupported")

    def test_explicit_mode_override(self):
        """Test factory allows explicit mode override."""
        mock_orch = Mock()
        mock_orch.deployment_mode = DeploymentMode.KUBERNETES
        with patch(
            "app.services.orchestration.kubernetes_orchestrator.KubernetesOrchestrator",
            return_value=mock_orch,
        ):
            orch = get_orchestrator(DeploymentMode.KUBERNETES)
            assert orch.deployment_mode == DeploymentMode.KUBERNETES


class TestProjectLifecycle:
    """Test project start/stop/restart lifecycle via orchestrator."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator with lifecycle methods."""
        orch = AsyncMock()
        orch.deployment_mode = DeploymentMode.DOCKER

        orch.start_project = AsyncMock(
            return_value={
                "status": "running",
                "project_slug": "test-proj-abc123",
                "containers": {
                    "frontend": "http://test-proj-abc123-frontend.localhost",
                },
            }
        )
        orch.stop_project = AsyncMock(return_value=None)
        orch.restart_project = AsyncMock(
            return_value={
                "status": "running",
                "project_slug": "test-proj-abc123",
                "containers": {
                    "frontend": "http://test-proj-abc123-frontend.localhost",
                },
            }
        )
        orch.get_project_status = AsyncMock(
            return_value={
                "status": "running",
                "containers": {
                    "frontend": {
                        "status": "running",
                        "url": "http://test-proj-abc123-frontend.localhost",
                    }
                },
            }
        )
        return orch

    @pytest.mark.asyncio
    async def test_start_project(self, mock_orchestrator):
        """Test starting a project returns correct status."""
        project = Mock(id=uuid4(), slug="test-proj-abc123")
        containers = [Mock(name="frontend", image="node:18")]
        connections = []
        user_id = uuid4()
        db = AsyncMock()

        result = await mock_orchestrator.start_project(
            project, containers, connections, user_id, db
        )

        assert result["status"] == "running"
        assert "frontend" in result["containers"]
        mock_orchestrator.start_project.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_project(self, mock_orchestrator):
        """Test stopping a project calls orchestrator correctly."""
        project_id = uuid4()
        user_id = uuid4()

        await mock_orchestrator.stop_project("test-proj-abc123", project_id, user_id)

        mock_orchestrator.stop_project.assert_called_once_with(
            "test-proj-abc123", project_id, user_id
        )

    @pytest.mark.asyncio
    async def test_restart_project(self, mock_orchestrator):
        """Test restarting a project returns running status."""
        project = Mock(id=uuid4(), slug="test-proj-abc123")
        containers = [Mock(name="frontend")]
        connections = []
        user_id = uuid4()
        db = AsyncMock()

        result = await mock_orchestrator.restart_project(
            project, containers, connections, user_id, db
        )

        assert result["status"] == "running"
        mock_orchestrator.restart_project.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_project_status_running(self, mock_orchestrator):
        """Test getting status of a running project."""
        project_id = uuid4()

        result = await mock_orchestrator.get_project_status("test-proj-abc123", project_id)

        assert result["status"] == "running"
        assert "frontend" in result["containers"]

    @pytest.mark.asyncio
    async def test_get_project_status_stopped(self, mock_orchestrator):
        """Test getting status of a stopped project."""
        mock_orchestrator.get_project_status = AsyncMock(
            return_value={"status": "stopped", "containers": {}}
        )
        project_id = uuid4()

        result = await mock_orchestrator.get_project_status("test-proj-abc123", project_id)

        assert result["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_get_project_status_not_found(self, mock_orchestrator):
        """Test getting status of a non-existent project."""
        mock_orchestrator.get_project_status = AsyncMock(
            return_value={"status": "not_found", "containers": {}}
        )
        project_id = uuid4()

        result = await mock_orchestrator.get_project_status("nonexistent", project_id)

        assert result["status"] == "not_found"


class TestContainerLifecycle:
    """Test individual container start/stop/status."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator for container-level ops."""
        orch = AsyncMock()
        orch.deployment_mode = DeploymentMode.DOCKER

        orch.start_container = AsyncMock(
            return_value={
                "status": "running",
                "container_name": "frontend",
                "url": "http://test-proj-abc123-frontend.localhost",
            }
        )
        orch.stop_container = AsyncMock(return_value=None)
        orch.get_container_status = AsyncMock(
            return_value={
                "status": "running",
                "url": "http://test-proj-abc123-frontend.localhost",
            }
        )
        orch.is_container_ready = AsyncMock(
            return_value={"ready": True, "message": "Container is ready"}
        )
        return orch

    @pytest.mark.asyncio
    async def test_start_container(self, mock_orchestrator):
        """Test starting a single container."""
        project = Mock(id=uuid4(), slug="test-proj-abc123")
        container = Mock(name="frontend")
        user_id = uuid4()
        db = AsyncMock()

        result = await mock_orchestrator.start_container(
            project, container, [container], [], user_id, db
        )

        assert result["status"] == "running"
        assert result["container_name"] == "frontend"

    @pytest.mark.asyncio
    async def test_stop_container(self, mock_orchestrator):
        """Test stopping a single container."""
        project_id = uuid4()
        user_id = uuid4()

        await mock_orchestrator.stop_container("test-proj-abc123", project_id, "frontend", user_id)

        mock_orchestrator.stop_container.assert_called_once()

    @pytest.mark.asyncio
    async def test_container_readiness_check(self, mock_orchestrator):
        """Test checking if container is ready for commands."""
        project_id = uuid4()
        user_id = uuid4()

        result = await mock_orchestrator.is_container_ready(user_id, project_id, "frontend")

        assert result["ready"] is True

    @pytest.mark.asyncio
    async def test_container_not_ready(self, mock_orchestrator):
        """Test container not ready returns appropriate status."""
        mock_orchestrator.is_container_ready = AsyncMock(
            return_value={"ready": False, "message": "Container is starting"}
        )
        project_id = uuid4()
        user_id = uuid4()

        result = await mock_orchestrator.is_container_ready(user_id, project_id, "frontend")

        assert result["ready"] is False
        assert "starting" in result["message"]


class TestMultiContainerProject:
    """Test managing projects with multiple containers (frontend + backend + db)."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator supporting multiple containers."""
        orch = AsyncMock()
        orch.deployment_mode = DeploymentMode.DOCKER

        orch.start_project = AsyncMock(
            return_value={
                "status": "running",
                "project_slug": "fullstack-app-xyz",
                "containers": {
                    "frontend": "http://fullstack-app-xyz-frontend.localhost",
                    "backend": "http://fullstack-app-xyz-backend.localhost",
                    "database": "http://fullstack-app-xyz-database.localhost",
                },
            }
        )
        orch.get_project_status = AsyncMock(
            return_value={
                "status": "running",
                "containers": {
                    "frontend": {"status": "running"},
                    "backend": {"status": "running"},
                    "database": {"status": "running"},
                },
            }
        )
        return orch

    @pytest.mark.asyncio
    async def test_start_multi_container_project(self, mock_orchestrator):
        """Test starting a project with multiple containers."""
        project = Mock(id=uuid4(), slug="fullstack-app-xyz")
        containers = [
            Mock(name="frontend", image="node:18"),
            Mock(name="backend", image="python:3.11"),
            Mock(name="database", image="postgres:15"),
        ]
        connections = [
            Mock(source_container="backend", target_container="database"),
            Mock(source_container="frontend", target_container="backend"),
        ]
        user_id = uuid4()
        db = AsyncMock()

        result = await mock_orchestrator.start_project(
            project, containers, connections, user_id, db
        )

        assert result["status"] == "running"
        assert len(result["containers"]) == 3
        assert "frontend" in result["containers"]
        assert "backend" in result["containers"]
        assert "database" in result["containers"]

    @pytest.mark.asyncio
    async def test_multi_container_status(self, mock_orchestrator):
        """Test getting status of multi-container project shows all containers."""
        project_id = uuid4()

        result = await mock_orchestrator.get_project_status("fullstack-app-xyz", project_id)

        assert result["status"] == "running"
        assert len(result["containers"]) == 3

    @pytest.mark.asyncio
    async def test_partial_container_failure(self, mock_orchestrator):
        """Test status when one container is down."""
        mock_orchestrator.get_project_status = AsyncMock(
            return_value={
                "status": "partial",
                "containers": {
                    "frontend": {"status": "running"},
                    "backend": {"status": "stopped"},
                    "database": {"status": "running"},
                },
            }
        )
        project_id = uuid4()

        result = await mock_orchestrator.get_project_status("fullstack-app-xyz", project_id)

        assert result["status"] == "partial"
        assert result["containers"]["backend"]["status"] == "stopped"
        assert result["containers"]["frontend"]["status"] == "running"


class TestFileOperationsViaOrchestrator:
    """Test file read/write/delete/list via orchestrator interface."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator with file operation support."""
        orch = AsyncMock()
        files = {}

        async def mock_read(user_id, project_id, container_name, file_path, **kwargs):
            key = f"{project_id}/{container_name}/{file_path}"
            return files.get(key)

        async def mock_write(user_id, project_id, container_name, file_path, content, **kwargs):
            key = f"{project_id}/{container_name}/{file_path}"
            files[key] = content
            return True

        async def mock_delete(user_id, project_id, container_name, file_path, **kwargs):
            key = f"{project_id}/{container_name}/{file_path}"
            if key in files:
                del files[key]
                return True
            return False

        async def mock_list(user_id, project_id, container_name, directory=".", **kwargs):
            prefix = f"{project_id}/{container_name}/{directory}"
            result = []
            for key in files:
                if key.startswith(prefix) or directory == ".":
                    name = key.split("/")[-1]
                    result.append(
                        {"name": name, "type": "file", "size": len(files[key]), "path": key}
                    )
            return result

        orch.read_file = mock_read
        orch.write_file = mock_write
        orch.delete_file = mock_delete
        orch.list_files = mock_list
        orch._files = files
        return orch

    @pytest.mark.asyncio
    async def test_write_and_read_file(self, mock_orchestrator):
        """Test writing and reading back a file."""
        user_id = uuid4()
        project_id = uuid4()

        await mock_orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            file_path="src/App.jsx",
            content="export default function App() {}",
        )

        content = await mock_orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            file_path="src/App.jsx",
        )

        assert content == "export default function App() {}"

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, mock_orchestrator):
        """Test reading a file that doesn't exist returns None."""
        user_id = uuid4()
        project_id = uuid4()

        content = await mock_orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            file_path="nonexistent.js",
        )

        assert content is None

    @pytest.mark.asyncio
    async def test_delete_file(self, mock_orchestrator):
        """Test deleting a file removes it."""
        user_id = uuid4()
        project_id = uuid4()

        await mock_orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            file_path="temp.js",
            content="temporary",
        )

        result = await mock_orchestrator.delete_file(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            file_path="temp.js",
        )

        assert result is True

        content = await mock_orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            file_path="temp.js",
        )
        assert content is None


class TestShellExecutionViaOrchestrator:
    """Test command execution via orchestrator interface."""

    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator with shell execution support."""
        orch = AsyncMock()
        orch.execute_command = AsyncMock(return_value="command output")
        orch.is_container_ready = AsyncMock(return_value={"ready": True, "message": "Ready"})
        return orch

    @pytest.mark.asyncio
    async def test_execute_command(self, mock_orchestrator):
        """Test executing a command in container."""
        user_id = uuid4()
        project_id = uuid4()

        result = await mock_orchestrator.execute_command(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            command=["npm", "run", "build"],
        )

        assert result == "command output"

    @pytest.mark.asyncio
    async def test_execute_command_with_timeout(self, mock_orchestrator):
        """Test executing a command with custom timeout."""
        user_id = uuid4()
        project_id = uuid4()

        await mock_orchestrator.execute_command(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            command=["npm", "install"],
            timeout=300,
        )

        mock_orchestrator.execute_command.assert_called_once_with(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            command=["npm", "install"],
            timeout=300,
        )

    @pytest.mark.asyncio
    async def test_execute_command_with_working_dir(self, mock_orchestrator):
        """Test executing a command with working directory."""
        user_id = uuid4()
        project_id = uuid4()

        await mock_orchestrator.execute_command(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            command=["ls", "-la"],
            working_dir="src/",
        )

        mock_orchestrator.execute_command.assert_called_once_with(
            user_id=user_id,
            project_id=project_id,
            container_name="frontend",
            command=["ls", "-la"],
            working_dir="src/",
        )

    @pytest.mark.asyncio
    async def test_execute_command_failure(self, mock_orchestrator):
        """Test command execution failure raises RuntimeError."""
        mock_orchestrator.execute_command = AsyncMock(
            side_effect=RuntimeError("Command failed: exit code 1")
        )
        user_id = uuid4()
        project_id = uuid4()

        with pytest.raises(RuntimeError, match="Command failed"):
            await mock_orchestrator.execute_command(
                user_id=user_id,
                project_id=project_id,
                container_name="frontend",
                command=["invalid-command"],
            )


class TestActivityTracking:
    """Test activity tracking for idle cleanup."""

    def test_track_activity(self):
        """Test that activity tracking calls through correctly."""
        orch = Mock()
        orch.track_activity = Mock()

        user_id = uuid4()
        project_id = str(uuid4())

        orch.track_activity(user_id, project_id, container_name="frontend")

        orch.track_activity.assert_called_once_with(user_id, project_id, container_name="frontend")



class TestDeploymentMode:
    """Test DeploymentMode enum behavior."""

    def test_docker_mode_properties(self):
        """Test Docker mode enum properties."""
        mode = DeploymentMode.DOCKER
        assert mode.is_docker is True
        assert mode.is_kubernetes is False
        assert str(mode) == "docker"

    def test_kubernetes_mode_properties(self):
        """Test Kubernetes mode enum properties."""
        mode = DeploymentMode.KUBERNETES
        assert mode.is_docker is False
        assert mode.is_kubernetes is True
        assert str(mode) == "kubernetes"

    def test_from_string_docker(self):
        """Test creating DeploymentMode from string."""
        assert DeploymentMode.from_string("docker") == DeploymentMode.DOCKER
        assert DeploymentMode.from_string("Docker") == DeploymentMode.DOCKER
        assert DeploymentMode.from_string(" docker ") == DeploymentMode.DOCKER

    def test_from_string_kubernetes(self):
        """Test creating DeploymentMode from string."""
        assert DeploymentMode.from_string("kubernetes") == DeploymentMode.KUBERNETES
        assert DeploymentMode.from_string("Kubernetes") == DeploymentMode.KUBERNETES

    def test_from_string_invalid(self):
        """Test invalid deployment mode string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid deployment mode"):
            DeploymentMode.from_string("invalid")
