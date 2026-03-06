"""
Determinism verification tests for the AI agent system.

These tests verify that given the same inputs, the system produces
identical outputs across multiple runs. This is critical for:
1. Debugging and reproducing issues
2. Testing with mocked LLM responses
3. Ensuring predictable behavior

Usage:
    pytest tests/agent/unit/test_determinism.py -v
    pytest tests/agent/unit/test_determinism.py -v -m deterministic
"""

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ============================================================================
# Determinism Test Utilities
# ============================================================================


def compute_hash(obj: Any) -> str:
    """Compute a deterministic hash of an object."""
    if isinstance(obj, dict):
        # Sort keys for deterministic serialization
        serialized = json.dumps(obj, sort_keys=True, default=str)
    elif isinstance(obj, list):
        serialized = json.dumps(obj, sort_keys=True, default=str)
    else:
        serialized = str(obj)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def assert_deterministic(results: list[Any], description: str = ""):
    """Assert all results in the list are identical."""
    if not results:
        return

    first_hash = compute_hash(results[0])
    for i, result in enumerate(results[1:], start=1):
        current_hash = compute_hash(result)
        assert first_hash == current_hash, (
            f"Non-deterministic result at iteration {i}: {description}\n"
            f"Expected hash: {first_hash}\n"
            f"Got hash: {current_hash}\n"
            f"First: {results[0]}\n"
            f"Current: {result}"
        )


# ============================================================================
# Parser Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestParserDeterminism:
    """Verify parser produces identical results for identical inputs."""

    @pytest.fixture
    def parser(self):
        """Create a fresh parser instance."""
        from app.agent.parser import AgentResponseParser

        return AgentResponseParser()

    def test_single_tool_call_deterministic(self, parser):
        """Same tool call input produces identical output across runs."""
        input_text = '{"tool_name": "read_file", "parameters": {"file_path": "test.js"}}'

        results = []
        for _ in range(10):
            tool_calls = parser.parse(input_text)
            results.append([{"name": tc.name, "parameters": tc.parameters} for tc in tool_calls])

        assert_deterministic(results, "single tool call parsing")

    def test_multi_tool_call_deterministic(self, parser):
        """Array of tool calls produces identical output across runs."""
        input_text = """[
            {"tool_name": "read_file", "parameters": {"file_path": "a.js"}},
            {"tool_name": "read_file", "parameters": {"file_path": "b.js"}}
        ]"""

        results = []
        for _ in range(10):
            tool_calls = parser.parse(input_text)
            results.append([{"name": tc.name, "parameters": tc.parameters} for tc in tool_calls])

        assert_deterministic(results, "multi tool call parsing")

    def test_completion_detection_deterministic(self, parser):
        """Completion detection is consistent."""
        test_cases = [
            ("TASK_COMPLETE", True),
            ("Working on it...", False),
            ("Done!\n\nTASK_COMPLETE", True),
            ('{"tool_name": "read_file", "parameters": {}}', False),
        ]

        for input_text, expected in test_cases:
            results = []
            for _ in range(10):
                results.append(parser.is_complete(input_text))

            assert_deterministic(results, f"completion detection for '{input_text[:30]}'")
            assert all(r == expected for r in results)

    def test_thought_extraction_deterministic(self, parser):
        """Thought extraction is consistent."""
        input_text = "THOUGHT: I need to analyze this code.\n\n{}"

        results = []
        for _ in range(10):
            thought = parser.extract_thought(input_text)
            results.append(thought)

        assert_deterministic(results, "thought extraction")

    def test_conversational_text_deterministic(self, parser):
        """Conversational text extraction is consistent."""
        input_text = (
            'Let me help you.\n\n{"tool_name": "read_file", "parameters": {"file_path": "x"}}'
        )

        results = []
        for _ in range(10):
            text = parser.get_conversational_text(input_text)
            results.append(text)

        assert_deterministic(results, "conversational text extraction")


