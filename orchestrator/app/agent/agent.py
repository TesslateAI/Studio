"""
Universal Agent

Model-agnostic agent that uses prompt engineering and tool calling to accomplish tasks.
Works with ANY language model by using text-based tool calling instead of function calling APIs.

"""

import logging
from typing import List, Dict, Any, Optional, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime

from .models import ModelAdapter
from .parser import AgentResponseParser, ToolCall
from .tools.registry import ToolRegistry
from .prompts import get_base_system_prompt, get_model_specific_prompt, get_user_message_wrapper

logger = logging.getLogger(__name__)


@dataclass
class AgentStep:
    """Represents one step in the agent's execution."""
    iteration: int
    thought: Optional[str]
    tool_calls: List[ToolCall]
    tool_results: List[Dict[str, Any]]
    response_text: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_complete: bool = False


@dataclass
class AgentResult:
    """Final result of agent execution."""
    success: bool
    iterations: int
    steps: List[AgentStep]
    final_response: str
    error: Optional[str] = None
    tool_calls_made: int = 0
    completion_reason: str = "unknown"


class UniversalAgent:
    """
    Universal agent that works with any language model.

    Uses prompt engineering and regex parsing to enable tool calling
    without requiring model-specific function calling APIs.
    """

    def __init__(
        self,
        model: ModelAdapter,
        tool_registry: ToolRegistry,
        max_iterations: int = 20,
        minimal_prompts: bool = False,
        system_prompt: Optional[str] = None
    ):
        """
        Initialize the Universal Agent.

        Args:
            model: Model adapter for LLM communication
            tool_registry: Registry of available tools
            max_iterations: Maximum number of agent loop iterations
            minimal_prompts: Use minimal system prompts (for simpler models)
            system_prompt: Optional custom system prompt to override default
        """
        self.model = model
        self.tool_registry = tool_registry
        self.parser = AgentResponseParser()
        self.max_iterations = max_iterations
        self.minimal_prompts = minimal_prompts
        self.custom_system_prompt = system_prompt  # Store custom system prompt

        # Conversation history
        self.messages: List[Dict[str, str]] = []

        # Execution tracking
        self.steps: List[AgentStep] = []
        self.tool_calls_count = 0

        logger.info(
            f"UniversalAgent initialized - model: {model.get_model_name()}, "
            f"max_iterations: {max_iterations}, tools: {len(tool_registry._tools)}, "
            f"custom_prompt: {'Yes' if system_prompt else 'No'}"
        )

    async def run(
        self,
        user_request: str,
        context: Dict[str, Any],
        project_context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """
        Run the agent to complete a user request.

        This is the main agent loop that:
        1. Gets response from model
        2. Parses for tool calls
        3. Executes tools
        4. Feeds results back to model
        5. Repeats until complete or max iterations

        Args:
            user_request: The user's task/request
            context: Execution context (user_id, project_id, db, etc.)
            project_context: Optional context about the project

        Returns:
            AgentResult with execution details
        """
        logger.info(f"Agent starting - request: {user_request[:100]}...")

        # Initialize conversation with system prompt
        system_prompt = self._get_system_prompt()
        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": get_user_message_wrapper(user_request, project_context)}
        ]

        # Main agent loop
        for iteration in range(1, self.max_iterations + 1):
            logger.info(f"[Iteration {iteration}/{self.max_iterations}] Starting")

            try:
                # Step 1: Get model response
                response = await self.model.chat(self.messages)
                logger.debug(f"Model response: {response[:200]}...")

                # Step 2: Parse response
                tool_calls = self.parser.parse(response)
                thought = self.parser.extract_thought(response)
                is_complete = self.parser.is_complete(response)

                logger.info(
                    f"[Iteration {iteration}] Parsed {len(tool_calls)} tool call(s), "
                    f"complete: {is_complete}"
                )

                # Step 3: Execute tools if any
                tool_results = []
                if tool_calls:
                    tool_results = await self._execute_tool_calls(tool_calls, context)
                    self.tool_calls_count += len(tool_calls)

                # Record this step
                step = AgentStep(
                    iteration=iteration,
                    thought=thought,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    response_text=response,
                    is_complete=is_complete
                )
                self.steps.append(step)

                # Step 4: Update conversation history
                self.messages.append({"role": "assistant", "content": response})

                # Step 5: Feed tool results back to model (if any)
                if tool_results:
                    results_text = self._format_tool_results(tool_results)
                    self.messages.append({"role": "user", "content": results_text})

                # Step 6: Check for completion
                if is_complete:
                    logger.info(f"Task completed in {iteration} iterations")
                    conversational_text = self.parser.get_conversational_text(response)
                    return AgentResult(
                        success=True,
                        iterations=iteration,
                        steps=self.steps,
                        final_response=conversational_text or "Task completed successfully.",
                        tool_calls_made=self.tool_calls_count,
                        completion_reason="task_complete_signal"
                    )

                # If no tool calls and not complete, model might be done or stuck
                if not tool_calls and iteration > 1:
                    logger.info(f"No tool calls in iteration {iteration}, assuming complete")
                    conversational_text = self.parser.get_conversational_text(response)
                    return AgentResult(
                        success=True,
                        iterations=iteration,
                        steps=self.steps,
                        final_response=conversational_text or response,
                        tool_calls_made=self.tool_calls_count,
                        completion_reason="no_more_actions"
                    )

            except Exception as e:
                logger.error(f"[Iteration {iteration}] Error: {e}", exc_info=True)
                return AgentResult(
                    success=False,
                    iterations=iteration,
                    steps=self.steps,
                    final_response="",
                    error=str(e),
                    tool_calls_made=self.tool_calls_count,
                    completion_reason="error"
                )

        # Reached max iterations
        logger.warning(f"Reached max iterations ({self.max_iterations})")
        last_response = self.steps[-1].response_text if self.steps else ""
        conversational_text = self.parser.get_conversational_text(last_response)

        return AgentResult(
            success=False,
            iterations=self.max_iterations,
            steps=self.steps,
            final_response=conversational_text or "Maximum iterations reached",
            tool_calls_made=self.tool_calls_count,
            completion_reason="max_iterations"
        )

    async def _execute_tool_calls(
        self,
        tool_calls: List[ToolCall],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Execute a list of tool calls.

        Args:
            tool_calls: List of ToolCall objects
            context: Execution context

        Returns:
            List of tool results
        """
        results = []

        for i, tool_call in enumerate(tool_calls):
            logger.info(f"Executing tool {i+1}/{len(tool_calls)}: {tool_call.name}")

            result = await self.tool_registry.execute(
                tool_name=tool_call.name,
                parameters=tool_call.parameters,
                context=context
            )

            results.append(result)

            # Log result
            if result["success"]:
                logger.info(f"Tool {tool_call.name} succeeded")
            else:
                logger.warning(f"Tool {tool_call.name} failed: {result.get('error')}")

        return results

    def _format_tool_results(self, results: List[Dict[str, Any]]) -> str:
        """
        Format tool results for feeding back to the model.

        Args:
            results: List of tool execution results

        Returns:
            Formatted string
        """
        formatted = ["Tool Results:\n"]

        for i, result in enumerate(results, 1):
            tool_name = result.get("tool", "unknown")
            success = result.get("success", False)

            formatted.append(f"\n{i}. {tool_name}: {'✓ Success' if success else '✗ Failed'}")

            if success:
                tool_result = result.get("result", {})
                # Format result based on content
                if isinstance(tool_result, dict):
                    for key, value in tool_result.items():
                        if isinstance(value, str) and len(value) > 500:
                            formatted.append(f"   {key}: {value[:500]}... (truncated)")
                        elif isinstance(value, list) and len(value) > 10:
                            formatted.append(f"   {key}: [{len(value)} items]")
                        else:
                            formatted.append(f"   {key}: {value}")
                else:
                    formatted.append(f"   {tool_result}")
            else:
                error = result.get("error", "Unknown error")
                formatted.append(f"   Error: {error}")

        return "\n".join(formatted)

    def _get_system_prompt(self) -> str:
        """Get the appropriate system prompt for the model."""
        # Use custom system prompt if provided
        if self.custom_system_prompt:
            # Append tool information to the custom prompt
            tool_info = "\n\n" + self._get_tool_info()
            return self.custom_system_prompt + tool_info

        # Otherwise use default prompts
        if self.minimal_prompts:
            from .prompts import get_minimal_system_prompt
            return get_minimal_system_prompt(self.tool_registry)

        base_prompt = get_base_system_prompt(self.tool_registry, include_examples=True)
        return get_model_specific_prompt(self.model.get_model_name(), base_prompt)

    def _get_tool_info(self) -> str:
        """Get formatted tool information to append to custom prompts."""
        tools_text = [
            "\n\n=== TOOL CALLING FORMAT ===",
            "",
            "When you need to perform an action, output tool calls in this XML format:",
            "",
            "<tool_call>",
            "<tool_name>TOOL_NAME_HERE</tool_name>",
            "<parameters>",
            '{"parameter_name": "value"}',
            "</parameters>",
            "</tool_call>",
            "",
            "Important formatting rules:",
            "- Parameters must be valid JSON",
            "- You can call multiple tools in one response",
            "- Always include a THOUGHT section before tool calls explaining your reasoning",
            "",
            "=== Available Tools ===",
            ""
        ]
        for tool_name, tool in self.tool_registry._tools.items():
            tools_text.append(f"- {tool_name}: {tool.description}")

        tools_text.extend([
            "",
            "=== Task Completion ===",
            "",
            "When you have completed the user's request, output:",
            "TASK_COMPLETE",
            "",
            "Example:",
            "",
            "THOUGHT: I need to add a red border to the button in App.jsx",
            "",
            "<tool_call>",
            "<tool_name>read_file</tool_name>",
            '<parameters>{"file_path": "src/App.jsx"}</parameters>',
            "</tool_call>",
        ])

        return "\n".join(tools_text)

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get the full conversation history."""
        return self.messages.copy()

    def get_execution_summary(self) -> Dict[str, Any]:
        """Get a summary of the agent's execution."""
        return {
            "total_steps": len(self.steps),
            "tool_calls_made": self.tool_calls_count,
            "final_iteration": self.steps[-1].iteration if self.steps else 0,
            "completed": self.steps[-1].is_complete if self.steps else False
        }
