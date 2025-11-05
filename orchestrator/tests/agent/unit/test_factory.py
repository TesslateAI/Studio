"""
Unit tests for Agent Factory.

Tests agent creation, registration, and factory functions.
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from app.agent.factory import (
    create_agent_from_db_model,
    register_agent_type,
    get_available_agent_types,
    get_agent_class,
    AGENT_CLASS_MAP
)
from app.agent.base import AbstractAgent
from app.agent.stream_agent import StreamAgent
from app.agent.iterative_agent import IterativeAgent


@pytest.mark.unit
class TestAgentFactory:
    """Test suite for agent factory functions."""

    @pytest.fixture
    def mock_agent_model(self):
        """Create a mock MarketplaceAgent model."""
        model = Mock()
        model.name = "Test Agent"
        model.slug = "test-agent"
        model.agent_type = "StreamAgent"
        model.system_prompt = "You are a helpful assistant."
        model.tools = None
        return model

    @pytest.fixture
    def mock_agent_model_with_tools(self):
        """Create a mock MarketplaceAgent with tools."""
        model = Mock()
        model.name = "Tool Agent"
        model.slug = "tool-agent"
        model.agent_type = "IterativeAgent"
        model.system_prompt = "You are a tool-using assistant."
        model.tools = ["read_file", "write_file", "bash_exec"]
        return model

    @pytest.mark.asyncio
    async def test_create_stream_agent_from_model(self, mock_agent_model):
        """Test creating a StreamAgent from database model."""
        agent = await create_agent_from_db_model(mock_agent_model)

        assert isinstance(agent, StreamAgent)
        assert agent.system_prompt == "You are a helpful assistant."

    @pytest.mark.asyncio
    async def test_create_iterative_agent_from_model(self, mock_agent_model_with_tools, mock_model_adapter):
        """Test creating an IterativeAgent from database model."""
        model_adapter_instance = mock_model_adapter()
        mock_agent_model_with_tools.agent_type = "IterativeAgent"

        agent = await create_agent_from_db_model(
            mock_agent_model_with_tools,
            model_adapter=model_adapter_instance
        )

        assert isinstance(agent, IterativeAgent)
        assert agent.system_prompt == "You are a tool-using assistant."
        assert agent.tools is not None

    @pytest.mark.asyncio
    async def test_create_agent_with_invalid_type(self, mock_agent_model):
        """Test that invalid agent type raises ValueError."""
        mock_agent_model.agent_type = "NonExistentAgent"

        with pytest.raises(ValueError) as exc_info:
            await create_agent_from_db_model(mock_agent_model)

        assert "Unknown agent type" in str(exc_info.value)
        assert "NonExistentAgent" in str(exc_info.value)
        assert "Available types" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_agent_without_system_prompt(self, mock_agent_model):
        """Test that missing system prompt raises ValueError."""
        mock_agent_model.system_prompt = ""

        with pytest.raises(ValueError) as exc_info:
            await create_agent_from_db_model(mock_agent_model)

        assert "does not have a system prompt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_agent_with_whitespace_only_prompt(self, mock_agent_model):
        """Test that whitespace-only prompt raises ValueError."""
        mock_agent_model.system_prompt = "   \n  \t  "

        with pytest.raises(ValueError) as exc_info:
            await create_agent_from_db_model(mock_agent_model)

        assert "does not have a system prompt" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_agent_with_scoped_tools(self, mock_agent_model_with_tools, monkeypatch):
        """Test that agent is created with scoped tool registry."""
        from app.agent.tools import registry as registry_module
        from app.agent.tools.registry import ToolRegistry, Tool, ToolCategory

        # Create a mock global registry
        global_registry = ToolRegistry()

        async def mock_executor(params, context):
            return {"success": True}

        for tool_name in ["read_file", "write_file", "bash_exec"]:
            global_registry.register(Tool(
                name=tool_name,
                description=f"Mock {tool_name}",
                parameters={},
                executor=mock_executor,
                category=ToolCategory.FILE_OPS
            ))

        monkeypatch.setattr(registry_module, "get_tool_registry", lambda: global_registry)

        agent = await create_agent_from_db_model(
            mock_agent_model_with_tools,
            model_adapter=Mock()
        )

        assert agent.tools is not None
        assert len(agent.tools._tools) == 3

    def test_register_new_agent_type(self):
        """Test registering a new agent type."""
        class CustomAgent(AbstractAgent):
            async def run(self, user_request, context):
                yield {'type': 'complete', 'data': {}}

        # Store original state
        original_types = get_available_agent_types().copy()

        try:
            register_agent_type("CustomAgent", CustomAgent)

            available = get_available_agent_types()
            assert "CustomAgent" in available

            agent_class = get_agent_class("CustomAgent")
            assert agent_class is CustomAgent
        finally:
            # Cleanup: Remove custom agent
            if "CustomAgent" in AGENT_CLASS_MAP:
                del AGENT_CLASS_MAP["CustomAgent"]

    def test_register_overwrites_existing_type(self):
        """Test that registering same type overwrites previous."""
        class CustomAgent1(AbstractAgent):
            async def run(self, user_request, context):
                yield {'type': 'complete', 'data': {'version': 1}}

        class CustomAgent2(AbstractAgent):
            async def run(self, user_request, context):
                yield {'type': 'complete', 'data': {'version': 2}}

        try:
            register_agent_type("CustomAgent", CustomAgent1)
            assert get_agent_class("CustomAgent") is CustomAgent1

            register_agent_type("CustomAgent", CustomAgent2)
            assert get_agent_class("CustomAgent") is CustomAgent2
        finally:
            if "CustomAgent" in AGENT_CLASS_MAP:
                del AGENT_CLASS_MAP["CustomAgent"]

    def test_get_available_agent_types(self):
        """Test getting list of available agent types."""
        types = get_available_agent_types()

        assert isinstance(types, list)
        assert "StreamAgent" in types
        assert "IterativeAgent" in types
        assert len(types) >= 2

    def test_get_agent_class_existing(self):
        """Test getting an existing agent class."""
        stream_class = get_agent_class("StreamAgent")
        assert stream_class is StreamAgent

        iterative_class = get_agent_class("IterativeAgent")
        assert iterative_class is IterativeAgent

    def test_get_agent_class_nonexistent(self):
        """Test getting a nonexistent agent class returns None."""
        result = get_agent_class("NonExistentAgent")
        assert result is None

    @pytest.mark.asyncio
    async def test_factory_creates_stream_agent_correctly(self, mock_agent_model):
        """Test that factory creates StreamAgent with correct configuration."""
        mock_agent_model.agent_type = "StreamAgent"
        mock_agent_model.system_prompt = "Custom stream prompt"
        mock_agent_model.tools = ["read_file"]  # StreamAgent doesn't use tools

        agent = await create_agent_from_db_model(mock_agent_model)

        assert isinstance(agent, StreamAgent)
        assert agent.system_prompt == "Custom stream prompt"

    @pytest.mark.asyncio
    async def test_factory_creates_iterative_agent_with_global_registry(self, mock_agent_model):
        """Test that IterativeAgent uses global registry when no tools specified."""
        mock_agent_model.agent_type = "IterativeAgent"
        mock_agent_model.tools = None  # No specific tools

        agent = await create_agent_from_db_model(
            mock_agent_model,
            model_adapter=Mock()
        )

        assert isinstance(agent, IterativeAgent)
        assert agent.tools is not None  # Should have global registry

    @pytest.mark.asyncio
    async def test_factory_handles_empty_tools_list(self, mock_agent_model):
        """Test that empty tools list is treated as None (uses global registry)."""
        # Note: In Python, empty list [] is falsy, so `if agent_model.tools:` is False
        # This means empty list is treated the same as None and uses global registry

        mock_agent_model.agent_type = "IterativeAgent"
        mock_agent_model.tools = []  # Empty list is falsy

        agent = await create_agent_from_db_model(
            mock_agent_model,
            model_adapter=Mock()
        )

        assert isinstance(agent, IterativeAgent)
        assert agent.tools is not None
        # Empty list is falsy, so it should use global registry (which has tools)
        # The actual behavior is that [] is treated the same as None
        assert len(agent.tools._tools) > 0  # Has tools from global registry


@pytest.mark.unit
class TestAgentClassMap:
    """Test suite for AGENT_CLASS_MAP."""

    def test_agent_class_map_contains_default_types(self):
        """Test that AGENT_CLASS_MAP contains default agent types."""
        assert "StreamAgent" in AGENT_CLASS_MAP
        assert "IterativeAgent" in AGENT_CLASS_MAP
        assert AGENT_CLASS_MAP["StreamAgent"] is StreamAgent
        assert AGENT_CLASS_MAP["IterativeAgent"] is IterativeAgent

    def test_agent_class_map_is_dict(self):
        """Test that AGENT_CLASS_MAP is a dictionary."""
        assert isinstance(AGENT_CLASS_MAP, dict)

    def test_all_mapped_classes_inherit_from_abstract_agent(self):
        """Test that all mapped classes inherit from AbstractAgent."""
        for agent_type, agent_class in AGENT_CLASS_MAP.items():
            assert issubclass(agent_class, AbstractAgent), \
                f"{agent_type} does not inherit from AbstractAgent"
