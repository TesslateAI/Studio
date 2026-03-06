"""
Real LLM Agent Tests.

These tests use the actual LLM model via OpenAI-compatible API
to test agent behavior with real model outputs.

Usage:
    # Run all LLM tests (requires API access)
    pytest tests/agent/llm/test_real_llm_agent.py -v -m llm

    # Run with timeout protection
    pytest tests/agent/llm/test_real_llm_agent.py -v -m llm --timeout=120

Requirements:
    - OPENAI_API_BASE and OPENAI_API_KEY environment variables set
    - Access to the configured model (OPENAI_MODEL)

Notes:
    - These tests are slower than mocked tests (real API calls)
    - May incur API costs
    - Results may vary slightly between runs due to model non-determinism
"""

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dotenv import load_dotenv

# Load .env file
load_dotenv()

logger = logging.getLogger(__name__)

# Model configuration - use a valid model from the API
# Available models: gpt-5, gpt-4.1, llama-3.3-70b, qwen-3-235b-a22b-instruct-2507, etc.
LLM_MODEL = os.environ.get("LLM_TEST_MODEL", "llama-3.3-70b")


def skip_if_no_llm():
    """Skip test if LLM API is not configured."""
    api_base = os.environ.get("OPENAI_API_BASE")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_base or not api_key:
        pytest.skip("OPENAI_API_BASE or OPENAI_API_KEY not configured")


# ============================================================================
# LLM Connection Tests
# ============================================================================


@pytest.mark.llm
@pytest.mark.slow
class TestLLMConnection:
    """Tests for LLM connectivity and basic functionality."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_litellm_connection(self):
        """Test that we can connect to LLM API."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        api_base = os.environ.get("OPENAI_API_BASE")
        api_key = os.environ.get("OPENAI_API_KEY")

        client = AsyncOpenAI(base_url=api_base, api_key=api_key)

        try:
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": "Say 'hello' and nothing else."}],
                max_tokens=10,
                temperature=0,
            )

            assert response.choices[0].message.content is not None
            assert len(response.choices[0].message.content) > 0
            logger.info(
                f"LLM Connection test passed. Response: {response.choices[0].message.content}"
            )

        except Exception as e:
            pytest.fail(f"Failed to connect to LLM API: {e}")

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_model_availability(self):
        """Test that configured model is available."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        api_base = os.environ.get("OPENAI_API_BASE")
        api_key = os.environ.get("OPENAI_API_KEY")

        client = AsyncOpenAI(base_url=api_base, api_key=api_key)

        try:
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": "What is 2+2? Answer with just the number."}],
                max_tokens=5,
                temperature=0,
            )

            content = response.choices[0].message.content.strip()
            assert "4" in content, f"Expected '4' in response, got: {content}"

        except Exception as e:
            pytest.fail(f"Llama-4-Maverick model not available: {e}")


# ============================================================================
# Parser with Real LLM Tests
# ============================================================================


@pytest.mark.llm
@pytest.mark.slow
class TestParserWithRealLLM:
    """Test parser can handle real LLM outputs."""

    @pytest.fixture
    def parser(self):
        from app.agent.parser import AgentResponseParser

        return AgentResponseParser()

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_parse_tool_call_from_real_llm(self, parser):
        """Test parser can extract tool calls from real LLM output."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        api_base = os.environ.get("OPENAI_API_BASE")
        api_key = os.environ.get("OPENAI_API_KEY")

        client = AsyncOpenAI(base_url=api_base, api_key=api_key)

        # Prompt that should result in a tool call
        prompt = """You are an AI coding assistant. When you need to read a file, output a JSON tool call in this exact format:
{"tool_name": "read_file", "parameters": {"file_path": "the_file_path"}}

The user wants you to read the file "src/App.jsx". Output ONLY the JSON tool call, nothing else."""

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,
        )

        llm_output = response.choices[0].message.content
        logger.info(f"LLM output: {llm_output}")

        # Parse the output
        tool_calls = parser.parse(llm_output)

        assert len(tool_calls) >= 1, (
            f"Expected at least 1 tool call, got {len(tool_calls)} from: {llm_output}"
        )

        # Verify tool call structure
        found_read_file = False
        for tc in tool_calls:
            if tc.name == "read_file":
                found_read_file = True
                assert "file_path" in tc.parameters
                assert "App.jsx" in tc.parameters["file_path"]
                break

        assert found_read_file, f"Expected read_file tool call in: {tool_calls}"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_parse_completion_signal_from_real_llm(self, parser):
        """Test parser can detect completion signal from real LLM output."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        api_base = os.environ.get("OPENAI_API_BASE")
        api_key = os.environ.get("OPENAI_API_KEY")

        client = AsyncOpenAI(base_url=api_base, api_key=api_key)

        prompt = """You are an AI coding assistant. When you complete a task, output "TASK_COMPLETE" on its own line.