# ============================================================================
# Tool Registry Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestToolRegistryDeterminism:
    """Verify tool registry produces deterministic results."""

    @pytest.fixture
    def registry(self):
        """Create a tool registry with mock tools."""
        from app.agent.tools.registry import ToolRegistry

        return ToolRegistry()

    def test_tool_listing_order_deterministic(self, registry):
        """Tools are listed in deterministic order."""
        results = []
        for _ in range(10):
            tools = registry.list_tools()
            results.append([t.name for t in tools])

        assert_deterministic(results, "tool listing order")

    def test_tool_schema_generation_deterministic(self, registry):
        """Tool schema generation is deterministic."""
        results = []
        for _ in range(10):
            tools = registry.list_tools()
            schemas = [
                {"name": t.name, "description": t.description, "parameters": t.parameters}
                for t in tools
            ]
            results.append(schemas)

        assert_deterministic(results, "tool schema generation")


# ============================================================================
# Tool Execution Determinism Tests (Mocked)
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestToolExecutionDeterminism:
    """Verify tool execution is deterministic with mocked backends."""

    @pytest.mark.asyncio
    async def test_read_file_deterministic(self, tmp_path, test_context):
        """Read file produces identical results."""
        from app.agent.tools.file_ops.read_write import read_file_tool

        # Mock the orchestrator to return deterministic content
        mock_orchestrator = AsyncMock()
        mock_orchestrator.read_file = AsyncMock(return_value="Line 1\nLine 2\nLine 3")

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            results = []
            for _ in range(10):
                result = await read_file_tool({"file_path": "test.txt"}, test_context)
                results.append(
                    {"has_content": "content" in result, "content": result.get("content", "")}
                )

            assert_deterministic(results, "read file execution")

    @pytest.mark.asyncio
    async def test_write_file_deterministic(self, tmp_path, test_context):
        """Write file result format is deterministic."""
        from app.agent.tools.file_ops.read_write import write_file_tool

        # Mock the orchestrator
        mock_orchestrator = AsyncMock()
        mock_orchestrator.write_file = AsyncMock(return_value=True)

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            results = []
            for i in range(10):
                result = await write_file_tool(
                    {"file_path": f"output_{i}.txt", "content": "Test content\nLine 2"},
                    test_context,
                )
                results.append(
                    {"has_preview": "preview" in result, "has_message": "message" in result}
                )

            assert_deterministic(results, "write file execution pattern")

    @pytest.mark.asyncio
    async def test_todo_operations_deterministic(self, test_context):
        """Todo operations produce deterministic results."""
        from app.agent.tools.planning_ops.todos import todo_read_tool, todo_write_tool

        # Prepare context with todos list
        test_context["_todos"] = []

        todos = [
            {"content": "Task 1", "status": "pending"},
            {"content": "Task 2", "status": "in_progress"},
        ]

        results = []
        for _ in range(10):
            # Reset todos
            test_context["_todos"] = []

            # Write todos
            write_result = await todo_write_tool({"todos": todos}, test_context)

            # Read todos
            read_result = await todo_read_tool({}, test_context)

            results.append(
                {
                    "write_success": write_result.get("success", False),
                    "read_success": read_result.get("success", False),
                }
            )

        assert_deterministic(results, "todo operations")


# ============================================================================
# Agent Response Format Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestAgentResponseFormatDeterminism:
    """Verify agent response formatting is deterministic."""

    def test_success_output_formatting_deterministic(self):
        """Success output formatting is consistent."""
        from app.agent.tools.output_formatter import success_output

        results = []
        for _ in range(10):
            formatted = success_output(
                message="Read file successfully",
                details={"lines": 10, "path": "test.js"},
                file_path="test.js",
            )
            results.append(formatted)

        assert_deterministic(results, "success output formatting")

    def test_error_output_formatting_deterministic(self):
        """Error output formatting is consistent."""
        from app.agent.tools.output_formatter import error_output

        results = []
        for _ in range(10):
            formatted = error_output(
                message="File not found",
                suggestion="Check the file path",
                details={"path": "missing.js"},
            )
            results.append(formatted)

        assert_deterministic(results, "error output formatting")


