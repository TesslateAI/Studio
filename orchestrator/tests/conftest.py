"""
Test configuration and fixtures for pytest.

This file provides comprehensive fixtures for testing the agent system.
Fixtures include: database sessions, mock users/projects, tool registries,
model adapters, agent instances, container backends, and timing utilities.

Test Markers:
- @pytest.mark.mocked: Fully mocked, no containers required
- @pytest.mark.docker: Requires Docker daemon
- @pytest.mark.minikube: Requires minikube cluster
- @pytest.mark.llm: Uses real LLM (Llama-4-Maverick via LiteLLM)
- @pytest.mark.deterministic: Determinism verification tests
- @pytest.mark.oracle: Golden input/output tests
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

# Add the orchestrator directory to sys.path
orchestrator_dir = Path(__file__).parent.parent
sys.path.insert(0, str(orchestrator_dir))


def pytest_configure(config):
    """
    Pytest hook called before test collection.
    Sets up test environment variables and registers custom markers.
    """
    # CRITICAL: Set test environment variables BEFORE any app imports
    # Integration tests use port 5433 (docker-compose.test.yml)
    # Unit/mocked tests don't actually connect to DB
    os.environ["DATABASE_URL"] = (
        "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test"
    )
    os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
    os.environ["DEPLOYMENT_MODE"] = "docker"
    os.environ["LITELLM_API_BASE"] = "http://localhost:4000/v1"
    os.environ["LITELLM_MASTER_KEY"] = "test-master-key"

    # Import and clear settings cache after env vars are set
    from app.config import get_settings

    get_settings.cache_clear()

    # Register custom markers
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "e2e: mark test as an end-to-end test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "docker: mark test as requiring Docker")
    config.addinivalue_line("markers", "kubernetes: mark test as requiring Kubernetes")


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session (needed for async tests)."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_user():
    """Create a mock user for testing."""
    user = Mock()
    user.id = uuid4()
    user.username = "testuser"
    user.email = "test@example.com"
    user.litellm_api_key = "test-litellm-key"
    user.is_admin = False
    return user


@pytest.fixture
def mock_project():
    """Create a mock project for testing."""
    project = Mock()
    project.id = uuid4()
    project.name = "Test Project"
    project.slug = "test-project-abc123"
    project.description = "A test project"
    return project


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


@pytest.fixture
def test_context(mock_user, mock_project, mock_db):
    """Create a complete test context for tool execution."""
    return {
        "user": mock_user,
        "user_id": mock_user.id,
        "project_id": mock_project.id,
        "db": mock_db,
        "project_context": {"project_name": mock_project.name, "project_slug": mock_project.slug},
    }


@pytest.fixture
def mock_tool_registry():
    """Create a mock tool registry for testing."""
    from app.agent.tools.registry import Tool, ToolCategory, ToolRegistry

    registry = ToolRegistry()

    async def mock_tool_executor(params, context):
        return {"message": "Mock tool executed", "params": params}

    registry.register(
        Tool(
            name="mock_tool",
            description="A mock tool for testing",
            parameters={
                "type": "object",
                "properties": {"test_param": {"type": "string", "description": "A test parameter"}},
                "required": ["test_param"],
            },
            executor=mock_tool_executor,
            category=ToolCategory.FILE_OPS,
        )
    )

    return registry


@pytest.fixture
def mock_model_adapter():
    """Create a mock model adapter factory for testing."""
    from app.agent.models import ModelAdapter

    class MockModelAdapter(ModelAdapter):
        def __init__(self, responses=None):
            self.responses = responses or ["Test response"]
            self.call_count = 0

        async def chat(self, messages, **kwargs):
            """Yield mock response chunks."""
            response = self.responses[min(self.call_count, len(self.responses) - 1)]
            self.call_count += 1
            for char in response:
                yield char

        def get_model_name(self):
            return "mock-model"

    return MockModelAdapter


@pytest.fixture
def sample_project_files():
    """Sample project files for testing."""
    return {
        "package.json": """{
  "name": "test-app",
  "version": "1.0.0",
  "dependencies": {
    "react": "^18.2.0"
  }
}""",
        "src/App.jsx": """import React from 'react';

function App() {
  return (
    <div className="App">
      <h1>Hello World</h1>
    </div>
  );
}

export default App;
""",
        "src/components/Button.jsx": """import React from 'react';