The task is complete. Please signal completion."""

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0,
        )

        llm_output = response.choices[0].message.content
        logger.info(f"LLM completion output: {llm_output}")

        # Check completion detection
        is_complete = parser.is_complete(llm_output)
        assert is_complete, f"Expected completion signal in: {llm_output}"


# ============================================================================
# Model Adapter Tests
# ============================================================================


@pytest.mark.llm
@pytest.mark.slow
class TestModelAdapterWithRealLLM:
    """Test OpenAIAdapter with real LLM."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_model_adapter_generate(self):
        """Test OpenAIAdapter.chat() with real LLM."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        from app.agent.models import OpenAIAdapter

        client = AsyncOpenAI(
            base_url=os.environ.get("OPENAI_API_BASE"), api_key=os.environ.get("OPENAI_API_KEY")
        )

        adapter = OpenAIAdapter(model_name=LLM_MODEL, client=client, temperature=0)

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is the capital of France? Answer in one word."},
        ]

        # Collect streaming response
        response = ""
        async for chunk in adapter.chat(messages):
            response += chunk

        assert response is not None
        assert "Paris" in response or "paris" in response.lower(), (
            f"Expected 'Paris' in response, got: {response}"
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_model_adapter_with_system_prompt(self):
        """Test OpenAIAdapter respects system prompt."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        from app.agent.models import OpenAIAdapter

        client = AsyncOpenAI(
            base_url=os.environ.get("OPENAI_API_BASE"), api_key=os.environ.get("OPENAI_API_KEY")
        )

        adapter = OpenAIAdapter(model_name=LLM_MODEL, client=client, temperature=0)

        system_prompt = """You are a pirate assistant. You always start your response with "Arrr!"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Hello"},
        ]

        # Collect streaming response
        response = ""
        async for chunk in adapter.chat(messages):
            response += chunk

        assert response is not None
        assert "arr" in response.lower(), f"Expected pirate response, got: {response}"


# ============================================================================
# Agent Tool Calling Tests
# ============================================================================


@pytest.mark.llm
@pytest.mark.slow
class TestAgentToolCallingWithRealLLM:
    """Test agent tool calling with real LLM."""

    @pytest.fixture
    def mock_tool_context(self, test_context, tmp_path):
        """Create a context with mock tool execution."""
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True)

        # Create a sample file
        (project_dir / "App.jsx").write_text("""
function App() {
  return <div>Hello World</div>;
}
export default App;
""")

        context = test_context.copy()
        context["project_path"] = str(project_dir)
        return context

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)
    async def test_iterative_agent_single_tool_call(self, mock_tool_context, tmp_path):
        """Test IterativeAgent can make a tool call with real LLM."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        from app.agent.iterative_agent import IterativeAgent
        from app.agent.models import OpenAIAdapter
        from app.agent.tools.registry import ToolRegistry

        project_dir = tmp_path / "project_files"
        project_dir.mkdir(parents=True)
        (project_dir / "App.jsx").write_text("function App() { return <div>Hello</div>; }")

        # Create in-memory file storage
        file_content = {"App.jsx": "function App() { return <div>Hello</div>; }"}

        # Mock orchestrator
        async def mock_read_file(user_id, project_id, container_name, file_path, **kwargs):
            return file_content.get(file_path, "")

        async def mock_list_directory(user_id, project_id, container_name, dir_path=".", **kwargs):
            return [{"name": "App.jsx", "type": "file"}]

        mock_orchestrator = MagicMock()
        mock_orchestrator.read_file = AsyncMock(side_effect=mock_read_file)
        mock_orchestrator.list_directory = AsyncMock(side_effect=mock_list_directory)

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            # Create agent with real model
            client = AsyncOpenAI(
                base_url=os.environ.get("OPENAI_API_BASE"), api_key=os.environ.get("OPENAI_API_KEY")
            )

            adapter = OpenAIAdapter(model_name=LLM_MODEL, client=client, temperature=0)

            system_prompt = """You are a coding assistant. You have access to tools.

When you need to read a file, output:
{"tool_name": "read_file", "parameters": {"file_path": "path/to/file"}}

When you are done, output: TASK_COMPLETE

Always output ONLY the JSON tool call or TASK_COMPLETE, nothing else."""

            tools = ToolRegistry()

            agent = IterativeAgent(system_prompt=system_prompt, tools=tools, model=adapter)

            # Run agent with a simple request
            request = "Read the file App.jsx"

            events = []
            async for event in agent.run(request, mock_tool_context):
                events.append(event)
                logger.info(f"Agent event: {event}")

                # Limit iterations for safety
                if len(events) > 20:
                    break

            # Should have at least attempted to call a tool
            tool_call_events = [e for e in events if e.get("type") == "tool_call"]
            assert len(tool_call_events) >= 1 or any("TASK_COMPLETE" in str(e) for e in events), (
                f"Expected tool call or completion, got events: {events}"
            )


