"""
Agent Oracle Tests

Deterministic tests that verify the agent correctly processes scripted LLM responses.
Uses OracleModelAdapter to replay exact model outputs and asserts tool call sequences,
file changes, and final responses.

Run: pytest -m oracle_agent -v
"""

import json
import pathlib

import pytest

from .oracle_model_adapter import OracleModelAdapter

# Mark all tests in this module
pytestmark = pytest.mark.oracle_agent

SCENARIOS_DIR = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "oracle_scenarios"


def load_scenario(name: str) -> dict:
    """Load a scenario JSON file."""
    path = SCENARIOS_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


class MockFileSystem:
    """In-memory filesystem for oracle tests."""

    def __init__(self, initial_files: dict[str, str] | None = None):
        self.files: dict[str, str] = initial_files or {}
        self.tool_calls: list[dict] = []

    async def handle_tool_call(self, name: str, parameters: dict) -> dict:
        """Mock tool execution that tracks calls and simulates file ops."""
        self.tool_calls.append({"name": name, "parameters": parameters})

        if name == "read_file":
            path = parameters.get("file_path", "")
            if path in self.files:
                return {"success": True, "result": {"content": self.files[path]}}
            return {"success": False, "error": f"File not found: {path}"}

        elif name in ("write_file", "create_file"):
            path = parameters.get("file_path", "")
            content = parameters.get("content", "")
            self.files[path] = content
            return {"success": True, "result": {"message": f"File written: {path}"}}

        elif name == "edit_file":
            path = parameters.get("file_path", "")
            old = parameters.get("old_content", "")
            new = parameters.get("new_content", "")
            if path in self.files:
                self.files[path] = self.files[path].replace(old, new)
                return {"success": True, "result": {"message": f"File edited: {path}"}}
            return {"success": False, "error": f"File not found: {path}"}

        elif name == "execute_command":
            return {"success": True, "result": {"stdout": "Done", "exit_code": 0}}

        return {"success": True, "result": {"message": f"Mock executed: {name}"}}


@pytest.fixture
def mock_fs():
    """Create a mock filesystem with some initial files."""
    return MockFileSystem(
        {
            "src/App.css": "body {\n  background-color: white;\n  margin: 0;\n}\n",
            "src/utils.ts": (
                "export function formatDate(date: Date): string {\n"
                "  return date.toLocaleDateString();\n"
                "}\n"
                "\n"
                "export function formatCurrency(amount: number): string {\n"
                "  return `$${amount.toFixed(2)}`;\n"
                "}\n"
                "\n"
                "export function generateId(): string {\n"
                "  return Math.random().toString(36).slice(2);\n"
                "}\n"
            ),
            "backend/routes.py": "from fastapi import FastAPI\n\napp = FastAPI()\n\n# Routes\n",
        }
    )


