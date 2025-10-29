"""
Iterative Agent

Model-agnostic agent that uses a think-act-reflect loop with tool calling.
This agent iteratively processes tasks by thinking, calling tools, and reflecting
on results until the task is complete.
"""

import logging
from typing import List, Dict, Any, Optional, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from .base import AbstractAgent
from .models import ModelAdapter
from .parser import AgentResponseParser, ToolCall
from .tools.registry import ToolRegistry
from .prompts import get_user_message_wrapper

logger = logging.getLogger(__name__)


def _convert_uuids_to_strings(obj: Any) -> Any:
    """
    Recursively convert UUID objects to strings in nested data structures.

    This ensures that data can be JSON-serialized for database storage.

    Args:
        obj: Any object (dict, list, UUID, or primitive)

    Returns:
        The same structure with UUIDs converted to strings
    """
    if isinstance(obj, UUID):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: _convert_uuids_to_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_uuids_to_strings(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(_convert_uuids_to_strings(item) for item in obj)
    else:
        return obj


@dataclass
class AgentStep:
    """
    Represents one iteration of the agent's execution loop.

    Each step captures the agent's thinking, actions taken, and results received.
    """
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
                    "parameters": _convert_uuids_to_strings(tc.parameters)
                }
                for tc in self.tool_calls
            ],
            "tool_results": _convert_uuids_to_strings(self.tool_results),
            "response_text": self.response_text,
            "timestamp": self.timestamp.isoformat(),
            "is_complete": self.is_complete
        }


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
        max_iterations: int = 20
    ):
        """
        Initialize the Iterative Agent.

        Args:
            system_prompt: The system prompt for the agent
            tools: Registry of available tools (if None, uses global registry)
            model: Model adapter for LLM communication (can be set later)
            max_iterations: Maximum number of agent loop iterations
        """
        super().__init__(system_prompt, tools)

        self.model = model
        self.max_iterations = max_iterations
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

        # Extract and prepare project context
        project_context = None
        if 'project_context' in context:
            project_context = context['project_context']

        # Add user_id and project_id to project_context for environment context
        if project_context is None:
            project_context = {}

        project_context['user_id'] = context.get('user_id')
        project_context['project_id'] = context.get('project_id')

        # Initialize conversation with system prompt
        full_system_prompt = self._get_system_prompt()

        # Get user message with full [CONTEXT] section
        user_message = await get_user_message_wrapper(user_request, project_context)

        self.messages = [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": user_message}
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

                # Step 3: Execute tools if any (skip if task is complete)
                tool_results = []
                if tool_calls and not is_complete:
                    tool_results = await self._execute_tool_calls(tool_calls, context)
                    self.tool_calls_count += len(tool_calls)
                elif tool_calls and is_complete:
                    logger.info(f"[IterativeAgent] Skipping {len(tool_calls)} tool calls because task is complete")
                    tool_calls = []  # Clear tool calls to avoid showing "Unknown tool" errors

                # Record this step and yield to client
                display_text = response
                if not tool_calls and not is_complete:
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

                # If no tool calls and no completion signal, assume task is done
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
            # Handle parse errors specially
            if tool_call.name == "__parse_error__":
                logger.warning(f"[IterativeAgent] Parse error detected for tool: {tool_call.parameters.get('tool_name')}")
                result = {
                    "success": False,
                    "tool": tool_call.parameters.get('tool_name', 'unknown'),
                    "error": "Tool call parsing failed - Invalid JSON format",
                    "result": {
                        "message": f"Failed to parse tool call for '{tool_call.parameters.get('tool_name', 'unknown')}'",
                        "error_details": tool_call.parameters.get('error'),
                        "problematic_json": tool_call.parameters.get('raw_params', ''),
                        "suggestion": tool_call.parameters.get('suggestion', '')
                    }
                }
                results.append(result)
                continue

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
                    # Show message first (user-friendly summary)
                    if "message" in tool_result:
                        formatted.append(f"   message: {tool_result['message']}")

                    # Show full content/stdout/output for agent context
                    # DO NOT truncate - agent needs full context
                    if "content" in tool_result:
                        formatted.append(f"   content:")
                        content_lines = tool_result["content"].split('\n')
                        for line in content_lines:
                            formatted.append(f"   | {line}")
                    elif "stdout" in tool_result:
                        formatted.append(f"   stdout:")
                        stdout_lines = tool_result["stdout"].split('\n')
                        for line in stdout_lines:
                            formatted.append(f"   | {line}")
                    elif "output" in tool_result:
                        formatted.append(f"   output:")
                        output_lines = tool_result["output"].split('\n')
                        for line in output_lines:
                            formatted.append(f"   | {line}")
                    elif "preview" in tool_result:
                        formatted.append(f"   preview:")
                        preview_lines = tool_result["preview"].split('\n')
                        for line in preview_lines:
                            formatted.append(f"   | {line}")

                    # Show files list (for list_files)
                    if "files" in tool_result:
                        if isinstance(tool_result["files"], list):
                            if len(tool_result["files"]) > 0:
                                formatted.append(f"   files ({len(tool_result['files'])} items):")
                                for file in tool_result["files"]:
                                    if isinstance(file, dict):
                                        file_type = file.get("type", "file")
                                        file_name = file.get("name", file.get("path", "unknown"))
                                        file_size = file.get("size", 0)
                                        formatted.append(f"     [{file_type}] {file_name} ({file_size} bytes)")
                                    else:
                                        formatted.append(f"     {file}")
                        else:
                            formatted.append(f"   files: {tool_result['files']}")

                    # Show directory (for list_files context)
                    if "directory" in tool_result and "files" not in formatted[-1]:
                        formatted.append(f"   directory: {tool_result['directory']}")

                    # Show file_path for file operations
                    if "file_path" in tool_result and "message" not in formatted[-1]:
                        formatted.append(f"   file_path: {tool_result['file_path']}")

                    # Show command for command execution
                    if "command" in tool_result and "message" not in formatted[-1]:
                        formatted.append(f"   command: {tool_result['command']}")

                    # Show stderr if present (errors)
                    if "stderr" in tool_result and tool_result["stderr"]:
                        formatted.append(f"   stderr:")
                        stderr_lines = tool_result["stderr"].split('\n')
                        for line in stderr_lines:
                            formatted.append(f"   | {line}")

                    # Show suggestion for errors/guidance
                    if "suggestion" in tool_result:
                        formatted.append(f"   suggestion: {tool_result['suggestion']}")

                    # Show details last (technical info)
                    if "details" in tool_result:
                        formatted.append(f"   details: {tool_result['details']}")

                else:
                    formatted.append(f"   {tool_result}")
            else:
                error = result.get("error", "Unknown error")
                formatted.append(f"   Error: {error}")

                # Show suggestion from result if available
                if isinstance(result.get("result"), dict):
                    if "suggestion" in result["result"]:
                        formatted.append(f"   Suggestion: {result['result']['suggestion']}")

                    # Show parse error details prominently
                    if "error_details" in result["result"]:
                        formatted.append(f"   Details: {result['result']['error_details']}")

                    if "problematic_json" in result["result"] and result["result"]["problematic_json"]:
                        formatted.append(f"   Problematic JSON (first 300 chars):")
                        formatted.append(f"   {result['result']['problematic_json'][:300]}")

        return "\n".join(formatted)

    def _get_system_prompt(self) -> str:
        """
        Build the complete system prompt for the agent.

        The prompt has three parts:
        1. Base methodology (Plan-Act-Observe-Verify workflow)
        2. Agent specialization (custom prompt defining agent role/expertise)
        3. Tool information (available tools, formatting, usage rules)

        Returns:
            Complete system prompt string
        """
        from .prompts import get_base_methodology_prompt

        # Start with base methodology
        prompt_parts = [get_base_methodology_prompt()]

        # Add agent specialization
        if self.system_prompt and self.system_prompt.strip():
            prompt_parts.append("\n\n=== AGENT SPECIALIZATION ===\n")
            prompt_parts.append(self.system_prompt)

        # Add tool information
        if self.tools:
            prompt_parts.append(self._get_tool_info())

        return "\n".join(prompt_parts)

    def _get_tool_info(self) -> str:
        """
        Get formatted tool information to append to system prompt.

        Returns tool usage instructions, formatting examples, and available tools list.
        """
        if not self.tools:
            return ""

        tools_text = [
            "\n\nTool Usage and Formatting",
            "",
            "Your actions are communicated through specific XML-style tool calls. You must include a THOUGHT section before every tool call to explain your reasoning.",
            "",
            "CRITICAL: Parameters must be provided as VALID JSON inside the <parameters> tags.",
            "",
            "JSON Escaping Rules (MUST FOLLOW):",
            "1. ALL quotes inside string values MUST be escaped with backslash: \\\"",
            "2. Newlines must be escaped as \\n, tabs as \\t, backslashes as \\\\",
            "3. Use only double quotes for JSON strings, never single quotes",
            "",
            "Examples:",
            '{"description": "The video for \\"Never Gonna Give You Up\\" by Rick Astley"}',
            '{"message": "Line 1\\nLine 2\\nLine 3"}',
            '{"path": "C:\\\\Users\\\\Documents\\\\file.txt"}',
            "",
            "Tool Call Format:",
            "",
            "THOUGHT: I need to understand the current file structure to locate the main application file. I will list the files in the src directory to get an overview.",
            "",
            "<tool_call>",
            "<tool_name>TOOL_NAME_HERE</tool_name>",
            "<parameters>",
            '{"parameter_name": "value", "another_parameter": "value2"}',
            "</parameters>",
            "</tool_call>",
            "",
            "Complete Example:",
            "",
            "THOUGHT: I will read the App.jsx file to understand the application structure.",
            "",
            "<tool_call>",
            "<tool_name>read_file</tool_name>",
            "<parameters>",
            '{"file_path": "src/App.jsx"}',
            "</parameters>",
            "</tool_call>",
            "",
            "Available Tools:",
            ""
        ]

        # List all available tools with descriptions and parameters
        for tool_name, tool in self.tools._tools.items():
            tools_text.append(f"{tool_name}: {tool.description}")
            tools_text.append("")

            # Add parameters
            if hasattr(tool, 'parameters'):
                params = tool.parameters
                if isinstance(params, dict):
                    props = params.get('properties', {})
                    required = params.get('required', [])

                    if props:
                        tools_text.append("Parameters:")
                        tools_text.append("")
                        for param_name, param_info in props.items():
                            param_type = param_info.get('type', 'string')
                            req_str = 'required' if param_name in required else 'optional'
                            param_desc = param_info.get('description', '')
                            tools_text.append(f"  - {param_name} ({param_type}, {req_str}): {param_desc}")
                            tools_text.append("")

        tools_text.extend([
            "Rules and Constraints",
            "",
            "One Tool Call per Thought: Always include a THOUGHT section before tool calls.",
            "",
            "Wait for Observation: ALWAYS wait for the observation from your previous tool use before issuing the next command. Do not assume the outcome of any action.",
            "",
            "Conciseness: Be professional and concise. Do not provide conversational filler.",
            "",
            "File Modifications: Read files before modifying them to understand their current state.",
            "",
            "Output Truncation: Be aware that long command outputs or file contents may be truncated to preserve context space. You will be notified if this happens."
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
