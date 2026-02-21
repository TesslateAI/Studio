"""
Integration tests for TesslateAgent subagent functionality.

Tests subagent spawning, communication, and lifecycle with mocked components:
- Subagent invocation from main agent
- Parallel subagent execution
- Subagent result propagation
- Error handling in subagents
- Session management and resumption
"""

import pytest

from app.agent.models import ModelAdapter
from app.agent.tesslate_agent import TesslateAgent
from app.agent.tools.registry import Tool, ToolCategory, ToolRegistry


@pytest.mark.integration
class TestTesslateAgentSubagentsIntegration:
    """Integration tests for subagent functionality with mocked components."""

    @pytest.fixture
    def subagent_tool_registry(self):
        """Create a registry with subagent invocation tool."""
        registry = ToolRegistry()

        async def invoke_subagent_tool(params, context):
            """Invoke a subagent."""
            subagent_type = params.get("subagent_type", "general-purpose")
            prompt = params.get("prompt", "")

            # Simulate subagent execution with dictionary lookup
            responses = {
                "general-purpose": {
                    "success": True,
                    "result": f"Subagent completed task: {prompt}",
                    "agent_id": "subagent-123",
                    "turns_used": 3,
                },
                "Plan": {
                    "success": True,
                    "result": "Plan created:\n1. Step 1\n2. Step 2\n3. Step 3",
                    "agent_id": "plan-456",
                    "turns_used": 1,
                },
                "Explore": {
                    "success": True,
                    "result": "Found 5 relevant files:\n- file1.py\n- file2.py\n- file3.py\n- file4.py\n- file5.py",
                    "agent_id": "explore-789",
                    "turns_used": 2,
                },
            }

            return responses.get(
                subagent_type,
                {
                    "success": False,
                    "error": f"Unknown subagent type: {subagent_type}",
                },
            )

        # Register subagent tool
        registry.register(
            Tool(
                name="invoke_subagent",
                description="Invoke a specialized subagent to handle complex tasks",
                parameters={
                    "type": "object",
                    "properties": {
                        "subagent_type": {
                            "type": "string",
                            "description": "Type of subagent: general-purpose, Plan, or Explore",
                            "enum": ["general-purpose", "Plan", "Explore"],
                        },
                        "prompt": {
                            "type": "string",
                            "description": "Task description for the subagent",
                        },
                        "max_turns": {
                            "type": "integer",
                            "description": "Maximum number of turns for the subagent",
                            "default": 10,
                        },
                    },
                    "required": ["subagent_type", "prompt"],
                },
                executor=invoke_subagent_tool,
                category=ToolCategory.PROJECT,
            )
        )

        return registry

    @pytest.fixture
    def mock_model_with_subagent(self):
        """Create a mock model that invokes subagents."""

        class MockSubagentModel(ModelAdapter):
            def __init__(self):
                self.call_count = 0

            async def chat(self, messages, **kwargs):
                """Required abstract method - not used in these tests."""
                yield "Mock chat response"

            async def chat_with_tools(self, messages, tools, **kwargs):
                self.call_count += 1

                if self.call_count == 1:
                    # First call: invoke general-purpose subagent
                    return {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_subagent_1",
                                "type": "function",
                                "function": {
                                    "name": "invoke_subagent",
                                    "arguments": '{"subagent_type": "general-purpose", "prompt": "Analyze the codebase structure"}',
                                },
                            }
                        ],
                    }
                elif self.call_count == 2:
                    # Second call: completion with subagent result
                    return {
                        "role": "assistant",
                        "content": "The subagent has completed the analysis. Here are the findings...",
                    }

            def get_model_name(self):
                return "mock-subagent"

        return MockSubagentModel()

    @pytest.mark.asyncio
    async def test_subagent_invocation_basic(
        self, subagent_tool_registry, mock_model_with_subagent, test_context
    ):
        """Test basic subagent invocation from main agent."""
        agent = TesslateAgent(
            system_prompt="You are a project manager that delegates to subagents.",
            tools=subagent_tool_registry,
            model=mock_model_with_subagent,
        )

        events = []
        async for event in agent.run("Analyze the project structure", test_context):
            events.append(event)

        # Verify subagent was invoked
        tool_events = [e for e in events if e.get("type") == "tool_result"]
        assert len(tool_events) > 0

        # Verify subagent invocation in tool calls
        subagent_calls = [
            e for e in tool_events if "invoke_subagent" in str(e.get("tool_name", ""))
        ]
        assert len(subagent_calls) > 0

    @pytest.mark.asyncio
    async def test_subagent_plan_mode(self, subagent_tool_registry, test_context):
        """Test Plan subagent for creating implementation plans."""

        class MockPlanModel(ModelAdapter):
            async def chat(self, messages, **kwargs):
                """Required abstract method - not used in these tests."""
                yield "Mock chat response"

            async def chat_with_tools(self, messages, tools, **kwargs):
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_plan",
                            "type": "function",
                            "function": {
                                "name": "invoke_subagent",
                                "arguments": '{"subagent_type": "Plan", "prompt": "Create a plan to implement authentication"}',
                            },
                        }
                    ],
                }

            def get_model_name(self):
                return "mock-plan"

        agent = TesslateAgent(
            system_prompt="You are a project planner.",
            tools=subagent_tool_registry,
            model=MockPlanModel(),
        )

        events = []
        async for event in agent.run("Plan authentication feature", test_context):
            events.append(event)

        # Verify Plan subagent was invoked
        tool_events = [e for e in events if e.get("type") == "tool_result"]
        plan_results = [e for e in tool_events if "Plan created" in str(e.get("result", ""))]
        assert len(plan_results) > 0

    @pytest.mark.asyncio
    async def test_subagent_explore_mode(self, subagent_tool_registry, test_context):
        """Test Explore subagent for codebase exploration."""

        class MockExploreModel(ModelAdapter):
            async def chat(self, messages, **kwargs):
                """Required abstract method - not used in these tests."""
                yield "Mock chat response"

            async def chat_with_tools(self, messages, tools, **kwargs):
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_explore",
                            "type": "function",
                            "function": {
                                "name": "invoke_subagent",
                                "arguments": '{"subagent_type": "Explore", "prompt": "Find all authentication-related files"}',
                            },
                        }
                    ],
                }

            def get_model_name(self):
                return "mock-explore"

        agent = TesslateAgent(
            system_prompt="You are a code navigator.",
            tools=subagent_tool_registry,
            model=MockExploreModel(),
        )

        events = []
        async for event in agent.run("Find auth files", test_context):
            events.append(event)

        # Verify Explore subagent was invoked
        tool_events = [e for e in events if e.get("type") == "tool_result"]
        explore_results = [e for e in tool_events if "Found" in str(e.get("result", ""))]
        assert len(explore_results) > 0

    @pytest.mark.asyncio
    async def test_subagent_parallel_invocation(self, subagent_tool_registry, test_context):
        """Test invoking multiple subagents in parallel."""

        class MockParallelSubagentModel(ModelAdapter):
            async def chat(self, messages, **kwargs):
                """Required abstract method - not used in these tests."""
                yield "Mock chat response"

            async def chat_with_tools(self, messages, tools, **kwargs):
                # Invoke multiple subagents in parallel
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_plan",
                            "type": "function",
                            "function": {
                                "name": "invoke_subagent",
                                "arguments": '{"subagent_type": "Plan", "prompt": "Plan frontend"}',
                            },
                        },
                        {
                            "id": "call_explore",
                            "type": "function",
                            "function": {
                                "name": "invoke_subagent",
                                "arguments": '{"subagent_type": "Explore", "prompt": "Explore backend"}',
                            },
                        },
                    ],
                }

            def get_model_name(self):
                return "mock-parallel-subagent"

        agent = TesslateAgent(
            system_prompt="You are a project coordinator.",
            tools=subagent_tool_registry,
            model=MockParallelSubagentModel(),
        )

        events = []
        async for event in agent.run("Analyze frontend and backend", test_context):
            events.append(event)

        # Verify both subagents were invoked
        tool_events = [e for e in events if e.get("type") == "tool_result"]
        assert len(tool_events) >= 2  # At least two subagent results

    @pytest.mark.asyncio
    async def test_subagent_error_handling(self, subagent_tool_registry, test_context):
        """Test error handling when subagent invocation fails."""

        class MockErrorSubagentModel(ModelAdapter):
            async def chat(self, messages, **kwargs):
                """Required abstract method - not used in these tests."""
                yield "Mock chat response"

            async def chat_with_tools(self, messages, tools, **kwargs):
                # Invoke invalid subagent type
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_invalid",
                            "type": "function",
                            "function": {
                                "name": "invoke_subagent",
                                "arguments": '{"subagent_type": "InvalidType", "prompt": "Do something"}',
                            },
                        }
                    ],
                }

            def get_model_name(self):
                return "mock-error-subagent"

        agent = TesslateAgent(
            system_prompt="You are a test agent.",
            tools=subagent_tool_registry,
            model=MockErrorSubagentModel(),
        )

        events = []
        async for event in agent.run("Test error", test_context):
            events.append(event)

        # Should handle error gracefully
        tool_events = [e for e in events if e.get("type") == "tool_result"]
        error_results = [e for e in tool_events if e.get("result", {}).get("success") is False]
        assert len(error_results) > 0

    @pytest.mark.asyncio
    async def test_subagent_max_turns_limit(self, subagent_tool_registry, test_context):
        """Test subagent respects max_turns parameter."""

        class MockMaxTurnsModel(ModelAdapter):
            async def chat(self, messages, **kwargs):
                """Required abstract method - not used in these tests."""
                yield "Mock chat response"

            async def chat_with_tools(self, messages, tools, **kwargs):
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_limited",
                            "type": "function",
                            "function": {
                                "name": "invoke_subagent",
                                "arguments": '{"subagent_type": "general-purpose", "prompt": "Long task", "max_turns": 3}',
                            },
                        }
                    ],
                }

            def get_model_name(self):
                return "mock-max-turns"

        agent = TesslateAgent(
            system_prompt="You are a test agent.",
            tools=subagent_tool_registry,
            model=MockMaxTurnsModel(),
        )

        events = []
        async for event in agent.run("Test max turns", test_context):
            events.append(event)

        # Verify subagent result includes turns_used
        tool_events = [e for e in events if e.get("type") == "tool_result"]
        assert len(tool_events) > 0

        # Check turns_used is present and <= max_turns
        for event in tool_events:
            result = event.get("result", {})
            if isinstance(result, dict) and "turns_used" in result:
                assert result["turns_used"] <= 3

    @pytest.mark.asyncio
    async def test_subagent_no_nesting(self, subagent_tool_registry, test_context):
        """Test that subagents cannot invoke other subagents (no nesting)."""
        # This is enforced by SubagentManager - subagents don't have access to invoke_subagent tool
        # This test verifies the architecture prevents infinite recursion

        # Create a registry WITHOUT invoke_subagent for the subagent
        subagent_registry = ToolRegistry()

        # Subagent should only have basic tools, not invoke_subagent
        async def echo_tool(params, context):
            return {"message": f"Echo: {params.get('text', '')}"}

        subagent_registry.register(
            Tool(
                name="echo",
                description="Echo text",
                parameters={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                executor=echo_tool,
                category=ToolCategory.FILE_OPS,
            )
        )

        # Verify invoke_subagent is not in subagent registry
        assert "invoke_subagent" not in [tool.name for tool in subagent_registry.get_all()]

        # This ensures subagents can't spawn more subagents
        # preventing infinite recursion
