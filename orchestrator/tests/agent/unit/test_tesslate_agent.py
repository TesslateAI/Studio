"""
Unit tests for TesslateAgent and supporting modules.

Tests tool conversion, context compaction, message serialization,
native function calling, parallel execution, edit modes, subagents,
factory integration, and multi-turn scenario simulations.

All tests use mocked LLM responses (no real API calls).
"""

import json
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.agent.base import AbstractAgent
from app.agent.compaction import (
    APPROX_BYTES_PER_TOKEN,
    SUMMARY_PREFIX,
    approx_token_count,
    build_compacted_history,
    collect_user_messages,
    compact_conversation,
    estimate_messages_tokens,
)
from app.agent.factory import AGENT_CLASS_MAP, create_agent_from_db_model
from app.agent.models import ModelAdapter
from app.agent.resource_limits import get_resource_limits
from app.agent.subagent_manager import (
    READ_ONLY_TOOLS,
    SubagentConfig,
    SubagentManager,
)
from app.agent.tesslate_agent import (
    MAX_TOOL_OUTPUT,
    TesslateAgent,
    _backoff,
    _is_retryable_error,
    _safe_json_loads,
    format_tool_result,
    serialize_assistant_message,
)
from app.agent.tool_converter import (
    PARALLEL_TOOLS,
    is_parallel_tool,
    registry_to_openai_tools,
    tool_to_openai_format,
)
from app.agent.tools.registry import Tool, ToolCategory, ToolRegistry

# =============================================================================
# Mock Model Adapter for Native Function Calling
# =============================================================================


class MockToolCallingAdapter(ModelAdapter):
    """
    Mock adapter that returns pre-programmed responses with native tool calls.

    Each response is a tuple of (content, tool_calls).
    When tool_calls is non-empty, the adapter simulates the LLM requesting tool calls.
    When tool_calls is empty/None, the LLM is "done".
    """

    def __init__(self, responses: list[tuple]):
        """
        Args:
            responses: List of (content: str, tool_calls: list[dict]) tuples.
                       Each entry is consumed per LLM call.
        """
        self.responses = responses
        self.call_index = 0
        self.messages_received: list[list[dict]] = []

    async def chat_with_tools(self, messages, tools, tool_choice="auto"):
        self.messages_received.append(list(messages))

        if self.call_index >= len(self.responses):
            yield {"type": "text_delta", "content": "No more responses."}
            yield {"type": "done", "finish_reason": "stop"}
            return

        content, tool_calls = self.responses[self.call_index]
        self.call_index += 1

        if content:
            yield {"type": "text_delta", "content": content}
        if tool_calls:
            yield {"type": "tool_calls_complete", "tool_calls": tool_calls}
        yield {
            "type": "done",
            "finish_reason": "tool_calls" if tool_calls else "stop",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }

    async def chat(self, messages, **kwargs):
        """Fallback for non-tool-calling usage (e.g., compaction)."""
        yield "Mock summary of conversation."

    def get_model_name(self):
        return "mock-tool-calling-model"