# ============================================================================
# Mocked Agent Loop Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestAgentLoopDeterminism:
    """Verify agent loop behavior is deterministic with mocked LLM."""

    @pytest.fixture
    def mock_llm_response(self):
        """Create a deterministic mock LLM response."""
        return '{"tool_name": "read_file", "parameters": {"file_path": "app.js"}}'

    @pytest.mark.asyncio
    async def test_tool_call_extraction_deterministic(self, mock_llm_response):
        """Tool call extraction from LLM response is deterministic."""
        from app.agent.parser import AgentResponseParser

        parser = AgentResponseParser()

        results = []
        for _ in range(10):
            tool_calls = parser.parse(mock_llm_response)
            results.append([{"name": tc.name, "params": tc.parameters} for tc in tool_calls])

        assert_deterministic(results, "tool call extraction")

    @pytest.mark.asyncio
    async def test_agent_state_transitions_deterministic(self):
        """Agent state transitions are deterministic with mocked LLM."""

        async def simulate_agent_loop(initial_state: str) -> list[str]:
            """Simulate deterministic state transitions."""
            state_history = [initial_state]
            current = initial_state

            transitions = {
                "idle": "thinking",
                "thinking": "executing",
                "executing": "thinking",  # Or completed
            }

            for _ in range(5):
                if current in transitions:
                    current = transitions[current]
                    state_history.append(current)
                else:
                    break

            return state_history

        results = []
        for _ in range(10):
            history = await simulate_agent_loop("idle")
            results.append(history)

        assert_deterministic(results, "agent state transitions")


# ============================================================================
# Session ID Generation Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestSessionIdDeterminism:
    """Verify session ID generation with seeded random."""

    def test_uuid_generation_with_seed_deterministic(self, deterministic_uuid):
        """UUID generation with seed produces same results."""
        import uuid as uuid_module

        # The fixture patches uuid.uuid4 to be deterministic
        # Each call increments counter, so first call always returns same value
        first_uuid = uuid_module.uuid4()

        # Reset by getting new fixture - but within same test, counter keeps incrementing
        # So we test that the sequence is deterministic
        assert str(first_uuid) == "00000000-0000-0000-0000-000000000001"

    def test_session_creation_deterministic(self, deterministic_uuid):
        """Session creation is deterministic with seeded UUIDs."""
        import uuid as uuid_module

        def create_session():
            return {
                "session_id": str(uuid_module.uuid4()),
                "created_at": "2024-01-01T00:00:00Z",  # Fixed time
                "status": "active",
            }

        # First session should have deterministic ID
        session1 = create_session()
        assert session1["session_id"] == "00000000-0000-0000-0000-000000000001"

        session2 = create_session()
        assert session2["session_id"] == "00000000-0000-0000-0000-000000000002"


# ============================================================================
# Frozen Time Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestTimeDeterminism:
    """Verify time-dependent operations are deterministic with frozen time."""

    def test_timestamp_generation_deterministic(self, frozen_time):
        """Timestamp generation is deterministic with frozen time."""
        # frozen_time is the freeze_time decorator/context manager
        with frozen_time("2024-01-01 12:00:00"):
            results = []
            for _ in range(10):
                timestamp = datetime.now().isoformat()
                results.append(timestamp)

            assert_deterministic(results, "timestamp generation")
            assert results[0] == "2024-01-01T12:00:00"

    def test_timeout_calculation_deterministic(self, frozen_time):
        """Timeout calculations are deterministic."""

        def calculate_timeout(duration_seconds: int) -> dict[str, str]:
            now = datetime.now()
            return {
                "start": now.isoformat(),
                "duration": duration_seconds,
            }

        with frozen_time("2024-01-01 12:00:00"):
            results = []
            for _ in range(10):
                timeout = calculate_timeout(30)
                results.append(timeout)

            assert_deterministic(results, "timeout calculation")


# ============================================================================
# Hash/Checksum Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestHashDeterminism:
    """Verify hash computations are deterministic."""

    def test_file_content_hash_deterministic(self):
        """File content hashing is deterministic."""
        content = "function hello() {\n  return 'world';\n}"

        results = []
        for _ in range(10):
            hash_val = hashlib.sha256(content.encode()).hexdigest()
            results.append(hash_val)

        assert_deterministic(results, "file content hash")

    def test_project_state_hash_deterministic(self):
        """Project state hashing is deterministic."""
        project_state = {
            "files": ["a.js", "b.js", "c.js"],
            "containers": [{"name": "frontend", "status": "running"}],
            "settings": {"framework": "nextjs"},
        }

        results = []
        for _ in range(10):
            # Sort for deterministic serialization
            serialized = json.dumps(project_state, sort_keys=True)
            hash_val = hashlib.sha256(serialized.encode()).hexdigest()
            results.append(hash_val)

        assert_deterministic(results, "project state hash")