export default function Button({ children, onClick }) {
  return (
    <button
      className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded"
      onClick={onClick}
    >
      {children}
    </button>
  );
}
""",
    }


@pytest.fixture
def temp_project_dir(tmp_path, mock_user, mock_project, sample_project_files):
    """
    Create a temporary project directory with sample files.

    Structure: users/{user_id}/{project_id}/...
    """
    project_dir = tmp_path / "users" / str(mock_user.id) / str(mock_project.id)
    project_dir.mkdir(parents=True, exist_ok=True)

    for file_path, content in sample_project_files.items():
        full_path = project_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    return project_dir


@pytest.fixture
def sample_tool_calls():
    """Sample tool calls for parser testing."""
    return {
        "xml_format": """
THOUGHT: I need to read the App.jsx file to understand its current structure.

<tool_call>
<tool_name>read_file</tool_name>
<parameters>
{"file_path": "src/App.jsx"}
</parameters>
</tool_call>
""",
        "multiple_calls": """
THOUGHT: I'll create two new components.

<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "src/Header.jsx", "content": "import React from 'react';\\nexport default function Header() { return <header>Header</header>; }"}
</parameters>
</tool_call>

<tool_call>
<tool_name>write_file</tool_name>
<parameters>
{"file_path": "src/Footer.jsx", "content": "import React from 'react';\\nexport default function Footer() { return <footer>Footer</footer>; }"}
</parameters>
</tool_call>
""",
        "completion_signal": """
THOUGHT: The task is now complete.

TASK_COMPLETE
""",
        "with_thought": """
THOUGHT: First, I should check what files exist in the project.

