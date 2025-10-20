"""
Iterative Agent

Model-agnostic agent that uses a think-act-reflect loop with tool calling.
This agent iteratively processes tasks by thinking, calling tools, and reflecting
on results until the task is complete.

This is the refactored version of UniversalAgent that implements AbstractAgent.
"""

import logging
from typing import List, Dict, Any, Optional, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .base import AbstractAgent
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
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_complete: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert step to dictionary for JSON serialization."""
        return {
            "iteration": self.iteration,
            "thought": self.thought,
            "tool_calls": [
                {
                    "name": tc.name,
                    "parameters": tc.parameters
                }
                for tc in self.tool_calls
            ],
            "tool_results": self.tool_results,
            "response_text": self.response_text,
            "timestamp": self.timestamp.isoformat(),
            "is_complete": self.is_complete
        }


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


class IterativeAgent(AbstractAgent):
    """
    Iterative agent that works with any language model.

    Uses prompt engineering and regex parsing to enable tool calling
    without requiring model-specific function calling APIs.

    This agent follows a think-act-reflect loop:
    1. Think: Analyze the task and decide what to do
    2. Act: Execute tools to accomplish sub-tasks
    3. Reflect: Review results and decide next steps
    4. Repeat until task is complete
    """

    def __init__(
        self,
        system_prompt: str,
        tools: Optional[ToolRegistry] = None,
        model: Optional[ModelAdapter] = None,
        max_iterations: int = 20,
        minimal_prompts: bool = False
    ):
        """
        Initialize the Iterative Agent.

        Args:
            system_prompt: The system prompt for the agent
            tools: Registry of available tools (if None, uses global registry)
            model: Model adapter for LLM communication (can be set later)
            max_iterations: Maximum number of agent loop iterations
            minimal_prompts: Use minimal system prompts (for simpler models)
        """
        super().__init__(system_prompt, tools)

        self.model = model
        self.max_iterations = max_iterations
        self.minimal_prompts = minimal_prompts
        self.parser = AgentResponseParser()

        # Conversation history
        self.messages: List[Dict[str, str]] = []

        # Execution tracking
        self.steps: List[AgentStep] = []
        self.tool_calls_count = 0

        logger.info(
            f"IterativeAgent initialized - "
            f"max_iterations: {max_iterations}, "
            f"tools: {len(self.tools._tools) if self.tools else 0}"
        )

    def set_model(self, model: ModelAdapter):
        """Set the model adapter (useful for lazy initialization)."""
        self.model = model

    async def run(
        self,
        user_request: str,
        context: Dict[str, Any]
    ) -> AsyncIterator[Dict[str, Any]]:
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

        Yields:
            Events with types: agent_step, complete, error
        """
        if not self.model:
            yield {
                'type': 'error',
                'content': 'Model adapter not set. Call set_model() first.'
            }
            return

        logger.info(f"[IterativeAgent] Starting - request: {user_request[:100]}...")

        # Extract project context from context dict
        project_context = None
        if 'project_context' in context:
            project_context = context['project_context']

        # Initialize conversation with system prompt
        full_system_prompt = self._get_system_prompt()
        self.messages = [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": get_user_message_wrapper(user_request, project_context)}
        ]

        # Main agent loop
        for iteration in range(1, self.max_iterations + 1):
            logger.info(f"[IterativeAgent] Iteration {iteration}/{self.max_iterations}")

            try:
                # Step 1: Get model response
                response = await self.model.chat(self.messages)
                logger.debug(f"[IterativeAgent] Model response: {response[:200]}...")

                # Step 2: Parse response
                tool_calls = self.parser.parse(response)
                thought = self.parser.extract_thought(response)
                is_complete = self.parser.is_complete(response)

                logger.info(
                    f"[IterativeAgent] Iteration {iteration} - "
                    f"tool_calls: {len(tool_calls)}, complete: {is_complete}"
                )

                # Step 3: Execute tools if any
                tool_results = []
                if tool_calls:
                    tool_results = await self._execute_tool_calls(tool_calls, context)
                    self.tool_calls_count += len(tool_calls)

                # Record this step
                display_text = response
                if not tool_calls and not is_complete:
                    # Extract conversational text for display
                    conversational = self.parser.get_conversational_text(response)
                    if conversational:
                        display_text = conversational

                step = AgentStep(
                    iteration=iteration,
                    thought=thought,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    response_text=display_text,
                    is_complete=is_complete
                )
                self.steps.append(step)

                # Yield the step to the client
                yield {
                    'type': 'agent_step',
                    'data': step.to_dict()
                }

                # Step 4: Update conversation history
                self.messages.append({"role": "assistant", "content": response})

                # Step 5: Feed tool results back to model (if any)
                if tool_results:
                    results_text = self._format_tool_results(tool_results)
                    self.messages.append({"role": "user", "content": results_text})

                # Step 6: Check for completion
                if is_complete:
                    logger.info(f"[IterativeAgent] Task completed in {iteration} iterations")
                    conversational_text = self.parser.get_conversational_text(response)
                    yield {
                        'type': 'complete',
                        'data': {
                            'success': True,
                            'iterations': iteration,
                            'final_response': conversational_text or "Task completed successfully.",
                            'tool_calls_made': self.tool_calls_count,
                            'completion_reason': 'task_complete_signal'
                        }
                    }
                    return

                # If no tool calls and not complete, model might be done
                if not tool_calls and iteration > 1:
                    logger.info(f"[IterativeAgent] No tool calls in iteration {iteration}, assuming complete")
                    conversational_text = self.parser.get_conversational_text(response)
                    yield {
                        'type': 'complete',
                        'data': {
                            'success': True,
                            'iterations': iteration,
                            'final_response': conversational_text or response,
                            'tool_calls_made': self.tool_calls_count,
                            'completion_reason': 'no_more_actions'
                        }
                    }
                    return

            except Exception as e:
                logger.error(f"[IterativeAgent] Iteration {iteration} error: {e}", exc_info=True)
                yield {
                    'type': 'error',
                    'content': f'Agent error: {str(e)}'
                }
                yield {
                    'type': 'complete',
                    'data': {
                        'success': False,
                        'iterations': iteration,
                        'final_response': '',
                        'error': str(e),
                        'tool_calls_made': self.tool_calls_count,
                        'completion_reason': 'error'
                    }
                }
                return

        # Reached max iterations
        logger.warning(f"[IterativeAgent] Reached max iterations ({self.max_iterations})")
        last_response = self.steps[-1].response_text if self.steps else ""
        conversational_text = self.parser.get_conversational_text(last_response)

        yield {
            'type': 'complete',
            'data': {
                'success': False,
                'iterations': self.max_iterations,
                'final_response': conversational_text or "Maximum iterations reached",
                'tool_calls_made': self.tool_calls_count,
                'completion_reason': 'max_iterations'
            }
        }

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
        if not self.tools:
            logger.error("[IterativeAgent] No tool registry available")
            return [{
                "success": False,
                "error": "No tool registry available"
            } for _ in tool_calls]

        results = []

        for i, tool_call in enumerate(tool_calls):
            logger.info(f"[IterativeAgent] Executing tool {i+1}/{len(tool_calls)}: {tool_call.name}")

            result = await self.tools.execute(
                tool_name=tool_call.name,
                parameters=tool_call.parameters,
                context=context
            )

            results.append(result)

            # Log result
            if result["success"]:
                logger.info(f"[IterativeAgent] Tool {tool_call.name} succeeded")
            else:
                logger.warning(f"[IterativeAgent] Tool {tool_call.name} failed: {result.get('error')}")

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
                        # Skip preview for now
                        if key == "preview":
                            continue

                        if isinstance(value, str) and len(value) > 500:
                            formatted.append(f"   {key}: {value[:500]}... (truncated)")
                        elif isinstance(value, list) and len(value) > 10:
                            formatted.append(f"   {key}: [{len(value)} items]")
                        else:
                            formatted.append(f"   {key}: {value}")

                    # Show preview last if it exists
                    if "preview" in tool_result:
                        formatted.append(f"   Content Preview:")
                        preview_lines = tool_result["preview"].split('\n')
                        for line in preview_lines:
                            formatted.append(f"   | {line}")
                else:
                    formatted.append(f"   {tool_result}")
            else:
                error = result.get("error", "Unknown error")
                formatted.append(f"   Error: {error}")

        return "\n".join(formatted)

    def _get_system_prompt(self) -> str:
        """Get the appropriate system prompt for the model."""
        # The system_prompt from AbstractAgent contains the custom agent prompt
        # We need to append tool information to it
        if self.tools:
            tool_info = "\n\n" + self._get_tool_info()
            return self.system_prompt + tool_info
        else:
            return self.system_prompt

    def _get_tool_info(self) -> str:
        """Get formatted tool information to append to custom prompts."""
        if not self.tools:
            return ""

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

        for tool_name, tool in self.tools._tools.items():
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
