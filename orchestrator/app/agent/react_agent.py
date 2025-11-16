"""
ReAct Agent

A ReAct (Reasoning + Acting) agent that explicitly separates reasoning from action.
This agent follows the ReAct paradigm: Thought (Reasoning) → Action → Observation loop
until the task is complete.

Based on the paper "ReAct: Synergizing Reasoning and Acting in Language Models"
https://arxiv.org/abs/2210.03629
"""

import logging
from typing import List, Dict, Any, Optional, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from .base import AbstractAgent
from .models import ModelAdapter
from .parser import AgentResponseParser, ToolCall
from .prompts import get_user_message_wrapper
from .tools.registry import ToolRegistry
from .resource_limits import get_resource_limits, ResourceLimitExceeded

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
class ReActStep:
    """
    Represents one iteration of the ReAct agent's execution loop.

    Each step captures the agent's reasoning, actions taken, and observations received.
    """
    iteration: int
    thought: Optional[str]  # Reasoning step
    tool_calls: List[ToolCall]  # Actions
    tool_results: List[Dict[str, Any]]  # Observations
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


class ReActAgent(AbstractAgent):
    """
    ReAct agent that explicitly implements the Reasoning + Acting paradigm.

    Uses prompt engineering and regex parsing to enable tool calling
    without requiring model-specific function calling APIs.

    This agent follows the ReAct loop:
    1. Thought (Reasoning): Analyze the task and reason about what to do
    2. Action: Execute tools to accomplish sub-tasks
    3. Observation: Receive and analyze results
    4. Repeat until task is complete

    The key difference from IterativeAgent is the explicit emphasis on
    structured reasoning before each action.
    """

    def __init__(
        self,
        system_prompt: str,
        tools: Optional[ToolRegistry] = None,
        model: Optional[ModelAdapter] = None
    ):
        """
        Initialize the ReAct Agent.

        Args:
            system_prompt: The system prompt for the agent
            tools: Registry of available tools (if None, uses global registry)
            model: Model adapter for LLM communication (can be set later)
        """
        super().__init__(system_prompt, tools)

        self.model = model
        self.parser = AgentResponseParser()

        # Conversation history
        self.messages: List[Dict[str, str]] = []

        # Execution tracking
        self.steps: List[ReActStep] = []
        self.tool_calls_count = 0
        self.last_step_had_errors = False  # Track if previous iteration had errors

        logger.info(
            f"ReActAgent initialized - "
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
        Run the ReAct agent to complete a user request.

        This is the main ReAct loop that:
        1. Gets reasoning + action from model
        2. Parses for tool calls (actions)
        3. Executes tools
        4. Feeds observations back to model
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

        logger.info(f"[ReActAgent] Starting - request: {user_request[:100]}...")

        # Initialize resource limits tracking
        limits = get_resource_limits()
        run_id = f"user-{context.get('user_id')}-project-{context.get('project_id')}-{datetime.now(timezone.utc).timestamp()}"

        # Extract and prepare project context
        project_context = None
        if 'project_context' in context:
            project_context = context['project_context']

        # Add user_id and project_id to project_context for environment context
        if project_context is None:
            project_context = {}

        project_context['user_id'] = context.get('user_id')
        project_context['project_id'] = context.get('project_id')

        # Initialize conversation with system prompt (with marker substitution)
        full_system_prompt = self._get_system_prompt(context)

        # Get user message with full [CONTEXT] section
        user_message = await get_user_message_wrapper(user_request, project_context)

        # Build messages list starting with system prompt
        self.messages = [
            {"role": "system", "content": full_system_prompt}
        ]

        # Include chat history if provided (for conversation continuity)
        chat_history = context.get('chat_history', [])
        if chat_history:
            logger.info(f"[ReActAgent] Including {len(chat_history)} previous messages for context")
            self.messages.extend(chat_history)

        # Add current user message
        self.messages.append({"role": "user", "content": user_message})

        # Main ReAct loop
        iteration = 0
        try:
            while True:
                iteration += 1
                logger.info(f"[ReActAgent] Iteration {iteration}")

                # Track iteration globally
                try:
                    limits.add_iteration(run_id)
                except ResourceLimitExceeded as e:
                    logger.warning(f"[ReActAgent] Resource limit exceeded: {e}")
                    yield {
                        'type': 'error',
                        'content': f'Resource limit exceeded: {str(e)}'
                    }
                    yield {
                        'type': 'complete',
                        'data': {
                            'success': False,
                            'iterations': iteration,
                            'final_response': '',
                            'error': str(e),
                            'tool_calls_made': self.tool_calls_count,
                            'completion_reason': 'resource_limit_exceeded',
                            'resource_stats': limits.get_stats(run_id)
                        }
                    }
                    return

                # DEBUG: Log full context being sent to LLM
                logger.debug(f"[ReActAgent] Context sent to LLM (iteration {iteration}):")
                for idx, msg in enumerate(self.messages):
                    role = msg['role']
                    content = msg['content']
                    logger.debug(f"  Message {idx} [{role}]: {content[:500]}..." if len(content) > 500 else f"  Message {idx} [{role}]: {content}")

                try:
                    # Step 1: Get model response (streaming)
                    response = ""
                    async for chunk in self.model.chat(self.messages):
                        response += chunk
                        # Yield text chunk to keep connection alive and show real-time generation
                        yield {
                            'type': 'text_chunk',
                            'data': {
                                'content': chunk,
                                'iteration': iteration
                            }
                        }

                    # DEBUG: Log full model response
                    logger.debug(f"[ReActAgent] Full model response (iteration {iteration}):")
                    logger.debug(f"  {response}")
                    logger.debug(f"[ReActAgent] Model response complete: {response[:200]}...")

                    # Step 2: Parse response
                    tool_calls = self.parser.parse(response)
                    thought = self.parser.extract_thought(response)
                    is_complete = self.parser.is_complete(response)

                    logger.info(
                        f"[ReActAgent] Iteration {iteration} - "
                        f"tool_calls: {len(tool_calls)}, complete: {is_complete}"
                    )

                    # DEBUG: Log parsed data
                    logger.debug(f"[ReActAgent] Parsed thought (Reasoning): {thought}")
                    logger.debug(f"[ReActAgent] Parsed tool_calls (Actions): {[{'name': tc.name, 'params': tc.parameters} for tc in tool_calls]}")
                    logger.debug(f"[ReActAgent] Is complete: {is_complete}")

                    # Step 3: Execute tools (Actions) if any
                    tool_results = []
                    if tool_calls:
                        tool_results = await self._execute_tool_calls(tool_calls, context)
                        self.tool_calls_count += len(tool_calls)

                        # Check for approval requests (Ask Before Edit mode)
                        for idx, result in enumerate(tool_results):
                            if result.get("approval_required"):
                                from .tools.approval_manager import get_approval_manager
                                approval_mgr = get_approval_manager()

                                # Create approval request
                                approval_id, request = await approval_mgr.request_approval(
                                    tool_name=result["tool"],
                                    parameters=result["parameters"],
                                    session_id=result["session_id"]
                                )

                                # Emit approval_required event
                                yield {
                                    'type': 'approval_required',
                                    'data': {
                                        'approval_id': approval_id,
                                        'tool_name': result["tool"],
                                        'tool_parameters': result["parameters"],
                                        'tool_description': f"Execute {result['tool']} operation"
                                    }
                                }

                                logger.info(f"[ReActAgent] Waiting for user approval for {result['tool']}")

                                # Wait for user response
                                await request.event.wait()

                                logger.info(f"[ReActAgent] Received approval response: {request.response}")

                                # Handle response
                                if request.response == 'stop':
                                    # User cancelled - terminate agent execution completely
                                    logger.info(f"[ReActAgent] User stopped execution at {result['tool']}")
                                    yield {
                                        'type': 'complete',
                                        'data': {
                                            'final_response': "Execution stopped by user.",
                                            'iterations': iteration,
                                            'tool_calls_made': self.tool_calls_count,
                                            'completion_reason': 'user_stopped'
                                        }
                                    }
                                    return  # Terminate agent execution
                                else:
                                    # allow_once or allow_all - retry execution with approval check bypassed
                                    logger.info(f"[ReActAgent] Retrying {tool_calls[idx].name} with approval granted")
                                    # Create modified context that skips approval check for this execution
                                    approved_context = {**context, 'skip_approval_check': True}
                                    tool_results[idx] = await self.tools.execute(
                                        tool_name=tool_calls[idx].name,
                                        parameters=tool_calls[idx].parameters,
                                        context=approved_context
                                    )

                        # Check if any tools failed or had parse errors
                        self.last_step_had_errors = any(
                            not result.get("success", False) for result in tool_results
                        )
                    else:
                        # No tool calls means no errors in this iteration
                        self.last_step_had_errors = False

                    # Record this step and yield to client
                    # Always extract conversational text to hide internal thinking from users
                    conversational = self.parser.get_conversational_text(response)
                    display_text = conversational if conversational else response

                    step = ReActStep(
                        iteration=iteration,
                        thought=thought,
                        tool_calls=tool_calls,
                        tool_results=tool_results,
                        response_text=display_text,
                        is_complete=is_complete
                    )
                    self.steps.append(step)

                    # Build step data with optional debug info
                    step_data = step.to_dict()

                    # Add debug data (only included if client requests it)
                    step_data['_debug'] = {
                        'full_response': response,
                        'context_messages_count': len(self.messages),
                        'context_messages': self.messages.copy(),  # Full context history
                        'raw_tool_calls': [{'name': tc.name, 'params': tc.parameters} for tc in tool_calls],
                        'raw_thought': thought,
                        'is_complete': is_complete,
                        'conversational_text': conversational,
                        'display_text': display_text
                    }

                    yield {
                        'type': 'agent_step',
                        'data': step_data
                    }

                    # Step 4: Update conversation history
                    self.messages.append({"role": "assistant", "content": response})

                    # Step 5: Feed tool results back to model (Observations)
                    if tool_results:
                        results_text = self._format_tool_results(tool_results)
                        self.messages.append({"role": "user", "content": results_text})

                    # Step 6: Check for completion
                    if is_complete:
                        # DON'T allow completion if there were errors in this iteration
                        if self.last_step_had_errors:
                            logger.warning(
                                f"[ReActAgent] Task marked complete but had errors in iteration {iteration}. "
                                f"Continuing to force retry."
                            )
                            # Add instruction to retry
                            retry_instruction = (
                                "\n\nYou marked the task as complete, but the previous actions had errors. "
                                "You MUST fix the errors first before completing the task. "
                                "Retry the failed operations with corrected parameters."
                            )
                            self.messages.append({"role": "user", "content": retry_instruction})
                            continue  # Force next iteration

                        logger.info(f"[ReActAgent] Task completed in {iteration} iterations")
                        conversational_text = self.parser.get_conversational_text(response)
                        yield {
                            'type': 'complete',
                            'data': {
                                'success': True,
                                'iterations': iteration,
                                'final_response': conversational_text or "Task completed successfully.",
                                'tool_calls_made': self.tool_calls_count,
                                'completion_reason': 'task_complete_signal',
                                'resource_stats': limits.get_stats(run_id)
                            }
                        }
                        return

                    # If no tool calls, check if we should complete
                    if not tool_calls:
                        conversational_text = self.parser.get_conversational_text(response)

                        # DON'T complete if the previous iteration had errors - require retry
                        if self.last_step_had_errors:
                            logger.warning(
                                f"[ReActAgent] No tool calls in iteration {iteration}, "
                                f"but previous step had errors. Continuing to force retry."
                            )
                            # Add instruction to retry
                            retry_instruction = (
                                "\n\nThe previous actions had errors. "
                                "You MUST retry the failed operations with corrected parameters. "
                                "Do NOT give up - fix the errors and try again."
                            )
                            self.messages.append({"role": "user", "content": retry_instruction})
                            continue  # Force next iteration

                        # No tool calls in this iteration - assume complete
                        logger.info(f"[ReActAgent] No tool calls in iteration {iteration}, assuming complete")
                        yield {
                            'type': 'complete',
                            'data': {
                                'success': True,
                                'iterations': iteration,
                                'final_response': conversational_text or response,
                                'tool_calls_made': self.tool_calls_count,
                                'completion_reason': 'no_more_actions',
                                'resource_stats': limits.get_stats(run_id)
                            }
                        }
                        return

                except Exception as e:
                    logger.error(f"[ReActAgent] Iteration {iteration} error: {e}", exc_info=True)
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
                            'completion_reason': 'error',
                            'resource_stats': limits.get_stats(run_id)
                        }
                    }
                    return

        finally:
            # Cleanup per-run tracking data
            limits.cleanup_run(run_id)

    async def _execute_tool_calls(
        self,
        tool_calls: List[ToolCall],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Execute a list of tool calls (Actions in ReAct terminology).

        Args:
            tool_calls: List of ToolCall objects
            context: Execution context

        Returns:
            List of tool results (Observations in ReAct terminology)
        """
        if not self.tools:
            logger.error("[ReActAgent] No tool registry available")
            return [{
                "success": False,
                "error": "No tool registry available"
            } for _ in tool_calls]

        results = []

        for i, tool_call in enumerate(tool_calls):
            # Handle parse errors specially
            if tool_call.name == "__parse_error__":
                logger.warning(f"[ReActAgent] Parse error detected for tool: {tool_call.parameters.get('tool_name')}")
                result = {
                    "success": False,
                    "tool": tool_call.parameters.get('tool_name', 'unknown'),
                    "error": "Tool call parsing failed - Invalid JSON format",
                    "result": {
                        "message": f"Failed to parse tool call for '{tool_call.parameters.get('tool_name', 'unknown')}'",
                        "error_details": tool_call.parameters.get('error'),
                        "problematic_json": tool_call.parameters.get('raw_params', ''),
                        "suggestion": tool_call.parameters.get('suggestion', ''),
                        "required_action": "You MUST retry this tool call with valid JSON. Fix the formatting errors and try again."
                    }
                }
                results.append(result)
                continue

            logger.info(f"[ReActAgent] Executing action {i+1}/{len(tool_calls)}: {tool_call.name}")

            result = await self.tools.execute(
                tool_name=tool_call.name,
                parameters=tool_call.parameters,
                context=context
            )

            results.append(result)

            # Log result (Observation)
            if result.get("success", False):
                logger.info(f"[ReActAgent] Action {tool_call.name} succeeded")
            else:
                logger.warning(f"[ReActAgent] Action {tool_call.name} failed: {result.get('error')}")

        return results

    def _format_tool_results(self, results: List[Dict[str, Any]]) -> str:
        """
        Format tool results (Observations) for feeding back to the model.

        Args:
            results: List of tool execution results

        Returns:
            Formatted string with observations
        """
        MAX_OUTPUT_LENGTH = 10000
        MAX_PREVIEW_LENGTH = 5000

        formatted = ["Observation:\n"]

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

                    # Handle content/stdout/output with intelligent truncation
                    output_field = None
                    output_content = None

                    for field in ["content", "stdout", "output", "preview"]:
                        if field in tool_result:
                            output_field = field
                            output_content = tool_result[field]
                            break

                    if output_content:
                        if len(output_content) > MAX_OUTPUT_LENGTH:
                            # Truncate with warning - show head and tail
                            elided_chars = len(output_content) - MAX_OUTPUT_LENGTH
                            formatted.append(f"   <warning>Output truncated: {elided_chars} characters elided</warning>")
                            formatted.append(f"   <suggestion>Try using head, tail, grep, or sed for more selective output</suggestion>")
                            formatted.append(f"   <{output_field}_head>")
                            for line in output_content[:MAX_PREVIEW_LENGTH].split('\n'):
                                formatted.append(f"   | {line}")
                            formatted.append(f"   </{output_field}_head>")
                            formatted.append(f"   <elided>{elided_chars} characters</elided>")
                            formatted.append(f"   <{output_field}_tail>")
                            for line in output_content[-MAX_PREVIEW_LENGTH:].split('\n'):
                                formatted.append(f"   | {line}")
                            formatted.append(f"   </{output_field}_tail>")
                        else:
                            # Normal output - not truncated
                            formatted.append(f"   {output_field}:")
                            for line in output_content.split('\n'):
                                formatted.append(f"   | {line}")

                    # Show files list (for directory listings)
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

                    # Show directory (for directory context)
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
                # Tools use "message" key for errors, but some might use "error"
                # Check result["result"]["message"] first (tool output), then result["error"] (executor error)
                error = None
                if isinstance(result.get("result"), dict) and "message" in result["result"]:
                    error = result["result"]["message"]
                else:
                    error = result.get("error", "Unknown error")
                formatted.append(f"   Error: {error}")

                # Show suggestion from result if available
                if isinstance(result.get("result"), dict):
                    # Show required action FIRST (most important)
                    if "required_action" in result["result"]:
                        formatted.append(f"   ⚠️ REQUIRED ACTION: {result['result']['required_action']}")

                    if "suggestion" in result["result"]:
                        formatted.append(f"   Suggestion: {result['result']['suggestion']}")

                    # Show parse error details prominently
                    if "error_details" in result["result"]:
                        formatted.append(f"   Details: {result['result']['error_details']}")

                    if "problematic_json" in result["result"] and result["result"]["problematic_json"]:
                        formatted.append(f"   Problematic JSON (first 300 chars):")
                        formatted.append(f"   {result['result']['problematic_json'][:300]}")

        return "\n".join(formatted)

    def _get_system_prompt(self, context: Dict[str, Any]) -> str:
        """
        Build the complete system prompt for the ReAct agent.

        The prompt has two parts:
        1. Agent's custom system prompt (with marker substitution) emphasizing ReAct methodology
        2. Tool information (available tools, formatting, usage rules)

        Args:
            context: Execution context for marker substitution

        Returns:
            Complete system prompt string
        """
        prompt_parts = []

        # Add agent's custom system prompt with marker substitution
        if self.system_prompt and self.system_prompt.strip():
            processed_prompt = self.get_processed_system_prompt(context)
            prompt_parts.append(processed_prompt)

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
            "\n\n=== REACT METHODOLOGY: REASONING + ACTING ===",
            "",
            "You must follow the ReAct paradigm: Thought → Action → Observation.",
            "",
            "1. THOUGHT: Explain your reasoning about what to do next and why.",
            "2. ACTION: Execute tools (formatted as JSON) to gather information or make changes.",
            "3. OBSERVATION: You will receive results from your actions.",
            "4. Repeat this cycle until the task is complete.",
            "",
            "CRITICAL: Every action MUST be preceded by a THOUGHT section explaining your reasoning.",
            "",
            "JSON Formatting Rules (MUST FOLLOW):",
            "1. ALL quotes inside string values MUST be escaped with backslash: \\\"",
            "2. Newlines must be escaped as \\n, tabs as \\t, backslashes as \\\\",
            "3. Use only double quotes for JSON strings, never single quotes",
            "4. Ensure proper JSON syntax: commas between properties, matching braces",
            "",
            "Escaping Examples:",
            '{"description": "The video for \\"Never Gonna Give You Up\\" by Rick Astley"}',
            '{"message": "Line 1\\nLine 2\\nLine 3"}',
            '{"path": "C:\\\\Users\\\\Documents\\\\file.txt"}',
            "",
            "ReAct Format (Single Action):",
            "",
            "THOUGHT: I need to understand the current file structure to locate the main application file.",
            "",
            '{',
            '  "tool_name": "read_file",',
            '  "parameters": {',
            '    "file_path": "src/App.jsx"',
            '  }',
            '}',
            "",
            "ReAct Format (Multiple Actions):",
            "",
            "THOUGHT: I'll read the App.jsx file and check the project dependencies to understand the current setup.",
            "",
            '[',
            '  {',
            '    "tool_name": "read_file",',
            '    "parameters": {',
            '      "file_path": "src/App.jsx"',
            '    }',
            '  },',
            '  {',
            '    "tool_name": "bash_exec",',
            '    "parameters": {',
            '      "command": "cat package.json"',
            '    }',
            '  }',
            ']',
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

            # Add examples if available
            if hasattr(tool, 'examples') and tool.examples:
                tools_text.append("Examples:")
                tools_text.append("")
                for example in tool.examples:
                    tools_text.append(f"  {example}")
                    tools_text.append("")

        tools_text.extend([
            "ReAct Rules and Constraints:",
            "",
            "Explicit Reasoning: ALWAYS include a THOUGHT section before actions explaining your reasoning.",
            "",
            "Wait for Observation: ALWAYS wait for the observation from your previous action before issuing the next command. Do not assume the outcome of any action.",
            "",
            "Conciseness: Be professional and concise. Do not provide conversational filler.",
            "",
            "File Modifications: Read files before modifying them to understand their current state.",
            "",
            "Output Truncation: Be aware that long command outputs or file contents may be truncated to preserve context space. You will be notified if this happens.",
            "",
            "",
            "Task Completion:",
            "",
            "Output TASK_COMPLETE when you have fully satisfied the user's original request. Do NOT mark complete just because an action succeeded. Verify the entire task is done."
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
