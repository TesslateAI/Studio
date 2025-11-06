"""
Integration tests for IterativeAgent.

Tests the complete iterative agent workflow including:
- Tool execution
- Multi-iteration scenarios
- Error handling
- Completion detection
"""

import pytest
from unittest.mock import AsyncMock, Mock
from app.agent.iterative_agent import IterativeAgent
from app.agent.tools.registry import ToolRegistry, Tool, ToolCategory
from app.agent.models import ModelAdapter


@pytest.mark.integration
class TestIterativeAgentIntegration:
    """Integration tests for IterativeAgent."""

    @pytest.fixture
    def simple_tool_registry(self):
        """Create a simple tool registry for testing."""
        registry = ToolRegistry()

        async def echo_tool(params, context):
            return {
                "message": f"Echo: {params.get('text', '')}",
                "echoed_text": params.get('text', '')
            }

        registry.register(Tool(
            name="echo",
            description="Echo text back",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to echo"}
                },
                "required": ["text"]
            },
            executor=echo_tool,
            category=ToolCategory.FILE_OPS
        ))

        return registry

    @pytest.fixture
    def mock_model_with_tool_call(self):
        """Create a mock model that returns a tool call."""
        class MockModelWithToolCall(ModelAdapter):
            def __init__(self):
                self.responses = [
                    """
THOUGHT: I'll echo the user's message.

<tool_call>
<tool_name>echo</tool_name>
<parameters>
{"text": "Hello World"}
</parameters>
</tool_call>
""",
                    """
THOUGHT: Task is complete.

TASK_COMPLETE
"""
                ]
                self.call_count = 0

            async def chat(self, messages, **kwargs):
                response = self.responses[min(self.call_count, len(self.responses) - 1)]
                self.call_count += 1
                for char in response:
                    yield char

            def get_model_name(self):
                return "mock-model"

        return MockModelWithToolCall()

    @pytest.mark.asyncio
    async def test_iterative_agent_single_iteration(
        self,
        simple_tool_registry,
        mock_model_with_tool_call,
        test_context
    ):
        """Test agent completing task in single iteration."""
        agent = IterativeAgent(
            system_prompt="You are a helpful assistant.",
            tools=simple_tool_registry,
            model=mock_model_with_tool_call,
            max_iterations=5
        )

        events = []
        async for event in agent.run("Echo hello", test_context):
            events.append(event)

        # Should have agent_step events and a complete event
        assert len(events) > 0

        # Find complete event
        complete_events = [e for e in events if e['type'] == 'complete']
        assert len(complete_events) == 1

        complete_event = complete_events[0]
        assert complete_event['data']['success'] is True
        assert complete_event['data']['iterations'] <= 5

    @pytest.mark.asyncio
    async def test_iterative_agent_tool_execution(
        self,
        simple_tool_registry,
        test_context
    ):
        """Test that tools are actually executed."""
        # Model that calls echo tool
        class ToolCallingModel(ModelAdapter):
            async def chat(self, messages, **kwargs):
                if len(messages) <= 2:
                    response = """
THOUGHT: I'll use the echo tool.

<tool_call>
<tool_name>echo</tool_name>
<parameters>
{"text": "Test message"}
</parameters>
</tool_call>
"""
                else:
                    response = "TASK_COMPLETE"

                for char in response:
                    yield char

            def get_model_name(self):
                return "tool-calling-model"

        agent = IterativeAgent(
            system_prompt="Test agent",
            tools=simple_tool_registry,
            model=ToolCallingModel(),
            max_iterations=3
        )

        events = []
        async for event in agent.run("Test request", test_context):
            events.append(event)

        # Find agent_step events with tool calls
        step_events = [e for e in events if e['type'] == 'agent_step']
        assert len(step_events) > 0

        # Check that tool was executed
        tool_executed = False
        for event in step_events:
            if event['data']['tool_calls']:
                assert event['data']['tool_calls'][0]['name'] == 'echo'
                tool_executed = True
                break

        assert tool_executed

    @pytest.mark.asyncio
    async def test_iterative_agent_max_iterations(
        self,
        simple_tool_registry,
        test_context
    ):
        """Test agent reaching max iterations."""
        # Model that never completes
        class NeverCompleteModel(ModelAdapter):
            async def chat(self, messages, **kwargs):
                response = """
THOUGHT: Still working...

<tool_call>
<tool_name>echo</tool_name>
<parameters>
{"text": "Iteration"}
</parameters>
</tool_call>
"""
                for char in response:
                    yield char

            def get_model_name(self):
                return "never-complete"

        agent = IterativeAgent(
            system_prompt="Test agent",
            tools=simple_tool_registry,
            model=NeverCompleteModel(),
            max_iterations=3
        )

        events = []
        async for event in agent.run("Test request", test_context):
            events.append(event)

        # Find complete event
        complete_events = [e for e in events if e['type'] == 'complete']
        assert len(complete_events) == 1

        # Should indicate max iterations reached
        complete_data = complete_events[0]['data']
        assert complete_data['iterations'] == 3
        assert complete_data['completion_reason'] == 'max_iterations'

    @pytest.mark.asyncio
    async def test_iterative_agent_no_tools(self, test_context):
        """Test agent with no tools (conversational only)."""
        class ConversationalModel(ModelAdapter):
            async def chat(self, messages, **kwargs):
                response = "This is a conversational response with no tool calls."
                for char in response:
                    yield char

            def get_model_name(self):
                return "conversational"

        agent = IterativeAgent(
            system_prompt="Conversational agent",
            tools=None,
            model=ConversationalModel(),
            max_iterations=3
        )

        events = []
        async for event in agent.run("Hello", test_context):
            events.append(event)

        # Should complete without tool calls
        complete_events = [e for e in events if e['type'] == 'complete']
        assert len(complete_events) == 1
        assert complete_events[0]['data']['tool_calls_made'] == 0

    @pytest.mark.asyncio
    async def test_iterative_agent_error_handling(
        self,
        test_context
    ):
        """Test agent handling tool execution errors."""
        registry = ToolRegistry()

        async def failing_tool(params, context):
            raise RuntimeError("Tool execution failed")

        registry.register(Tool(
            name="failing_tool",
            description="A tool that fails",
            parameters={"type": "object", "properties": {}},
            executor=failing_tool,
            category=ToolCategory.FILE_OPS
        ))

        class FailingToolModel(ModelAdapter):
            def __init__(self):
                self.call_count = 0

            async def chat(self, messages, **kwargs):
                if self.call_count == 0:
                    self.call_count += 1
                    response = """
<tool_call>
<tool_name>failing_tool</tool_name>
<parameters>
{}
</parameters>
</tool_call>
"""
                else:
                    response = "TASK_COMPLETE"

                for char in response:
                    yield char

            def get_model_name(self):
                return "failing-tool-model"

        agent = IterativeAgent(
            system_prompt="Test agent",
            tools=registry,
            model=FailingToolModel(),
            max_iterations=3
        )

        events = []
        async for event in agent.run("Test", test_context):
            events.append(event)

        # Should handle the error gracefully
        step_events = [e for e in events if e['type'] == 'agent_step']
        assert len(step_events) > 0

        # Check that tool result shows failure
        for event in step_events:
            if event['data']['tool_results']:
                assert event['data']['tool_results'][0]['success'] is False

    @pytest.mark.asyncio
    async def test_iterative_agent_multiple_tools_in_sequence(
        self,
        test_context
    ):
        """Test agent calling multiple tools in sequence."""
        registry = ToolRegistry()

        async def tool1(params, context):
            return {"message": "Tool 1 executed"}

        async def tool2(params, context):
            return {"message": "Tool 2 executed"}

        registry.register(Tool(
            name="tool1",
            description="First tool",
            parameters={"type": "object", "properties": {}},
            executor=tool1,
            category=ToolCategory.FILE_OPS
        ))

        registry.register(Tool(
            name="tool2",
            description="Second tool",
            parameters={"type": "object", "properties": {}},
            executor=tool2,
            category=ToolCategory.FILE_OPS
        ))

        class MultiToolModel(ModelAdapter):
            def __init__(self):
                self.responses = [
                    '<tool_call><tool_name>tool1</tool_name><parameters>{}</parameters></tool_call>',
                    '<tool_call><tool_name>tool2</tool_name><parameters>{}</parameters></tool_call>',
                    'TASK_COMPLETE'
                ]
                self.call_count = 0

            async def chat(self, messages, **kwargs):
                response = self.responses[min(self.call_count, len(self.responses) - 1)]
                self.call_count += 1
                for char in response:
                    yield char

            def get_model_name(self):
                return "multi-tool"

        agent = IterativeAgent(
            system_prompt="Test agent",
            tools=registry,
            model=MultiToolModel(),
            max_iterations=5
        )

        events = []
        async for event in agent.run("Test", test_context):
            events.append(event)

        # Should have multiple iterations
        step_events = [e for e in events if e['type'] == 'agent_step']
        assert len(step_events) >= 2

        # Check tools were executed
        assert step_events[0]['data']['tool_calls'][0]['name'] == 'tool1'
        assert step_events[1]['data']['tool_calls'][0]['name'] == 'tool2'

    @pytest.mark.asyncio
    async def test_iterative_agent_json_parse_error(
        self,
        simple_tool_registry,
        test_context
    ):
        """Test agent handling JSON parse errors in tool calls."""
        class BadJsonModel(ModelAdapter):
            def __init__(self):
                self.call_count = 0

            async def chat(self, messages, **kwargs):
                if self.call_count == 0:
                    self.call_count += 1
                    # Invalid JSON - missing quotes around value
                    response = """
<tool_call>
<tool_name>echo</tool_name>
<parameters>
{"text": broken json}
</parameters>
</tool_call>
"""
                else:
                    response = "TASK_COMPLETE"

                for char in response:
                    yield char

            def get_model_name(self):
                return "bad-json"

        agent = IterativeAgent(
            system_prompt="Test agent",
            tools=simple_tool_registry,
            model=BadJsonModel(),
            max_iterations=3
        )

        events = []
        async for event in agent.run("Test", test_context):
            events.append(event)

        # Should handle parse error
        step_events = [e for e in events if e['type'] == 'agent_step']
        assert len(step_events) > 0

        # Check for parse error tool call
        first_step = step_events[0]
        if first_step['data']['tool_calls']:
            assert first_step['data']['tool_calls'][0]['name'] == '__parse_error__'

    def test_agent_get_execution_summary(self, simple_tool_registry, mock_model_with_tool_call):
        """Test getting execution summary from agent."""
        agent = IterativeAgent(
            system_prompt="Test",
            tools=simple_tool_registry,
            model=mock_model_with_tool_call,
            max_iterations=5
        )

        # Agent should have initial state
        summary = agent.get_execution_summary()
        assert summary['total_steps'] == 0
        assert summary['tool_calls_made'] == 0

    def test_agent_get_conversation_history(self, simple_tool_registry, mock_model_with_tool_call):
        """Test getting conversation history from agent."""
        agent = IterativeAgent(
            system_prompt="Test",
            tools=simple_tool_registry,
            model=mock_model_with_tool_call,
            max_iterations=5
        )

        # Initially empty
        history = agent.get_conversation_history()
        assert len(history) == 0