<tool_call>
<tool_name>bash_exec</tool_name>
<parameters>
{"command": "ls -la src/"}
</parameters>
</tool_call>
""",
    }


@pytest.fixture
def mock_k8s_client():
    """Mock KubernetesClient for v2 tests."""
    client = AsyncMock()
    client.create_namespace_if_not_exists = AsyncMock()
    client.namespace_exists = AsyncMock(return_value=True)
    client.delete_namespace = AsyncMock()
    client.apply_network_policy = AsyncMock()
    client.create_pvc = AsyncMock()
    client.create_deployment = AsyncMock()
    client.create_service = AsyncMock()
    client.create_ingress = AsyncMock()
    client.delete_deployment = AsyncMock()
    client.delete_service = AsyncMock()
    client.delete_ingress = AsyncMock()
    client.wait_for_deployment_ready = AsyncMock()
    client.get_file_manager_pod = AsyncMock(return_value="file-manager-abc123")
    client.copy_wildcard_tls_secret = AsyncMock()
    client.is_pod_ready = Mock(return_value=True)
    client.get_project_namespace = Mock(side_effect=lambda pid: f"proj-{pid}")

    # Underlying K8s APIs (used by orchestrator for direct calls)
    client.core_v1 = Mock()
    client.core_v1.delete_namespace = Mock()
    client.core_v1.read_namespace = Mock()
    client.core_v1.list_namespaced_pod = Mock()
    client.apps_v1 = Mock()
    client.apps_v1.read_namespaced_deployment = Mock()
    client._exec_in_pod = Mock(return_value="")
    return client


@pytest.fixture
def mock_fileops_client():
    """Mock FileOpsClient (async context manager)."""
    client = AsyncMock()
    client.read_file_text = AsyncMock(return_value="file content")
    client.write_file_text = AsyncMock()
    client.read_file = AsyncMock(return_value=b"file content")
    client.write_file = AsyncMock()
    client.delete_path = AsyncMock()
    client.list_dir = AsyncMock(return_value=[])
    client.mkdir_all = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.fixture
def mock_compute_manager():
    """Mock ComputeManager for v2 tests."""
    cm = AsyncMock()
    cm.run_command = AsyncMock(return_value=("output", 0, "t1-abc-xyz"))
    cm.start_environment = AsyncMock(return_value={"frontend": "https://proj.example.com"})
    cm.stop_environment = AsyncMock()
    cm.reap_orphaned_pods = AsyncMock(return_value=0)
    return cm


@pytest.fixture
def mock_snapshot_manager():
    """Mock SnapshotManager for hibernation tests."""
    sm = AsyncMock()
    sm.create_snapshot = AsyncMock(
        return_value=(Mock(id=uuid4(), snapshot_name="snap-abc123"), None)
    )
    sm.wait_for_snapshot_ready = AsyncMock(return_value=(True, None))
    sm.has_existing_snapshot = AsyncMock(return_value=True)
    sm.get_latest_ready_snapshot = AsyncMock(return_value=None)
    sm.get_latest_ready_snapshots_by_pvc = AsyncMock(return_value={})
    sm.restore_from_snapshot = AsyncMock(return_value=(True, None))
    sm.soft_delete_project_snapshots = AsyncMock(return_value=0)
    return sm


@pytest.fixture
def mock_project_with_volume(mock_project):
    """Mock project with v2 volume fields."""
    mock_project.volume_id = "vol-test123"
    mock_project.cache_node = "node-1"
    mock_project.compute_tier = "none"
    mock_project.environment_status = "hibernated"
    mock_project.hibernated_at = None
    mock_project.last_activity = None
    mock_project.latest_snapshot_id = None
    mock_project.owner_id = mock_project.id  # Set to a UUID
    return mock_project


# ============================================================================
# Container Backend Fixtures
# ============================================================================


class MockContainerBackend:
    """Mock container backend for fully mocked tests."""

    def __init__(self):
        self.files: dict[str, str] = {}
        self.commands_executed: list[str] = []

    async def read_file(self, path: str) -> str:
        if path in self.files:
            return self.files[path]
        raise FileNotFoundError(f"File not found: {path}")

    async def write_file(self, path: str, content: str) -> bool:
        self.files[path] = content
        return True

    async def execute_command(self, command: str, timeout: int = 30) -> dict[str, Any]:
        self.commands_executed.append(command)
        return {"stdout": "", "stderr": "", "exit_code": 0}


class DockerContainerBackend:
    """Docker container backend for Docker integration tests."""

    def __init__(self):
        import docker

        self.client = docker.from_env()

    async def read_file(self, container_name: str, path: str) -> str:
        container = self.client.containers.get(container_name)
        exit_code, output = container.exec_run(f"cat {path}")
        if exit_code != 0:
            raise FileNotFoundError(f"File not found: {path}")
        return output.decode("utf-8")

    async def write_file(self, container_name: str, path: str, content: str) -> bool:
        container = self.client.containers.get(container_name)
        # Use base64 to safely transfer content
        import base64

        encoded = base64.b64encode(content.encode()).decode()
        container.exec_run(f"sh -c 'echo {encoded} | base64 -d > {path}'")
        return True

    async def execute_command(
        self, container_name: str, command: str, timeout: int = 30
    ) -> dict[str, Any]:
        container = self.client.containers.get(container_name)
        exit_code, output = container.exec_run(command)
        return {
            "stdout": output.decode("utf-8"),
            "stderr": "",
            "exit_code": exit_code,
        }


@pytest.fixture
def container_backend(request):
    """
    Returns appropriate container backend based on test markers.

    Usage:
        @pytest.mark.mocked
        def test_something(container_backend):
            # Uses MockContainerBackend

        @pytest.mark.docker
        def test_docker_something(container_backend):
            # Uses DockerContainerBackend
    """
    markers = [m.name for m in request.node.iter_markers()]

    if "mocked" in markers:
        return MockContainerBackend()
    elif "docker" in markers:
        return DockerContainerBackend()
    else:
        # Default to mocked for safety
        return MockContainerBackend()


# ============================================================================
# Permission Auto-Approval Fixtures
# ============================================================================


@pytest.fixture
def auto_approve_permissions(monkeypatch):
    """
    Automatically approve all tool permissions in tests.

    This fixture patches the approval manager to always return approved.
    Use this when you don't want tests to block on permission prompts.
    """

    async def mock_check_approval(*args, **kwargs):
        return {"approved": True, "auto_approved": True}

    # Patch at the module level where it's used
    monkeypatch.setattr(
        "app.agent.tools.registry.check_tool_approval",
        mock_check_approval,
        raising=False,
    )
    return True


# ============================================================================
# Real LLM Fixtures (for @pytest.mark.llm tests)
# ============================================================================


@pytest.fixture
async def real_model_adapter(mock_user, mock_db):
    """
    Real LLM adapter using Llama-4-Maverick via LiteLLM.

    Use this fixture for tests that need actual LLM reasoning.
    Mark tests with @pytest.mark.llm to indicate they use real LLM.
    """
    from app.agent.models import create_model_adapter

    adapter = await create_model_adapter(
        model_name="Llama-4-Maverick-17B-128E-Instruct-FP8",
        user_id=mock_user.id,
        db=mock_db,
    )
    return adapter


@pytest.fixture
def mock_model_with_responses():
    """
    Factory fixture to create mock models with specific response sequences.

    Usage:
        def test_something(mock_model_with_responses):
            model = mock_model_with_responses([
                '{"tool_name": "read_file", "parameters": {"file_path": "test.js"}}',
                'TASK_COMPLETE'
            ])
    """
    from app.agent.models import ModelAdapter

    def create_model(responses: list[str]):
        class ConfiguredMockModel(ModelAdapter):
            def __init__(self):
                self.responses = responses
                self.call_count = 0
                self.messages_received: list[list[dict]] = []

            async def chat(self, messages, **kwargs):
                self.messages_received.append(messages)
                response = self.responses[min(self.call_count, len(self.responses) - 1)]
                self.call_count += 1
                for char in response:
                    yield char

            def get_model_name(self):
                return "mock-model-with-responses"

        return ConfiguredMockModel()

    return create_model


# ============================================================================
# Determinism Fixtures
# ============================================================================


@pytest.fixture
def frozen_time():
    """
    Freeze time for deterministic timestamp testing.

    Usage:
        def test_something(frozen_time):
            with frozen_time("2025-01-01 12:00:00"):
                # All datetime.now() calls return frozen time
    """
    from freezegun import freeze_time

    return freeze_time


@pytest.fixture
def deterministic_uuid(monkeypatch):
    """
    Provide deterministic UUIDs for testing.

    UUIDs will be generated as:
    00000000-0000-0000-0000-000000000001
    00000000-0000-0000-0000-000000000002
    etc.
    """
    counter = [0]

    def predictable_uuid4():
        counter[0] += 1
        return uuid.UUID(f"00000000-0000-0000-0000-{counter[0]:012d}")

    monkeypatch.setattr("uuid.uuid4", predictable_uuid4)
    return counter


@pytest.fixture
def seeded_random(monkeypatch):
    """Seed random for deterministic behavior."""
    import random

    random.seed(42)
    return 42


# ============================================================================
# Mock Orchestrator Fixtures
# ============================================================================


@pytest.fixture
def mock_docker_orchestrator():
    """
    Mock Docker orchestrator for file/shell operations.

    Provides in-memory file storage and command execution tracking.
    """
    orchestrator = AsyncMock()
    files: dict[str, str] = {}
    commands: list[str] = []

    async def mock_read_file(user_id, project_id, file_path, *args, **kwargs):
        key = f"{project_id}/{file_path}"
        if key in files:
            return files[key]
        raise FileNotFoundError(f"File not found: {file_path}")

    async def mock_write_file(user_id, project_id, file_path, content, *args, **kwargs):
        key = f"{project_id}/{file_path}"
        files[key] = content
        return True

    async def mock_execute_command(user_id, project_id, command, *args, **kwargs):
        commands.append(command)
        return {"stdout": "", "stderr": "", "exit_code": 0}

    orchestrator.read_file = mock_read_file
    orchestrator.write_file = mock_write_file
    orchestrator.execute_command = mock_execute_command
    orchestrator._files = files  # Expose for assertions
    orchestrator._commands = commands  # Expose for assertions

    return orchestrator


@pytest.fixture
def mock_pty_session():
    """
    Mock PTY session with controllable output buffer.

    Allows tests to simulate PTY session behavior without real PTY.
    """
    session = Mock()
    session.session_id = str(uuid4())
    session.output_buffer = b""
    session.read_offset = 0
    session.is_eof = False

    def append_output(data: bytes):
        session.output_buffer += data

    def read_new_output():
        new_data = session.output_buffer[session.read_offset :]
        session.read_offset = len(session.output_buffer)
        return new_data

    session.append_output = append_output
    session.read_new_output = read_new_output

    return session


# ============================================================================
# Tmux Session Fixtures
# ============================================================================


@pytest.fixture
def mock_tmux_session_manager():
    """Mock TmuxSessionManager for testing tmux operations."""
    manager = AsyncMock()

    manager.generate_startup_command = Mock(
        return_value="tmux new-session -d -s main -x 120 -y 30 'npm run dev'"
    )
    manager.create_session = AsyncMock(
        return_value={
            "session_id": "main",
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    manager.is_session_active = AsyncMock(return_value=True)
    manager.attach_to_session = AsyncMock(return_value="main:0.0")
    manager.send_keys = AsyncMock(return_value=True)
    manager.capture_pane = AsyncMock(return_value="$ npm run dev\nReady on http://localhost:3000")
    manager.close_window = AsyncMock(return_value=True)

    return manager


# ============================================================================
# Tool Registry Fixtures (Enhanced)
# ============================================================================


@pytest.fixture
def full_tool_registry():
    """
    Create a full tool registry with all real tools registered.

    Use this for integration tests that need actual tool implementations.
    """
    from app.agent.tools.registry import get_global_registry

    return get_global_registry()


@pytest.fixture
def file_ops_registry():
    """Tool registry with only file operation tools."""
    from app.agent.tools.registry import create_scoped_tool_registry

    return create_scoped_tool_registry(
        tool_names=["read_file", "write_file", "patch_file", "multi_edit"]
    )


@pytest.fixture
def shell_ops_registry():
    """Tool registry with only shell operation tools."""
    from app.agent.tools.registry import create_scoped_tool_registry

    return create_scoped_tool_registry(
        tool_names=["bash_exec", "shell_open", "shell_exec", "shell_close"]
    )