# ============================================================================
# Determinism Tests with Real LLM
# ============================================================================


@pytest.mark.llm
@pytest.mark.slow
class TestLLMDeterminism:
    """Test LLM output determinism with temperature=0."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)
    async def test_deterministic_simple_response(self):
        """Test that temperature=0 produces consistent responses."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        api_base = os.environ.get("OPENAI_API_BASE")
        api_key = os.environ.get("OPENAI_API_KEY")

        client = AsyncOpenAI(base_url=api_base, api_key=api_key)

        prompt = "What is the chemical symbol for water? Answer with just the symbol."

        responses = []
        for _ in range(3):
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0,
                # Note: seed parameter may not be supported by all providers
            )
            responses.append(response.choices[0].message.content.strip())

        # All responses should be identical with temperature=0
        assert len(set(responses)) == 1, (
            f"Expected identical responses with temperature=0, got: {responses}"
        )
        # Allow unicode subscript (H₂O) or ASCII (H2O)
        response_normalized = responses[0].replace("₂", "2").lower()
        assert "h2o" in response_normalized, f"Expected H2O in response, got: {responses[0]}"

    @pytest.mark.asyncio
    @pytest.mark.timeout(180)
    async def test_deterministic_tool_call_format(self):
        """Test that tool call format is consistent."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        from app.agent.parser import AgentResponseParser

        api_base = os.environ.get("OPENAI_API_BASE")
        api_key = os.environ.get("OPENAI_API_KEY")

        client = AsyncOpenAI(base_url=api_base, api_key=api_key)
        parser = AgentResponseParser()

        prompt = """Output exactly this JSON and nothing else:
{"tool_name": "read_file", "parameters": {"file_path": "test.js"}}"""

        responses = []
        parsed_calls = []

        for _ in range(3):
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0,
            )
            content = response.choices[0].message.content
            responses.append(content)

            tool_calls = parser.parse(content)
            if tool_calls:
                parsed_calls.append(
                    {"name": tool_calls[0].name, "params": tool_calls[0].parameters}
                )

        # Should produce consistent parseable output
        assert len(parsed_calls) >= 1, f"Expected parseable tool calls from: {responses}"

        # All parsed calls should have same structure
        if len(parsed_calls) > 1:
            first = parsed_calls[0]
            for call in parsed_calls[1:]:
                assert call["name"] == first["name"], (
                    f"Tool names differ: {first['name']} vs {call['name']}"
                )


# ============================================================================
# Agent Response Quality Tests
# ============================================================================


@pytest.mark.llm
@pytest.mark.slow
class TestAgentResponseQuality:
    """Test quality of agent responses with real LLM."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_code_generation_quality(self):
        """Test that LLM generates valid code."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        api_base = os.environ.get("OPENAI_API_BASE")
        api_key = os.environ.get("OPENAI_API_KEY")

        client = AsyncOpenAI(base_url=api_base, api_key=api_key)

        prompt = """Write a JavaScript function called 'add' that takes two numbers and returns their sum.