class TestOracleScenarios:
    """Test oracle scenarios by verifying model adapter behavior and assertions."""

    @pytest.mark.asyncio
    async def test_turn_background_orange(self, mock_fs):
        scenario = load_scenario("turn_background_orange")
        adapter = OracleModelAdapter(scenario)
        assertions = scenario["assertions"]

        tool_sequence = []
        final_response = ""

        # Simulate agent loop: call model, handle tool calls, repeat
        for _turn_idx in range(len(scenario["turns"])):
            events = []
            async for event in adapter.chat_with_tools(messages=[], tools=[]):
                events.append(event)

            # Process events
            for event in events:
                if event["type"] == "tool_calls_delta":
                    tc = event["tool_call"]["function"]
                    name = tc["name"]
                    params = json.loads(tc["arguments"])
                    tool_sequence.append(name)
                    await mock_fs.handle_tool_call(name, params)
                elif event["type"] == "text_delta":
                    final_response += event.get("content", "")

        assert tool_sequence == assertions["tool_sequence"]
        assert all(f in mock_fs.files for f in assertions.get("files_modified", []))
        assert assertions["final_response_contains"].lower() in final_response.lower()
        assert len(scenario["turns"]) <= assertions["max_iterations"]

    @pytest.mark.asyncio
    async def test_create_button_component(self, mock_fs):
        scenario = load_scenario("create_button_component")
        adapter = OracleModelAdapter(scenario)
        assertions = scenario["assertions"]

        tool_sequence = []
        final_response = ""

        for _turn_idx in range(len(scenario["turns"])):
            async for event in adapter.chat_with_tools(messages=[], tools=[]):
                if event["type"] == "tool_calls_delta":
                    tc = event["tool_call"]["function"]
                    name = tc["name"]
                    params = json.loads(tc["arguments"])
                    tool_sequence.append(name)
                    await mock_fs.handle_tool_call(name, params)
                elif event["type"] == "text_delta":
                    final_response += event.get("content", "")

        assert tool_sequence == assertions["tool_sequence"]
        for f in assertions.get("files_created", []):
            assert f in mock_fs.files, f"Expected file {f} to be created"
        assert assertions["final_response_contains"].lower() in final_response.lower()

    @pytest.mark.asyncio
    async def test_install_package(self, mock_fs):
        scenario = load_scenario("install_package")
        adapter = OracleModelAdapter(scenario)
        assertions = scenario["assertions"]

        tool_sequence = []
        final_response = ""

        for _turn_idx in range(len(scenario["turns"])):
            async for event in adapter.chat_with_tools(messages=[], tools=[]):
                if event["type"] == "tool_calls_delta":
                    tc = event["tool_call"]["function"]
                    name = tc["name"]
                    params = json.loads(tc["arguments"])
                    tool_sequence.append(name)
                    await mock_fs.handle_tool_call(name, params)
                elif event["type"] == "text_delta":
                    final_response += event.get("content", "")

        assert tool_sequence == assertions["tool_sequence"]
        assert assertions["final_response_contains"].lower() in final_response.lower()

    @pytest.mark.asyncio
    async def test_add_api_route(self, mock_fs):
        scenario = load_scenario("add_api_route")
        adapter = OracleModelAdapter(scenario)
        assertions = scenario["assertions"]

        tool_sequence = []
        final_response = ""

        for _turn_idx in range(len(scenario["turns"])):
            async for event in adapter.chat_with_tools(messages=[], tools=[]):
                if event["type"] == "tool_calls_delta":
                    tc = event["tool_call"]["function"]
                    name = tc["name"]
                    params = json.loads(tc["arguments"])
                    tool_sequence.append(name)
                    await mock_fs.handle_tool_call(name, params)
                elif event["type"] == "text_delta":
                    final_response += event.get("content", "")

        assert tool_sequence == assertions["tool_sequence"]
        assert assertions["final_response_contains"].lower() in final_response.lower()
        # Verify the health route was actually added
        assert "health" in mock_fs.files.get("backend/routes.py", "")

    @pytest.mark.asyncio
    async def test_multi_file_refactor(self, mock_fs):
        scenario = load_scenario("multi_file_refactor")
        adapter = OracleModelAdapter(scenario)
        assertions = scenario["assertions"]

        tool_sequence = []
        final_response = ""

        for _turn_idx in range(len(scenario["turns"])):
            async for event in adapter.chat_with_tools(messages=[], tools=[]):
                if event["type"] == "tool_calls_delta":
                    tc = event["tool_call"]["function"]
                    name = tc["name"]
                    params = json.loads(tc["arguments"])
                    tool_sequence.append(name)
                    await mock_fs.handle_tool_call(name, params)
                elif event["type"] == "text_delta":
                    final_response += event.get("content", "")

        assert tool_sequence == assertions["tool_sequence"]
        for f in assertions.get("files_created", []):
            assert f in mock_fs.files
        for f in assertions.get("files_modified", []):
            assert f in mock_fs.files
        assert assertions["final_response_contains"].lower() in final_response.lower()
        # Verify the extracted file has the expected functions
        assert "formatDate" in mock_fs.files.get("src/formatters.ts", "")
        assert "formatCurrency" in mock_fs.files.get("src/formatters.ts", "")


class TestOracleModelAdapter:
    """Unit tests for the OracleModelAdapter itself."""

    @pytest.mark.asyncio
    async def test_empty_scenario(self):
        adapter = OracleModelAdapter({"turns": []})
        events = []
        async for event in adapter.chat_with_tools([], []):
            events.append(event)
        assert any(e["type"] == "done" for e in events)

    @pytest.mark.asyncio
    async def test_turn_advancement(self):
        adapter = OracleModelAdapter(
            {
                "turns": [
                    {"response_text": "First"},
                    {"response_text": "Second"},
                ]
            }
        )
        # First call
        events1 = [e async for e in adapter.chat_with_tools([], [])]
        assert any(e.get("content") == "First" for e in events1)
        # Second call
        events2 = [e async for e in adapter.chat_with_tools([], [])]
        assert any(e.get("content") == "Second" for e in events2)

    @pytest.mark.asyncio
    async def test_tool_calls_yield_correctly(self):
        adapter = OracleModelAdapter(
            {
                "turns": [
                    {
                        "tool_calls": [
                            {"name": "read_file", "parameters": {"file_path": "test.txt"}},
                            {
                                "name": "write_file",
                                "parameters": {"file_path": "out.txt", "content": "hello"},
                            },
                        ]
                    }
                ]
            }
        )
        events = [e async for e in adapter.chat_with_tools([], [])]
        tool_events = [e for e in events if e["type"] == "tool_calls_delta"]
        assert len(tool_events) == 2
        assert tool_events[0]["tool_call"]["function"]["name"] == "read_file"
        assert tool_events[1]["tool_call"]["function"]["name"] == "write_file"
        assert any(e["type"] == "tool_calls_complete" for e in events)
        assert any(e.get("finish_reason") == "tool_calls" for e in events)
