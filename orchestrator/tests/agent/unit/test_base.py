"""
Unit tests for AbstractAgent base class.

Tests the abstract interface that all agents must implement.
"""

import pytest
from app.agent.base import AbstractAgent
from app.agent.tools.registry import ToolRegistry


@pytest.mark.unit
class TestAbstractAgent:
    """Test suite for AbstractAgent."""

    def test_abstract_agent_cannot_be_instantiated(self):
        """Test that AbstractAgent cannot be instantiated directly."""
        with pytest.raises(TypeError) as exc_info:
            AbstractAgent("Test prompt")

        assert "Can't instantiate abstract class" in str(exc_info.value)

    def test_concrete_agent_must_implement_run(self):
        """Test that concrete agents must implement the run method."""
        class IncompleteAgent(AbstractAgent):
            pass

        with pytest.raises(TypeError) as exc_info:
            IncompleteAgent("Test prompt")

        assert "Can't instantiate abstract class" in str(exc_info.value)

    def test_concrete_agent_can_be_instantiated(self):
        """Test that a concrete agent with run() can be instantiated."""
        class ConcreteAgent(AbstractAgent):
            async def run(self, user_request, context):
                yield {'type': 'complete', 'data': {}}

        agent = ConcreteAgent("Test prompt")
        assert agent.system_prompt == "Test prompt"
        assert agent.tools is None

    def test_agent_with_tools(self):
        """Test that agent can be initialized with tools."""
        class ConcreteAgent(AbstractAgent):
            async def run(self, user_request, context):
                yield {'type': 'complete', 'data': {}}

        tools = ToolRegistry()
        agent = ConcreteAgent("Test prompt", tools=tools)

        assert agent.system_prompt == "Test prompt"
        assert agent.tools is tools

    @pytest.mark.asyncio
    async def test_agent_run_yields_events(self):
        """Test that agent run method can yield events."""
        class TestAgent(AbstractAgent):
            async def run(self, user_request, context):
                yield {'type': 'status', 'content': 'Starting'}
                yield {'type': 'stream', 'content': 'Processing'}
                yield {'type': 'complete', 'data': {'result': 'success'}}

        agent = TestAgent("Test prompt")
        events = []

        async for event in agent.run("Test request", {}):
            events.append(event)

        assert len(events) == 3
        assert events[0]['type'] == 'status'
        assert events[1]['type'] == 'stream'
        assert events[2]['type'] == 'complete'

    @pytest.mark.asyncio
    async def test_agent_receives_context(self):
        """Test that agent receives execution context."""
        class ContextAgent(AbstractAgent):
            async def run(self, user_request, context):
                yield {
                    'type': 'complete',
                    'data': {
                        'user_request': user_request,
                        'user_id': context.get('user_id'),
                        'project_id': context.get('project_id')
                    }
                }

        agent = ContextAgent("Test prompt")
        context = {
            'user_id': 'user123',
            'project_id': 'project456'
        }

        events = []
        async for event in agent.run("Test request", context):
            events.append(event)

        assert len(events) == 1
        assert events[0]['data']['user_request'] == "Test request"
        assert events[0]['data']['user_id'] == 'user123'
        assert events[0]['data']['project_id'] == 'project456'

    def test_agent_system_prompt_storage(self):
        """Test that system prompt is stored correctly."""
        class SimpleAgent(AbstractAgent):
            async def run(self, user_request, context):
                yield {}

        long_prompt = "A" * 10000
        agent = SimpleAgent(long_prompt)

        assert agent.system_prompt == long_prompt
        assert len(agent.system_prompt) == 10000

    def test_agent_initialization_parameters(self):
        """Test various initialization parameter combinations."""
        class SimpleAgent(AbstractAgent):
            async def run(self, user_request, context):
                yield {}

        # With just system prompt
        agent1 = SimpleAgent("Prompt")
        assert agent1.system_prompt == "Prompt"
        assert agent1.tools is None

        # With system prompt and tools
        tools = ToolRegistry()
        agent2 = SimpleAgent("Prompt", tools=tools)
        assert agent2.system_prompt == "Prompt"
        assert agent2.tools is tools

        # With empty prompt
        agent3 = SimpleAgent("")
        assert agent3.system_prompt == ""