Output only the function code, nothing else."""

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0,
        )

        code = response.choices[0].message.content

        # Verify it looks like valid code
        assert "function" in code or "const add" in code or "let add" in code, (
            f"Expected function definition, got: {code}"
        )
        assert "return" in code, f"Expected return statement, got: {code}"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_task_understanding(self):
        """Test that LLM understands complex tasks."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        api_base = os.environ.get("OPENAI_API_BASE")
        api_key = os.environ.get("OPENAI_API_KEY")

        client = AsyncOpenAI(base_url=api_base, api_key=api_key)

        prompt = """As a coding assistant, analyze this task and list the steps needed:
"Add a dark mode toggle to a React application"

List 3-5 concrete steps. Be brief."""

        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0,
        )

        response_text = response.choices[0].message.content.lower()

        # Should mention relevant concepts
        assert any(
            kw in response_text for kw in ["state", "context", "toggle", "theme", "css", "style"]
        ), f"Expected relevant dark mode concepts in: {response_text}"


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.llm
@pytest.mark.slow
class TestLLMErrorHandling:
    """Test error handling with real LLM."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_invalid_model_name(self):
        """Test handling of invalid model name."""
        from openai import AsyncOpenAI

        api_base = os.environ.get("OPENAI_API_BASE")
        api_key = os.environ.get("OPENAI_API_KEY")

        if not api_base:
            pytest.skip("OPENAI_API_BASE not configured")

        client = AsyncOpenAI(base_url=api_base, api_key=api_key)

        with pytest.raises((Exception, ValueError)):  # noqa: B017
            await client.chat.completions.create(
                model="nonexistent-model-12345",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=10,
            )

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_empty_messages_handling(self):
        """Test handling of empty messages."""
        from openai import AsyncOpenAI

        from app.agent.models import OpenAIAdapter

        api_base = os.environ.get("OPENAI_API_BASE")
        if not api_base:
            pytest.skip("OPENAI_API_BASE not configured")

        client = AsyncOpenAI(base_url=api_base, api_key=os.environ.get("OPENAI_API_KEY"))

        adapter = OpenAIAdapter(model_name=LLM_MODEL, client=client, temperature=0)

        # Should handle empty messages gracefully - expect an error
        with pytest.raises((Exception, ValueError)):  # noqa: B017
            response = ""
            async for chunk in adapter.chat([]):
                response += chunk


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.llm
@pytest.mark.slow
@pytest.mark.integration
class TestLLMIntegration:
    """Integration tests with real LLM and full agent stack."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(180)
    async def test_simple_file_read_workflow(self, test_context, tmp_path):
        """Test complete workflow: user request -> tool call -> response."""
        skip_if_no_llm()

        from openai import AsyncOpenAI

        from app.agent.iterative_agent import IterativeAgent
        from app.agent.models import OpenAIAdapter
        from app.agent.tools.registry import ToolRegistry

        # Setup test file
        project_dir = tmp_path / "project_files"
        project_dir.mkdir(parents=True)

        test_content = "console.log('Hello World');"
        (project_dir / "test.js").write_text(test_content)

        # Create in-memory file storage
        file_content = {"test.js": test_content}

        # Mock orchestrator
        async def mock_read_file(user_id, project_id, container_name, file_path, **kwargs):
            return file_content.get(file_path, "")

        async def mock_list_directory(user_id, project_id, container_name, dir_path=".", **kwargs):
            return [{"name": "test.js", "type": "file"}]

        mock_orchestrator = MagicMock()
        mock_orchestrator.read_file = AsyncMock(side_effect=mock_read_file)
        mock_orchestrator.list_directory = AsyncMock(side_effect=mock_list_directory)

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            # Create agent
            client = AsyncOpenAI(
                base_url=os.environ.get("OPENAI_API_BASE"), api_key=os.environ.get("OPENAI_API_KEY")
            )

            adapter = OpenAIAdapter(model_name=LLM_MODEL, client=client, temperature=0)

            system_prompt = """You are a coding assistant with these tools:

1. read_file - Read a file's contents
   Format: {"tool_name": "read_file", "parameters": {"file_path": "path"}}

2. When done, output: TASK_COMPLETE

Always start by reading the requested file."""

            tools = ToolRegistry()
            agent = IterativeAgent(system_prompt=system_prompt, tools=tools, model=adapter)

            # Run workflow
            events = []
            async for event in agent.run("Read test.js and tell me what it does", test_context):
                events.append(event)
                if len(events) > 30:  # Safety limit
                    break

            # Should have some events
            assert len(events) > 0, "Expected at least one event"

            # Check if we got tool calls or completion
            has_tool_call = any(e.get("type") == "tool_call" for e in events)
            has_result = any(e.get("type") in ["tool_result", "complete"] for e in events)

            assert has_tool_call or has_result, (
                f"Expected tool_call or result events, got: {[e.get('type') for e in events]}"
            )