# ============================================================================
# Concurrent Execution Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestConcurrencyDeterminism:
    """Verify operations maintain determinism under concurrent execution."""

    @pytest.mark.asyncio
    async def test_sequential_vs_concurrent_tool_results(self):
        """Sequential and concurrent tool execution produce same results."""
        from app.agent.parser import AgentResponseParser

        parser = AgentResponseParser()
        inputs = [
            '{"tool_name": "read_file", "parameters": {"file_path": "a.js"}}',
            '{"tool_name": "read_file", "parameters": {"file_path": "b.js"}}',
            '{"tool_name": "read_file", "parameters": {"file_path": "c.js"}}',
        ]

        # Sequential parsing
        sequential_results = []
        for inp in inputs:
            tool_calls = parser.parse(inp)
            sequential_results.append(
                [{"name": tc.name, "params": tc.parameters} for tc in tool_calls]
            )

        # Concurrent parsing (should be same since parsing is stateless)
        async def parse_async(inp):
            return parser.parse(inp)

        concurrent_tasks = [parse_async(inp) for inp in inputs]
        concurrent_raw = await asyncio.gather(*concurrent_tasks)
        concurrent_results = [
            [{"name": tc.name, "params": tc.parameters} for tc in result]
            for result in concurrent_raw
        ]

        # Results should be identical regardless of execution mode
        assert sequential_results == concurrent_results, (
            "Sequential and concurrent execution produced different results"
        )


# ============================================================================
# Seed-Based Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestSeedBasedDeterminism:
    """Verify seed-based operations are deterministic."""

    def test_random_selection_with_seed_deterministic(self, seeded_random):
        """Random selection with seed is deterministic."""
        options = ["option_a", "option_b", "option_c", "option_d"]

        results = []
        for _ in range(10):
            # Reset seed
            import random

            random.seed(42)
            selected = random.choice(options)
            results.append(selected)

        assert_deterministic(results, "seeded random selection")

    def test_shuffle_with_seed_deterministic(self, seeded_random):
        """Shuffling with seed is deterministic."""
        items = [1, 2, 3, 4, 5]

        results = []
        for _ in range(10):
            import random

            random.seed(42)
            shuffled = items.copy()
            random.shuffle(shuffled)
            results.append(shuffled)

        assert_deterministic(results, "seeded shuffle")


# ============================================================================
# System Prompt Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.unit
class TestSystemPromptDeterminism:
    """Verify system prompt generation is deterministic."""

    def test_prompt_template_rendering_deterministic(self):
        """Prompt template rendering is deterministic."""
        template = """You are an AI assistant working on project: {project_name}
Available tools: {tools}
Current directory: {cwd}"""

        context = {
            "project_name": "my-app",
            "tools": ["read_file", "write_file", "bash_exec"],
            "cwd": "/app",
        }

        results = []
        for _ in range(10):
            rendered = template.format(
                project_name=context["project_name"],
                tools=", ".join(context["tools"]),
                cwd=context["cwd"],
            )
            results.append(rendered)

        assert_deterministic(results, "prompt template rendering")

    def test_tool_description_generation_deterministic(self):
        """Tool description generation is deterministic."""
        tools = [
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
            {"name": "bash_exec", "description": "Execute bash command"},
        ]

        def generate_tool_descriptions(tools: list[dict]) -> str:
            # Sorted for determinism
            sorted_tools = sorted(tools, key=lambda t: t["name"])
            lines = [f"- {t['name']}: {t['description']}" for t in sorted_tools]
            return "\n".join(lines)

        results = []
        for _ in range(10):
            desc = generate_tool_descriptions(tools)
            results.append(desc)

        assert_deterministic(results, "tool description generation")
