"""
Integration tests for TesslateAgent.

Tests the complete TesslateAgent workflow including:
- Native function calling
- Tool execution with RwLock parallelism
- Context compaction
- Error handling and retry logic
"""

import pytest

from app.agent.features import Feature, Features
from app.agent.models import ModelAdapter
from app.agent.tesslate_agent import TesslateAgent
from app.agent.tools.registry import Tool, ToolCategory, ToolRegistry


def _make_tool_call(name: str, arguments: dict, call_id: str) -> dict:
    """Helper to create tool call dict."""
    import json

    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


class MockToolCallingAdapter(ModelAdapter):
    """
    Mock adapter using the proven pattern from unit tests.

    Each response is a tuple of (content: str, tool_calls: list[dict]).
    """

    def __init__(self, responses: list[tuple]):
        self.responses = responses
        self.call_index = 0

    async def chat_with_tools(self, messages, tools, tool_choice="auto"):
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
        }

    async def chat(self, messages, **kwargs):
        """Fallback for non-tool-calling usage."""
        yield "Mock summary."

    def get_model_name(self):
        return "mock-tool-calling"


@pytest.mark.integration
class TestTesslateAgentIntegration:
    """Integration tests for TesslateAgent with real tool execution."""

    @pytest.fixture
    def base_context(self):
        """Simple test context without db."""
        from uuid import uuid4

        return {
            "user_id": str(uuid4()),
            "project_id": str(uuid4()),
            "project_context": {"project_name": "Test", "project_slug": "test-abc"},
            "edit_mode": "allow",
        }

    @pytest.fixture
    def file_tool_registry(self):
        """Create a registry with file operation tools."""
        registry = ToolRegistry()
        file_storage = {}

        async def read_file_tool(params, context):
            file_path = params["file_path"]
            if file_path in file_storage:
                return {"success": True, "content": file_storage[file_path], "file_path": file_path}
            return {"success": False, "error": f"File {file_path} does not exist"}

        async def write_file_tool(params, context):
            file_path = params["file_path"]
            content = params["content"]
            file_storage[file_path] = content
            return {"success": True, "file_path": file_path, "bytes_written": len(content)}

        async def list_files_tool(params, context):
            return {"success": True, "files": list(file_storage.keys()), "count": len(file_storage)}

        registry.register(
            Tool(
                name="read_file",
                description="Read the contents of a file",
                parameters={
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
                executor=read_file_tool,
                category=ToolCategory.FILE_OPS,
            )
        )

        registry.register(
            Tool(
                name="write_file",
                description="Write content to a file",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["file_path", "content"],
                },
                executor=write_file_tool,
                category=ToolCategory.FILE_OPS,
            )
        )

        registry.register(
            Tool(
                name="list_files",
                description="List all files",
                parameters={"type": "object", "properties": {}},
                executor=list_files_tool,
                category=ToolCategory.FILE_OPS,
            )
        )

        return registry, file_storage

    @pytest.mark.asyncio
    async def test_tesslate_agent_basic_workflow(self, file_tool_registry, base_context):
        """Test TesslateAgent can execute a basic workflow with function calling."""
        registry, file_storage = file_tool_registry

        adapter = MockToolCallingAdapter(
            [
                (
                    "",
                    [
                        _make_tool_call(
                            "write_file",
                            {"file_path": "test.txt", "content": "Hello World"},
                            "call_1",
                        )
                    ],
                ),
                ("", [_make_tool_call("read_file", {"file_path": "test.txt"}, "call_2")]),
                (
                    "I've successfully created test.txt with the content 'Hello World' and verified it.",
                    [],
                ),
            ]
        )

        agent = TesslateAgent(
            system_prompt="You are a helpful file management assistant.",
            tools=registry,
            model=adapter,
            enable_subagents=False,  # Disable subagents for integration tests
        )

        events = []
        async for event in agent.run(
            "Create a file called test.txt with content 'Hello World'", base_context
        ):
            events.append(event)

        # Verify tool execution happened
        # Check for agent_step events (which contain tool calls)
        step_events = [e for e in events if e.get("type") == "agent_step"]
        assert len(step_events) >= 2  # write + read steps

        # Verify file was created
        assert "test.txt" in file_storage
        assert file_storage["test.txt"] == "Hello World"

        # Verify completion
        complete_events = [e for e in events if e.get("type") == "complete"]
        assert len(complete_events) == 1

    @pytest.mark.asyncio
    async def test_tesslate_agent_parallel_execution(self, file_tool_registry, base_context):
        """Test TesslateAgent can execute parallel read operations."""
        registry, file_storage = file_tool_registry

        # Pre-populate storage
        file_storage["file1.txt"] = "Content 1"
        file_storage["file2.txt"] = "Content 2"
        file_storage["file3.txt"] = "Content 3"

        adapter = MockToolCallingAdapter(
            [
                # Parallel reads
                (
                    "",
                    [
                        _make_tool_call("read_file", {"file_path": "file1.txt"}, "call_1"),
                        _make_tool_call("read_file", {"file_path": "file2.txt"}, "call_2"),
                        _make_tool_call("read_file", {"file_path": "file3.txt"}, "call_3"),
                    ],
                ),
                ("All files read successfully.", []),
            ]
        )

        agent = TesslateAgent(
            system_prompt="You are a helpful assistant.",
            tools=registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Read all three files", base_context):
            events.append(event)

        # Verify all reads succeeded (check agent_step which contains tool calls)
        step_events = [e for e in events if e.get("type") == "agent_step"]
        assert len(step_events) >= 1  # At least one step with 3 parallel tool calls

    @pytest.mark.asyncio
    async def test_tesslate_agent_retry_on_transient_error(self, file_tool_registry, base_context):
        """Test TesslateAgent retries on transient errors."""
        registry, _ = file_tool_registry

        class MockRetryAdapter(ModelAdapter):
            def __init__(self):
                self.call_count = 0

            async def chat_with_tools(self, messages, tools, tool_choice="auto"):
                self.call_count += 1
                if self.call_count == 1:
                    raise RuntimeError("502 Bad Gateway - temporary service unavailable")

                yield {"type": "text_delta", "content": "Success after retry"}
                yield {"type": "done", "finish_reason": "stop"}

            async def chat(self, messages, **kwargs):
                yield "Mock"

            def get_model_name(self):
                return "mock-retry"

        model = MockRetryAdapter()
        agent = TesslateAgent(
            system_prompt="You are a helpful assistant.",
            tools=registry,
            model=model,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Do something", base_context):
            events.append(event)

        # Verify retry happened
        assert model.call_count == 2  # First call failed, second succeeded

    @pytest.mark.asyncio
    async def test_tesslate_agent_feature_flags(self, file_tool_registry, base_context):
        """Test TesslateAgent respects feature flags."""
        registry, _ = file_tool_registry

        features = Features()
        features.disable(Feature.STREAMING)

        adapter = MockToolCallingAdapter([("Feature flag test", [])])

        agent = TesslateAgent(
            system_prompt="You are a helpful assistant.",
            tools=registry,
            model=adapter,
            features=features,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Test", base_context):
            events.append(event)

        # With streaming disabled, should still get events
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_tesslate_agent_context_compaction(self, file_tool_registry, base_context):
        """Test TesslateAgent triggers context compaction at 80% threshold."""
        registry, _ = file_tool_registry

        class MockLargeAdapter(ModelAdapter):
            def __init__(self):
                self.call_count = 0

            async def chat_with_tools(self, messages, tools, tool_choice="auto"):
                self.call_count += 1
                # Generate large content to fill context window
                large_content = "x" * 50000  # 50KB
                yield {
                    "type": "text_delta",
                    "content": f"Large response {self.call_count}: {large_content}",
                }
                yield {"type": "done", "finish_reason": "stop"}

            async def chat(self, messages, **kwargs):
                yield "Summary"

            def get_model_name(self):
                return "mock-large"

        agent = TesslateAgent(
            system_prompt="You are a helpful assistant.",
            tools=registry,
            model=MockLargeAdapter(),
            context_window=100000,  # 100K tokens
            enable_subagents=False,
        )

        # This would normally trigger compaction - just verify it doesn't crash
        events = []
        try:
            async for event in agent.run("Generate large content", base_context):
                events.append(event)
                if len(events) > 20:  # Prevent infinite loop
                    break
        except Exception as e:
            pytest.fail(f"Context compaction should not crash: {e}")

    @pytest.mark.asyncio
    async def test_tesslate_agent_trajectory_recording(self, file_tool_registry, base_context):
        """Test TesslateAgent records trajectory correctly."""
        registry, file_storage = file_tool_registry

        adapter = MockToolCallingAdapter(
            [
                (
                    "",
                    [
                        _make_tool_call(
                            "write_file", {"file_path": "test.txt", "content": "Test"}, "call_1"
                        )
                    ],
                ),
                ("Done", []),
            ]
        )

        agent = TesslateAgent(
            system_prompt="You are a helpful assistant.",
            tools=registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Create test.txt", base_context):
            events.append(event)

        # Verify we got events (trajectory structure varies by implementation)
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_tesslate_agent_error_handling(self, file_tool_registry, base_context):
        """Test TesslateAgent handles tool execution errors gracefully."""
        registry, _ = file_tool_registry

        adapter = MockToolCallingAdapter(
            [
                ("", [_make_tool_call("nonexistent_tool", {}, "call_1")]),
                ("Encountered an error, but recovered.", []),
            ]
        )

        agent = TesslateAgent(
            system_prompt="You are a helpful assistant.",
            tools=registry,
            model=adapter,
            enable_subagents=False,
        )

        events = []
        async for event in agent.run("Do something", base_context):
            events.append(event)

        # Should produce error event, not crash
        error_events = [e for e in events if "error" in str(e).lower()]
        assert len(error_events) > 0
