# Test Suite Documentation

Comprehensive test suite for the Tesslate Studio orchestrator, with a focus on the AI agent implementation.

## Directory Structure

```
tests/
├── conftest.py                     # Shared fixtures and test configuration
├── README.md                       # This file
│
├── agent/                          # Agent system tests
│   ├── unit/                       # Unit tests for agent components
│   │   ├── test_parser.py          # AgentResponseParser tests
│   │   ├── test_tool_registry.py   # ToolRegistry tests
│   │   └── test_output_formatter.py # Output formatting utilities
│   │
│   ├── tools/                      # Tool-specific tests
│   │   ├── test_file_ops.py        # File operation tools (read, write, patch, multi_edit)
│   │   ├── test_diff_editing.py    # Diff/patch editing functionality
│   │   └── test_patch_file_tool.py # Patch file tool integration
│   │
│   ├── integration/                # Integration tests
│   │   └── test_iterative_agent.py # IterativeAgent workflow tests
│   │
│   └── e2e/                        # End-to-end tests
│       └── test_agent_workflows.py # Complete agent workflows
│
├── shell/                          # Shell session tests
│   ├── test_pty_broker.py          # PTY broker tests
│   ├── test_shell_api.py           # Shell API tests
│   ├── test_shell_session_e2e.py   # Shell session E2E tests
│   └── test_shell_simple.py        # Simple shell tests
│
├── containers/                     # Container management tests
│   ├── test_container_system.py    # Container system tests
│   ├── test_multi_user_containers.py # Multi-user container tests
│   └── test_file_extraction.py     # File extraction tests
│
└── legacy/                         # Legacy/deprecated tests
    ├── test_agent_api.py           # Old agent API tests
    ├── test_agent_modes.py         # Old agent mode tests
    ├── test_comprehensive_agent_modes.py # Old comprehensive tests
    └── test_websocket_agent.py     # Old WebSocket tests
```

## Test Categories

### Unit Tests (`@pytest.mark.unit`)

Tests for individual components in isolation:

- **Parser Tests** (`test_parser.py`): Tool call parsing, completion detection, thought extraction
- **Tool Registry Tests** (`test_tool_registry.py`): Tool registration, lookup, execution, scoped registries
- **Output Formatter Tests** (`test_output_formatter.py`): Success/error output formatting, utility functions

**Run unit tests:**
```bash
pytest -m unit
```

### Integration Tests (`@pytest.mark.integration`)

Tests for component interactions:

- **IterativeAgent Tests** (`test_iterative_agent.py`): Multi-iteration workflows, tool execution, error handling
- **File Operations Tests** (`test_file_ops.py`): File read/write/patch workflows in Docker and Kubernetes modes

**Run integration tests:**
```bash
pytest -m integration
```

### End-to-End Tests (`@pytest.mark.e2e`)

Tests for complete user workflows:

- **Agent Workflows** (`test_agent_workflows.py`): Real-world scenarios like creating components, modifying files, error recovery

**Run E2E tests:**
```bash
pytest -m e2e
```

## Test Fixtures

### Core Fixtures (from `conftest.py`)

**Mock Objects:**
- `mock_user` - Mock user with ID, username, email, API keys
- `mock_project` - Mock project with ID, name, slug
- `mock_db` - AsyncMock database session
- `test_context` - Complete test context for tool execution

**Test Data:**
- `sample_project_files` - Sample React project files (package.json, App.jsx, Button.jsx)
- `sample_tool_calls` - Sample tool calls in various formats (XML, multiple calls, completion signals)
- `temp_project_dir` - Temporary project directory with sample files

**Mocks:**
- `mock_tool_registry` - Mock tool registry with a test tool
- `mock_model_adapter` - Factory for creating mock model adapters
- `mock_k8s_manager` - Mock Kubernetes manager for file operations

### Custom Fixtures

Tests can define their own fixtures:

```python
@pytest.fixture
def custom_tool_registry():
    """Create a custom tool registry for specific tests."""
    registry = ToolRegistry()
    # Register tools...
    return registry
```

## Running Tests

### All Tests
```bash
pytest
```

### Specific Test Category
```bash
pytest -m unit           # Unit tests only
pytest -m integration    # Integration tests only
pytest -m e2e            # End-to-end tests only
pytest -m slow           # Slow-running tests
```

### Specific Test File
```bash
pytest tests/agent/unit/test_parser.py
```

### Specific Test Function
```bash
pytest tests/agent/unit/test_parser.py::TestAgentResponseParser::test_parse_xml_single_tool_call
```

### With Coverage
```bash
pytest --cov=app.agent --cov-report=html
```

### Verbose Output
```bash
pytest -v
pytest -vv  # Extra verbose
```

### Run Tests in Parallel
```bash
pytest -n auto  # Uses pytest-xdist
```

## Test Markers

Custom markers for organizing and filtering tests:

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.e2e` - End-to-end tests
- `@pytest.mark.slow` - Slow-running tests
- `@pytest.mark.docker` - Requires Docker
- `@pytest.mark.kubernetes` - Requires Kubernetes

**Usage:**
```python
@pytest.mark.unit
def test_something():
    pass

@pytest.mark.integration
@pytest.mark.slow
async def test_complex_workflow():
    pass
```

## Writing New Tests

### Unit Test Template

```python
"""
Tests for <component_name>.

<Brief description>
"""

import pytest
from app.agent.<module> import <Component>