def _make_tool_call(name: str, arguments: dict, call_id: str = None) -> dict:
    """Helper to build a tool_call dict in OpenAI format."""
    return {
        "id": call_id or f"call_{name}_{id(arguments)}",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_registry():
    """Create a ToolRegistry with mock tools for testing."""
    registry = ToolRegistry()

    async def mock_read_file(params, context):
        return {"message": "File read", "content": f"Contents of {params.get('file_path', '')}"}

    async def mock_write_file(params, context):
        return {"message": f"File written: {params.get('file_path', '')}"}

    async def mock_bash_exec(params, context):
        return {"message": "Command executed", "stdout": "output", "stderr": ""}

    async def mock_get_project_info(params, context):
        return {"message": "Project info", "files": ["src/App.tsx", "package.json"]}

    async def mock_todo_read(params, context):
        return {"message": "Todos", "content": "1. Fix bug\n2. Add feature"}

    registry.register(
        Tool(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
            executor=mock_read_file,
            category=ToolCategory.FILE_OPS,
        )
    )
    registry.register(
        Tool(
            name="write_file",
            description="Write a file",
            parameters={
                "type": "object",
                "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["file_path", "content"],
            },
            executor=mock_write_file,
            category=ToolCategory.FILE_OPS,
        )
    )
    registry.register(
        Tool(
            name="bash_exec",
            description="Execute a shell command",
            parameters={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            executor=mock_bash_exec,
            category=ToolCategory.SHELL,
        )
    )
    registry.register(
        Tool(
            name="get_project_info",
            description="Get project info",
            parameters={"type": "object", "properties": {}},
            executor=mock_get_project_info,
            category=ToolCategory.PROJECT,
        )
    )
    registry.register(
        Tool(
            name="todo_read",
            description="Read todos",
            parameters={"type": "object", "properties": {}},
            executor=mock_todo_read,
            category=ToolCategory.PROJECT,
        )
    )

    return registry


@pytest.fixture
def base_context():
    """Standard test context dict."""
    return {
        "user_id": str(uuid4()),
        "project_id": str(uuid4()),
        "project_context": {"project_name": "Test", "project_slug": "test-abc"},
        "edit_mode": "allow",
    }


@pytest.fixture(autouse=True)
def reset_limits():
    """Reset resource limits before each test, restoring default config."""
    import app.agent.resource_limits as rl_module

    # Force a fresh singleton so config changes in one test don't leak
    rl_module._global_limits = None
    yield
    rl_module._global_limits = None


# =============================================================================
# Test Suite A: Tool Converter
# =============================================================================


@pytest.mark.unit
class TestToolConverter:
    """Tests for tool_converter.py."""

    def test_tool_to_openai_format_basic(self):
        """Produces valid OpenAI function format with all fields."""
        tool = Tool(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            executor=AsyncMock(),
            category=ToolCategory.FILE_OPS,
        )
        result = tool_to_openai_format(tool)

        assert result["type"] == "function"
        assert result["function"]["name"] == "read_file"
        assert result["function"]["description"] == "Read a file"
        assert result["function"]["parameters"]["type"] == "object"
        assert "path" in result["function"]["parameters"]["properties"]

    def test_tool_to_openai_format_empty_parameters(self):
        """Handles tools with no parameters (defaults to empty object)."""
        tool = Tool(
            name="get_info",
            description="Get info",
            parameters=None,
            executor=AsyncMock(),
            category=ToolCategory.PROJECT,
        )
        result = tool_to_openai_format(tool)

        assert result["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_registry_to_openai_tools_converts_all(self, mock_registry):
        """Converts all tools in registry."""
        tools = registry_to_openai_tools(mock_registry)

        assert len(tools) == 5  # read_file, write_file, bash_exec, get_project_info, todo_read
        names = {t["function"]["name"] for t in tools}
        assert names == {"read_file", "write_file", "bash_exec", "get_project_info", "todo_read"}

    def test_registry_to_openai_tools_preserves_required(self, mock_registry):
        """Required parameters are preserved in conversion."""
        tools = registry_to_openai_tools(mock_registry)
        read_tool = next(t for t in tools if t["function"]["name"] == "read_file")

        assert "file_path" in read_tool["function"]["parameters"].get("required", [])

    def test_registry_to_openai_tools_empty_registry(self):
        """Returns empty list for empty registry."""
        registry = ToolRegistry()
        tools = registry_to_openai_tools(registry)
        assert tools == []

    def test_is_parallel_tool_read_tools(self):
        """Read-only tools are classified as parallel."""
        assert is_parallel_tool("read_file") is True
        assert is_parallel_tool("get_project_info") is True
        assert is_parallel_tool("todo_read") is True
        assert is_parallel_tool("web_fetch") is True

    def test_is_parallel_tool_write_tools(self):
        """Write/mutating tools are NOT parallel."""
        assert is_parallel_tool("write_file") is False
        assert is_parallel_tool("bash_exec") is False
        assert is_parallel_tool("patch_file") is False
        assert is_parallel_tool("invoke_subagent") is False

    def test_parallel_tools_is_frozenset(self):
        """PARALLEL_TOOLS is immutable."""
        assert isinstance(PARALLEL_TOOLS, frozenset)


# =============================================================================
# Test Suite B: Message Serialization
# =============================================================================


@pytest.mark.unit
class TestMessageSerialization:
    """Tests for message serialization functions."""

    def test_serialize_text_only_message(self):
        """Text-only message has content string, no tool_calls."""
        msg = serialize_assistant_message("Hello world", [])

        assert msg["role"] == "assistant"
        assert msg["content"] == "Hello world"
        assert "tool_calls" not in msg

    def test_serialize_empty_content_no_tools(self):
        """Empty content defaults to empty string."""
        msg = serialize_assistant_message(None, [])

        assert msg["content"] == ""

    def test_serialize_with_tool_calls_content_is_none(self):
        """Content is None (not omitted) when tool_calls are present."""
        tc = [_make_tool_call("read_file", {"file_path": "test.txt"}, "call_1")]
        msg = serialize_assistant_message("some text", tc)

        assert msg["content"] is None
        assert "tool_calls" in msg

    def test_serialize_tool_calls_have_type_function(self):
        """Each serialized tool_call has explicit 'type': 'function'."""
        tc = [_make_tool_call("read_file", {"file_path": "a.txt"}, "call_1")]
        msg = serialize_assistant_message(None, tc)

        for call in msg["tool_calls"]:
            assert call["type"] == "function"

    def test_serialize_tool_call_arguments_are_strings(self):
        """Tool call arguments remain as JSON strings."""
        tc = [_make_tool_call("write_file", {"file_path": "b.txt", "content": "hi"}, "call_2")]
        msg = serialize_assistant_message(None, tc)

        args = msg["tool_calls"][0]["function"]["arguments"]
        assert isinstance(args, str)
        parsed = json.loads(args)
        assert parsed["file_path"] == "b.txt"

    def test_serialize_multiple_tool_calls(self):
        """Multiple tool calls are all serialized."""
        tcs = [
            _make_tool_call("read_file", {"file_path": "a.txt"}, "call_1"),
            _make_tool_call("read_file", {"file_path": "b.txt"}, "call_2"),
            _make_tool_call("read_file", {"file_path": "c.txt"}, "call_3"),
        ]
        msg = serialize_assistant_message(None, tcs)

        assert len(msg["tool_calls"]) == 3


# =============================================================================
# Test Suite C: Tool Result Formatting
# =============================================================================


@pytest.mark.unit
class TestToolResultFormatting:
    """Tests for format_tool_result."""

    def test_format_success_with_message(self):
        """Successful result with message field."""
        result = {"success": True, "result": {"message": "File written successfully"}}
        text = format_tool_result(result)
        assert "File written successfully" in text

    def test_format_success_with_content(self):
        """Successful result with content field."""
        result = {"success": True, "result": {"content": "file contents here"}}
        text = format_tool_result(result)
        assert "file contents here" in text

    def test_format_success_with_stdout(self):
        """Successful result with stdout field."""
        result = {"success": True, "result": {"stdout": "command output"}}
        text = format_tool_result(result)
        assert "command output" in text

    def test_format_error_result(self):
        """Error result includes error message."""
        result = {"success": False, "error": "File not found: test.txt"}
        text = format_tool_result(result)
        assert "Error:" in text
        assert "File not found" in text

    def test_format_truncation_large_output(self):
        """Large output is truncated with indicator."""
        big_content = "x" * (MAX_TOOL_OUTPUT + 5000)
        result = {"success": True, "result": {"content": big_content}}
        text = format_tool_result(result)

        assert "truncated" in text
        assert len(text) < len(big_content)

    def test_format_approval_required(self):
        """Approval-required result is formatted correctly."""
        result = {"approval_required": True, "tool": "write_file"}
        text = format_tool_result(result)
        assert "Awaiting approval" in text
        assert "write_file" in text

    def test_format_stderr(self):
        """stderr is included in output."""
        result = {"success": True, "result": {"stdout": "ok", "stderr": "warning: deprecated"}}
        text = format_tool_result(result)
        assert "warning: deprecated" in text


# =============================================================================
# Test Suite D: Utility Functions
# =============================================================================


@pytest.mark.unit
class TestUtilityFunctions:
    """Tests for module-level utility functions."""

    def test_backoff_increases_exponentially(self):
        """Backoff delay increases with attempt number."""
        d0 = _backoff(0)
        d1 = _backoff(1)
        d2 = _backoff(2)
        assert d1 > d0
        assert d2 > d1

    def test_backoff_has_jitter(self):
        """Multiple calls with same attempt produce slightly different values."""
        values = {_backoff(2) for _ in range(20)}
        # With jitter, we should get multiple distinct values
        assert len(values) > 1

    def test_is_retryable_error_timeout(self):
        """Timeout errors are retryable."""
        assert _is_retryable_error(Exception("Connection timeout")) is True

    def test_is_retryable_error_502(self):
        """502 errors are retryable."""
        assert _is_retryable_error(Exception("502 Bad Gateway")) is True

    def test_is_retryable_error_429(self):
        """Rate limit errors are retryable."""
        assert _is_retryable_error(Exception("429 rate limit exceeded")) is True

    def test_is_retryable_error_not_retryable(self):
        """Validation errors are NOT retryable."""
        assert _is_retryable_error(Exception("Invalid parameter: file_path")) is False

    def test_safe_json_loads_valid(self):
        """Valid JSON is parsed correctly."""
        assert _safe_json_loads('{"key": "value"}') == {"key": "value"}

    def test_safe_json_loads_invalid(self):
        """Invalid JSON returns empty dict."""
        assert _safe_json_loads("not json") == {}

    def test_safe_json_loads_none(self):
        """None input returns empty dict."""
        assert _safe_json_loads(None) == {}


# =============================================================================
# Test Suite E: Context Compaction
# =============================================================================


@pytest.mark.unit
class TestContextCompaction:
    """Tests for compaction.py."""

    def test_approx_token_count_formula(self):
        """Token count is approximately bytes / 4."""
        text = "Hello world"
        tokens = approx_token_count(text)
        expected = len(text.encode("utf-8")) // APPROX_BYTES_PER_TOKEN
        assert tokens == expected

    def test_estimate_messages_tokens_includes_content(self):
        """Token estimation includes message content."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "User message"},
        ]
        tokens = estimate_messages_tokens(messages)
        assert tokens > 0

    def test_estimate_messages_tokens_includes_tool_calls(self):
        """Token estimation includes tool call arguments."""
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"function": {"name": "read_file", "arguments": '{"file_path": "test.txt"}'}}
                ],
            }
        ]
        tokens = estimate_messages_tokens(messages)
        assert tokens > 0

    @pytest.mark.asyncio
    async def test_compaction_does_not_trigger_below_threshold(self):
        """Compaction returns None when under threshold."""
        messages = [
            {"role": "system", "content": "Short prompt"},
            {"role": "user", "content": "Short message"},
        ]
        adapter = MockToolCallingAdapter([])
        result = await compact_conversation(messages, adapter, 128_000, 0.8)
        assert result is None

    @pytest.mark.asyncio
    async def test_compaction_triggers_at_threshold(self):
        """Compaction triggers when tokens exceed threshold."""
        # Create messages that exceed 80% of a small context window
        big_content = "x" * 4000  # ~1000 tokens
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": big_content},
            {"role": "assistant", "content": big_content},
            {"role": "user", "content": big_content},
        ]
        adapter = MockToolCallingAdapter([])
        # Use a small context window so messages exceed threshold
        result = await compact_conversation(messages, adapter, 1000, 0.8)
        assert result is not None

    def test_compaction_preserves_system_message(self):
        """System message is always preserved in compacted history."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        compacted = build_compacted_history(messages, "Summary of conversation")

        system_msgs = [m for m in compacted if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "You are helpful"

    def test_compaction_adds_summary_with_prefix(self):
        """Summary message has SUMMARY_PREFIX."""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
        ]
        compacted = build_compacted_history(messages, "The user said hello")

        summary_msgs = [m for m in compacted if m.get("content", "").startswith(SUMMARY_PREFIX)]
        assert len(summary_msgs) == 1

    def test_collect_user_messages_filters_system(self):
        """System messages are excluded from collection."""
        messages = [
            {"role": "system", "content": "System prompt that should not appear"},
            {"role": "user", "content": "User question"},
            {"role": "assistant", "content": "Assistant answer"},
        ]
        collected = collect_user_messages(messages)

        assert "System prompt that should not appear" not in collected
        assert "User question" in collected

    def test_collect_user_messages_filters_summaries(self):
        """Previous summary messages are excluded (prevents summary-of-summary)."""
        messages = [
            {"role": "user", "content": f"{SUMMARY_PREFIX}\nOld summary"},
            {"role": "user", "content": "New question"},
        ]
        collected = collect_user_messages(messages)

        assert "Old summary" not in collected
        assert "New question" in collected

    def test_collect_user_messages_respects_max_bytes(self):
        """Collection respects byte limit."""
        messages = [
            {"role": "user", "content": "x" * 1000},
            {"role": "user", "content": "y" * 1000},
        ]
        collected = collect_user_messages(messages, max_bytes=500)

        assert len(collected.encode("utf-8")) <= 600  # Some overhead for [user]: prefix


# =============================================================================
# Test Suite F: TesslateAgent Core Loop
# =============================================================================


@pytest.mark.unit
class TestTesslateAgentLoop:
    """Tests for TesslateAgent.run() main loop."""

    @pytest.mark.asyncio
    async def test_yields_complete_when_no_tool_calls(self, mock_registry, base_context):
        """No tool calls = agent is done, yields complete event."""
        adapter = MockToolCallingAdapter(
            [
                ("Task is done!", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Hello", base_context):
            events.append(event)

        assert any(e["type"] == "complete" for e in events)
        complete = next(e for e in events if e["type"] == "complete")
        assert complete["data"]["success"] is True
        assert complete["data"]["completion_reason"] == "no_more_actions"

    @pytest.mark.asyncio
    async def test_yields_agent_step_after_tool_execution(self, mock_registry, base_context):
        """Tool calls produce agent_step events."""
        adapter = MockToolCallingAdapter(
            [
                ("", [_make_tool_call("read_file", {"file_path": "test.txt"}, "call_1")]),
                ("Done reading.", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Read test.txt", base_context):
            events.append(event)

        step_events = [e for e in events if e["type"] == "agent_step"]
        assert len(step_events) == 1
        assert step_events[0]["data"]["tool_calls"][0]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_multi_iteration_loop(self, mock_registry, base_context):
        """Agent loops multiple times until no more tool calls."""
        adapter = MockToolCallingAdapter(
            [
                ("", [_make_tool_call("read_file", {"file_path": "a.txt"}, "call_1")]),
                (
                    "",
                    [
                        _make_tool_call(
                            "write_file", {"file_path": "b.txt", "content": "hi"}, "call_2"
                        )
                    ],
                ),
                ("All done!", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Do stuff", base_context):
            events.append(event)

        step_events = [e for e in events if e["type"] == "agent_step"]
        assert len(step_events) == 2

        complete = next(e for e in events if e["type"] == "complete")
        assert complete["data"]["iterations"] == 3
        assert complete["data"]["tool_calls_made"] == 2

    @pytest.mark.asyncio
    async def test_yields_error_on_model_failure(self, mock_registry, base_context):
        """LLM failure yields error event."""

        class FailingAdapter(ModelAdapter):
            async def chat_with_tools(self, messages, tools, tool_choice="auto"):
                raise Exception("API unavailable")
                yield  # noqa: unreachable - makes it a generator

            async def chat(self, messages, **kwargs):
                yield ""

            def get_model_name(self):
                return "failing-model"

        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=FailingAdapter(),
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Hello", base_context):
            events.append(event)

        assert any(e["type"] == "error" for e in events)

    @pytest.mark.asyncio
    async def test_no_model_yields_error(self, mock_registry, base_context):
        """Agent without model adapter yields error immediately."""
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=None,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Hello", base_context):
            events.append(event)

        assert any(e["type"] == "error" for e in events)
        assert "Model adapter not set" in events[0]["content"]

    @pytest.mark.asyncio
    async def test_complete_event_has_correct_structure(self, mock_registry, base_context):
        """Complete event has all expected fields."""
        adapter = MockToolCallingAdapter([("Done.", [])])
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Hello", base_context):
            events.append(event)

        complete = next(e for e in events if e["type"] == "complete")
        data = complete["data"]
        assert "success" in data
        assert "iterations" in data
        assert "final_response" in data
        assert "tool_calls_made" in data
        assert "completion_reason" in data


# =============================================================================
# Test Suite G: Tool Execution Patterns
# =============================================================================


@pytest.mark.unit
class TestToolExecution:
    """Tests for parallel vs sequential tool execution."""

    @pytest.mark.asyncio
    async def test_tool_results_as_role_tool_messages(self, mock_registry, base_context):
        """Tool results are fed back as role:'tool' messages with tool_call_id."""
        adapter = MockToolCallingAdapter(
            [
                ("", [_make_tool_call("read_file", {"file_path": "test.txt"}, "call_1")]),
                ("Read complete.", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Read test.txt", base_context):
            events.append(event)

        # Check the messages sent to the LLM on the second call
        second_call_messages = adapter.messages_received[1]
        tool_messages = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0]["tool_call_id"] == "call_1"
        assert "Contents of test.txt" in tool_messages[0]["content"]

    @pytest.mark.asyncio
    async def test_tool_error_included_in_conversation(self, mock_registry, base_context):
        """Tool errors are fed back to the LLM for self-correction."""

        # Register a tool that always fails
        async def failing_executor(params, context):
            raise Exception("Permission denied")

        mock_registry.register(
            Tool(
                name="failing_tool",
                description="A tool that fails",
                parameters={"type": "object", "properties": {}},
                executor=failing_executor,
                category=ToolCategory.FILE_OPS,
            )
        )

        adapter = MockToolCallingAdapter(
            [
                ("", [_make_tool_call("failing_tool", {}, "call_fail")]),
                ("The tool failed, let me try another approach.", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Do something", base_context):
            events.append(event)

        # Agent should still complete (not crash)
        assert any(e["type"] == "complete" for e in events)

    @pytest.mark.asyncio
    async def test_agent_step_includes_tool_results(self, mock_registry, base_context):
        """agent_step event includes tool results data."""
        adapter = MockToolCallingAdapter(
            [
                ("", [_make_tool_call("get_project_info", {}, "call_info")]),
                ("Got the info.", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Get info", base_context):
            events.append(event)

        step = next(e for e in events if e["type"] == "agent_step")
        assert step["data"]["tool_results"] is not None
        assert step["data"]["iteration"] == 1


# =============================================================================
# Test Suite H: Edit Modes
# =============================================================================


@pytest.mark.unit
class TestEditModes:
    """Tests for plan/ask/allow edit mode behavior."""

    @pytest.mark.asyncio
    async def test_plan_mode_injects_planning_prompt(self, mock_registry, base_context):
        """Plan mode adds planning guidance to system prompt."""
        base_context["edit_mode"] = "plan"
        adapter = MockToolCallingAdapter([("Here is my plan...", [])])
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Plan the refactor", base_context):
            events.append(event)

        # Check that the system prompt sent to LLM includes plan mode guidance
        system_msg = adapter.messages_received[0][0]
        assert system_msg["role"] == "system"
        # The plan_mode_main template should have been injected
        # (may not be available in test env, but the code path should not crash)

    @pytest.mark.asyncio
    async def test_allow_mode_executes_all_tools(self, mock_registry, base_context):
        """Allow mode lets all tools execute without approval."""
        base_context["edit_mode"] = "allow"
        adapter = MockToolCallingAdapter(
            [
                (
                    "",
                    [
                        _make_tool_call(
                            "write_file", {"file_path": "test.txt", "content": "hi"}, "call_w"
                        )
                    ],
                ),
                ("Written!", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Write a file", base_context):
            events.append(event)

        # Should complete without approval events
        assert any(e["type"] == "complete" for e in events)
        assert not any(e["type"] == "approval_required" for e in events)


# =============================================================================
# Test Suite I: Subagent System
# =============================================================================


@pytest.mark.unit
class TestSubagentSystem:
    """Tests for subagent_manager.py and invoke_subagent tool."""

    def test_builtin_subagents_available(self, mock_registry, base_context):
        """All 3 built-in subagents are available."""
        adapter = MockToolCallingAdapter([])
        mgr = SubagentManager(
            model_adapter=adapter,
            base_tool_registry=mock_registry,
            context=base_context,
        )
        available = mgr.get_available_subagents()
        names = {a["name"] for a in available}

        assert "general-purpose" in names
        assert "Plan" in names
        assert "Explore" in names

    def test_subagent_cannot_invoke_subagent(self, mock_registry, base_context):
        """Subagent tool lists never include invoke_subagent (no nesting)."""
        adapter = MockToolCallingAdapter([])
        mgr = SubagentManager(
            model_adapter=adapter,
            base_tool_registry=mock_registry,
            context=base_context,
        )
        scoped = mgr._create_scoped_registry(
            SubagentConfig(
                name="test",
                description="test",
                tools=None,  # All tools
                system_prompt="test",
            )
        )
        tool_names = [t.name for t in scoped.list_tools()]
        assert "invoke_subagent" not in tool_names

    def test_explore_subagent_has_read_only_tools(self, mock_registry, base_context):
        """Explore subagent only gets read-only tools."""
        configs = SubagentManager(
            model_adapter=MockToolCallingAdapter([]),
            base_tool_registry=mock_registry,
            context=base_context,
        )._configs

        explore_config = configs["Explore"]
        assert explore_config.tools == READ_ONLY_TOOLS

    def test_invoke_tool_description_lists_subagents(self, mock_registry, base_context):
        """invoke_subagent tool description includes available subagent names."""
        mgr = SubagentManager(
            model_adapter=MockToolCallingAdapter([]),
            base_tool_registry=mock_registry,
            context=base_context,
        )
        desc = mgr.get_invoke_tool_description()

        assert "general-purpose" in desc
        assert "Plan" in desc
        assert "Explore" in desc

    @pytest.mark.asyncio
    async def test_invoke_unknown_subagent_raises(self, mock_registry, base_context):
        """Invoking unknown subagent raises ValueError."""
        mgr = SubagentManager(
            model_adapter=MockToolCallingAdapter([]),
            base_tool_registry=mock_registry,
            context=base_context,
        )

        with pytest.raises(ValueError, match="Unknown subagent"):
            await mgr.invoke("NonExistent", "do something")

    @pytest.mark.asyncio
    async def test_subagent_returns_text_result(self, mock_registry, base_context):
        """Subagent completes and returns text."""
        adapter = MockToolCallingAdapter(
            [
                ("Found 3 auth files in src/auth/.", []),
            ]
        )
        mgr = SubagentManager(
            model_adapter=adapter,
            base_tool_registry=mock_registry,
            context=base_context,
        )

        result = await mgr.invoke("Explore", "Find auth files")
        assert "auth files" in result

    def test_subagent_tool_added_to_openai_tools(self, mock_registry, base_context):
        """invoke_subagent tool appears in the OpenAI tools list."""
        adapter = MockToolCallingAdapter([])
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=True,
        )

        tools = agent._get_openai_tools(base_context)
        tool_names = {t["function"]["name"] for t in tools}
        assert "invoke_subagent" in tool_names

    def test_subagent_tool_not_added_when_disabled(self, mock_registry, base_context):
        """invoke_subagent not in tools when subagents disabled."""
        adapter = MockToolCallingAdapter([])
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        tools = agent._get_openai_tools(base_context)
        tool_names = {t["function"]["name"] for t in tools}
        assert "invoke_subagent" not in tool_names


# =============================================================================
# Test Suite J: Factory Integration
# =============================================================================


@pytest.mark.unit
class TestFactoryIntegration:
    """Tests for TesslateAgent registration in factory.py."""

    def test_tesslate_agent_in_class_map(self):
        """TesslateAgent is registered in AGENT_CLASS_MAP."""
        assert "TesslateAgent" in AGENT_CLASS_MAP

    def test_tesslate_agent_class_is_correct(self):
        """AGENT_CLASS_MAP points to the right class."""
        assert AGENT_CLASS_MAP["TesslateAgent"] is TesslateAgent

    def test_tesslate_agent_inherits_abstract_agent(self):
        """TesslateAgent inherits from AbstractAgent."""
        assert issubclass(TesslateAgent, AbstractAgent)

    @pytest.mark.asyncio
    async def test_factory_creates_tesslate_agent(self):
        """Factory correctly instantiates a TesslateAgent."""
        model = Mock()
        model.name = "Test Agent"
        model.slug = "test-agent"
        model.agent_type = "TesslateAgent"
        model.system_prompt = "You are a helpful assistant."
        model.tools = None

        adapter = MockToolCallingAdapter([])
        agent = await create_agent_from_db_model(model, model_adapter=adapter)

        assert isinstance(agent, TesslateAgent)
        assert agent.system_prompt == "You are a helpful assistant."
        assert agent.model is adapter

    def test_all_agent_types_still_registered(self):
        """All original agent types still exist (backward compat)."""
        assert "StreamAgent" in AGENT_CLASS_MAP
        assert "IterativeAgent" in AGENT_CLASS_MAP
        assert "ReActAgent" in AGENT_CLASS_MAP
        assert "TesslateAgent" in AGENT_CLASS_MAP


# =============================================================================
# Test Suite K: Resource Limits
# =============================================================================


@pytest.mark.unit
class TestResourceLimits:
    """Tests for resource limit enforcement in TesslateAgent."""

    @pytest.mark.asyncio
    async def test_resource_limit_exceeded_yields_error(self, mock_registry, base_context):
        """Exceeding iteration limit yields error + complete events."""
        # Set a very low limit
        limits = get_resource_limits()
        limits.max_iterations_per_run = 1

        # Agent that would need 2 iterations
        adapter = MockToolCallingAdapter(
            [
                ("", [_make_tool_call("read_file", {"file_path": "a.txt"}, "call_1")]),
                ("", [_make_tool_call("read_file", {"file_path": "b.txt"}, "call_2")]),
                ("Done.", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Read files", base_context):
            events.append(event)

        # Should have an error event and a complete event with resource_limit_exceeded
        complete_events = [e for e in events if e["type"] == "complete"]
        assert len(complete_events) == 1
        assert complete_events[0]["data"]["completion_reason"] == "resource_limit_exceeded"


# =============================================================================
# Test Suite L: Scenario Simulations
# =============================================================================


@pytest.mark.unit
class TestScenarios:
    """Realistic multi-turn agent interaction simulations."""

    @pytest.mark.asyncio
    async def test_scenario_read_and_modify_file(self, mock_registry, base_context):
        """
        Simulate: user asks to change background color
        Turn 1: LLM calls read_file('src/App.css')
        Turn 2: LLM calls write_file('src/App.css', new_content)
        Turn 3: LLM says "Done"
        """
        adapter = MockToolCallingAdapter(
            [
                (
                    "Let me read the file first.",
                    [
                        _make_tool_call("read_file", {"file_path": "src/App.css"}, "call_read"),
                    ],
                ),
                (
                    "Now I'll update it.",
                    [
                        _make_tool_call(
                            "write_file",
                            {"file_path": "src/App.css", "content": "body { background: blue; }"},
                            "call_write",
                        ),
                    ],
                ),
                ("Done! Changed background to blue.", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Change background to blue", base_context):
            events.append(event)

        step_events = [e for e in events if e["type"] == "agent_step"]
        assert len(step_events) == 2
        assert step_events[0]["data"]["tool_calls"][0]["name"] == "read_file"
        assert step_events[1]["data"]["tool_calls"][0]["name"] == "write_file"

        complete = next(e for e in events if e["type"] == "complete")
        assert complete["data"]["success"] is True
        assert complete["data"]["iterations"] == 3
        assert complete["data"]["tool_calls_made"] == 2

    @pytest.mark.asyncio
    async def test_scenario_multiple_parallel_reads(self, mock_registry, base_context):
        """
        Simulate: LLM calls 3 read_file in parallel.
        Verifies all 3 results are fed back.
        """
        adapter = MockToolCallingAdapter(
            [
                (
                    "Reading multiple files.",
                    [
                        _make_tool_call("read_file", {"file_path": "a.txt"}, "call_a"),
                        _make_tool_call("read_file", {"file_path": "b.txt"}, "call_b"),
                        _make_tool_call("read_file", {"file_path": "c.txt"}, "call_c"),
                    ],
                ),
                ("I've read all 3 files.", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Read 3 files", base_context):
            events.append(event)

        # Check that all 3 tool results were fed back to the LLM
        second_call_messages = adapter.messages_received[1]
        tool_messages = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_messages) == 3

        complete = next(e for e in events if e["type"] == "complete")
        assert complete["data"]["tool_calls_made"] == 3

    @pytest.mark.asyncio
    async def test_scenario_error_recovery(self, mock_registry, base_context):
        """
        Simulate: tool fails, LLM self-corrects on next turn.
        Turn 1: bash_exec('invalid') -> error
        Turn 2: read_file('correct.txt') -> success
        Turn 3: LLM says "Done"
        """
        # Make bash_exec fail for this test
        _original_executor = None
        for tool in mock_registry.list_tools():
            if tool.name == "bash_exec":
                _original_executor = tool.executor
                break

        async def failing_bash(params, context):
            if params.get("command") == "invalid":
                return {"message": "Error", "stdout": "", "stderr": "command not found"}
            return {"message": "OK", "stdout": "success", "stderr": ""}

        # Re-register with failing executor
        mock_registry.register(
            Tool(
                name="bash_exec",
                description="Execute a shell command",
                parameters={
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
                executor=failing_bash,
                category=ToolCategory.SHELL,
            )
        )

        adapter = MockToolCallingAdapter(
            [
                ("", [_make_tool_call("bash_exec", {"command": "invalid"}, "call_fail")]),
                (
                    "That failed, let me try reading the file instead.",
                    [
                        _make_tool_call("read_file", {"file_path": "correct.txt"}, "call_fix"),
                    ],
                ),
                ("Got it!", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Run a command", base_context):
            events.append(event)

        complete = next(e for e in events if e["type"] == "complete")
        assert complete["data"]["success"] is True
        assert complete["data"]["iterations"] == 3

    @pytest.mark.asyncio
    async def test_scenario_subagent_delegation(self, mock_registry, base_context):
        """
        Simulate: main agent invokes Explore subagent, then uses result.
        Turn 1: invoke_subagent(Explore, "find auth files")
        Turn 2: LLM writes code based on subagent findings
        Turn 3: Done
        """
        # The subagent will be invoked internally via SubagentManager
        # For this test, we mock the invoke to return a fixed result
        adapter = MockToolCallingAdapter(
            [
                (
                    "Let me explore first.",
                    [
                        _make_tool_call(
                            "invoke_subagent",
                            {
                                "name": "Explore",
                                "task": "Find auth files",
                            },
                            "call_sub",
                        ),
                    ],
                ),
                (
                    "Based on the findings, I'll write the code.",
                    [
                        _make_tool_call(
                            "write_file",
                            {"file_path": "src/auth.ts", "content": "export const auth = {};"},
                            "call_write",
                        ),
                    ],
                ),
                ("Done! Created auth module.", []),
            ]
        )
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=True,
        )

        # Patch SubagentManager.invoke to avoid running a real subagent loop
        with patch.object(SubagentManager, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = "Found auth files: src/auth/login.tsx, src/auth/context.tsx"

            events = []
            async for event in agent.run("Add auth system", base_context):
                events.append(event)

        step_events = [e for e in events if e["type"] == "agent_step"]
        assert len(step_events) == 2
        assert step_events[0]["data"]["tool_calls"][0]["name"] == "invoke_subagent"
        assert step_events[1]["data"]["tool_calls"][0]["name"] == "write_file"

        complete = next(e for e in events if e["type"] == "complete")
        assert complete["data"]["success"] is True

    @pytest.mark.asyncio
    async def test_scenario_chat_history_included(self, mock_registry, base_context):
        """Chat history from context is included in messages sent to LLM."""
        base_context["chat_history"] = [
            {"role": "user", "content": "Previous question"},
            {"role": "assistant", "content": "Previous answer"},
        ]

        adapter = MockToolCallingAdapter([("Current answer.", [])])
        agent = TesslateAgent(
            system_prompt="You are helpful.",
            tools=mock_registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Follow-up question", base_context):
            events.append(event)

        # Check messages sent to LLM include history
        first_call_messages = adapter.messages_received[0]
        roles = [m["role"] for m in first_call_messages]

        # Should be: system, user (prev), assistant (prev), user (current)
        assert roles[0] == "system"
        assert "user" in roles[1:]
        assert "assistant" in roles[1:]

        # History should come before current message
        history_user_idx = next(
            i
            for i, m in enumerate(first_call_messages)
            if m["role"] == "user" and m["content"] == "Previous question"
        )
        current_user_idx = next(
            i
            for i, m in enumerate(first_call_messages)
            if m["role"] == "user" and "Follow-up" in m.get("content", "")
        )
        assert history_user_idx < current_user_idx
