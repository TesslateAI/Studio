"""
Test configuration and fixtures for pytest.

This file provides comprehensive fixtures for testing the agent system.
Fixtures include: database sessions, mock users/projects, tool registries,
model adapters, and agent instances.
"""

import sys
import os
from pathlib import Path
import pytest
import asyncio
from uuid import uuid4
from unittest.mock import Mock, AsyncMock, MagicMock

# Add the orchestrator directory to sys.path
orchestrator_dir = Path(__file__).parent.parent
sys.path.insert(0, str(orchestrator_dir))


def pytest_configure(config):
    """
    Pytest hook called before test collection.
    Sets up test environment variables and registers custom markers.
    """
    # CRITICAL: Set test environment variables BEFORE any app imports
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://tesslate_user:dev_password_change_me@localhost:5432/tesslate_dev"
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
        "project_context": {
            "project_name": mock_project.name,
            "project_slug": mock_project.slug
        }
    }


@pytest.fixture
def mock_tool_registry():
    """Create a mock tool registry for testing."""
    from app.agent.tools.registry import ToolRegistry, Tool, ToolCategory

    registry = ToolRegistry()

    async def mock_tool_executor(params, context):
        return {
            "message": "Mock tool executed",
            "params": params
        }

    registry.register(Tool(
        name="mock_tool",
        description="A mock tool for testing",
        parameters={
            "type": "object",
            "properties": {
                "test_param": {"type": "string", "description": "A test parameter"}
            },
            "required": ["test_param"]
        },
        executor=mock_tool_executor,
        category=ToolCategory.FILE_OPS
    ))

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
"""
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
        full_path.write_text(content, encoding='utf-8')

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
"""
    }


@pytest.fixture
def mock_k8s_manager():
    """Create a mock Kubernetes manager for testing."""
    manager = AsyncMock()
    manager.read_file_from_pod = AsyncMock(return_value="File content")
    manager.write_file_to_pod = AsyncMock(return_value=True)
    manager.execute_command_in_pod = AsyncMock(return_value={
        "stdout": "Command output",
        "stderr": "",
        "exit_code": 0
    })
    return manager