@pytest.mark.unit
class Test<ComponentName>:
    """Test suite for <ComponentName>."""

    @pytest.fixture
    def component(self):
        """Create component instance for testing."""
        return <Component>()

    def test_basic_functionality(self, component):
        """Test basic functionality."""
        result = component.method()
        assert result == expected_value

    @pytest.mark.asyncio
    async def test_async_method(self, component):
        """Test async method."""
        result = await component.async_method()
        assert result is not None
```

### Integration Test Template

```python
"""
Integration tests for <feature>.

<Description of integration scenarios>
"""

import pytest
from unittest.mock import AsyncMock


@pytest.mark.integration
class Test<Feature>Integration:
    """Integration tests for <Feature>."""

    @pytest.fixture
    def setup_environment(self):
        """Setup test environment."""
        # Setup code
        yield
        # Cleanup code

    @pytest.mark.asyncio
    async def test_integration_scenario(self, setup_environment, test_context):
        """Test complete integration scenario."""
        # Test code
        pass
```

### E2E Test Template

```python
"""
End-to-end tests for <workflow>.

<Description of user workflows>
"""

import pytest


@pytest.mark.e2e
@pytest.mark.slow
class Test<Workflow>E2E:
    """E2E tests for <Workflow>."""

    @pytest.mark.asyncio
    async def test_complete_workflow(self, test_context):
        """Test complete user workflow."""
        # Simulate real user interaction
        pass
```

## Best Practices

### 1. Use Descriptive Test Names
```python
# Good
def test_parse_xml_single_tool_call():
    pass

# Bad
def test_parse():
    pass
```

### 2. Arrange-Act-Assert Pattern
```python
def test_tool_execution():
    # Arrange
    tool = create_tool()
    params = {"key": "value"}

    # Act
    result = tool.execute(params)

    # Assert
    assert result["success"] is True
```

### 3. Use Fixtures for Common Setup
```python
@pytest.fixture
def configured_agent():
    """Create a fully configured agent."""
    return Agent(
        system_prompt="Test prompt",
        tools=create_tools(),
        model=create_model()
    )

def test_agent(configured_agent):
    # Use configured_agent
    pass
```

### 4. Test Edge Cases
```python
@pytest.mark.parametrize("invalid_input,expected_error", [
    ("", "Empty input"),
    (None, "None value"),
    ("invalid", "Invalid format"),
])
def test_invalid_inputs(invalid_input, expected_error):
    with pytest.raises(ValueError, match=expected_error):
        process(invalid_input)
```

### 5. Mock External Dependencies
```python
@pytest.mark.asyncio
async def test_with_mock_k8s(mock_k8s_manager, monkeypatch):
    """Test with mocked Kubernetes manager."""
    monkeypatch.setattr(
        "app.agent.tools.file_ops.read_write.get_k8s_manager",
        lambda: mock_k8s_manager
    )

    # Test code using mocked K8s
```

### 6. Use Async Tests Properly
```python
@pytest.mark.asyncio
async def test_async_function():
    """Test async function."""
    result = await async_function()
    assert result is not None
```

## Continuous Integration

Tests are automatically run on:
- Pull requests
- Pushes to main branch
- Scheduled nightly builds

**CI Configuration:**
```yaml
# .github/workflows/tests.yml
- name: Run unit tests
  run: pytest -m unit

- name: Run integration tests
  run: pytest -m integration

- name: Run E2E tests
  run: pytest -m e2e --maxfail=1
```

## Troubleshooting

### Common Issues

**Issue: `ImportError: No module named 'app'`**
- Solution: Ensure `conftest.py` is adding the orchestrator directory to `sys.path`

**Issue: Async tests not running**
- Solution: Install `pytest-asyncio`: `pip install pytest-asyncio`

**Issue: Tests hanging**
- Solution: Check for unclosed async resources, add timeouts

**Issue: Fixtures not found**
- Solution: Ensure `conftest.py` is in the correct location

### Debug Mode

Run tests with more verbose output:
```bash
pytest -vv --tb=short  # Short traceback
pytest -vv --tb=long   # Long traceback
pytest -vv --pdb       # Drop into debugger on failure
```

### Logging

Enable logging during tests:
```bash
pytest --log-cli-level=DEBUG
```

## Coverage

Generate coverage reports:

```bash
# HTML report
pytest --cov=app.agent --cov-report=html
open htmlcov/index.html

# Terminal report
pytest --cov=app.agent --cov-report=term

# XML report (for CI)
pytest --cov=app.agent --cov-report=xml
```

**Coverage Goals:**
- Unit tests: >90%
- Integration tests: >80%
- Overall: >85%

## Contributing

When adding new features:

1. Write tests first (TDD)
2. Ensure all existing tests pass
3. Add tests for new functionality
4. Update this README if adding new test categories
5. Run full test suite before submitting PR

**Pre-commit checklist:**
```bash
# Format code
black orchestrator/

# Run linter
flake8 orchestrator/

# Run tests
pytest

# Check coverage
pytest --cov=app.agent --cov-report=term
```

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest Async Documentation](https://pytest-asyncio.readthedocs.io/)
- [Unittest Mock Documentation](https://docs.python.org/3/library/unittest.mock.html)

## Maintenance

This test suite is maintained as part of the Tesslate Studio project.

**Last Updated:** 2025-01-15
**Test Count:** 100+ tests across unit, integration, and E2E categories
**Coverage:** 85%+ code coverage for agent system
