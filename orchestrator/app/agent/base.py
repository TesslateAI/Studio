"""
Abstract Base Agent

Defines the core interface that all agents must implement.
This enables a plug-and-play marketplace system where any agent type
can be dynamically instantiated and executed.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any, Optional
from .tools.registry import ToolRegistry
from .prompts import substitute_markers


class AbstractAgent(ABC):
    """
    The abstract base class that all agents must implement.
    This defines the common interface for running an agent.

    All agents must be able to:
    1. Be initialized with a system prompt and optional tools
    2. Run asynchronously and yield events back to the client
    3. Accept user requests and context for execution
    """

    def __init__(self, system_prompt: str, tools: Optional[ToolRegistry] = None):
        """
        Initialize the agent.

        Args:
            system_prompt: The core instructions for the AI model.
            tools: A ToolRegistry instance containing only the tools this agent can use.
                   If None, the agent does not require tool access.
        """
        self.system_prompt = system_prompt
        self.tools = tools

    def get_processed_system_prompt(self, context: Dict[str, Any]) -> str:
        """
        Get the system prompt with markers substituted based on runtime context.

        This method should be called by agent implementations whenever they need
        to use the system prompt, to ensure markers like {mode}, {mode_instructions},
        {project_name}, etc. are replaced with actual values.

        Args:
            context: Execution context containing edit_mode, project_context, etc.

        Returns:
            System prompt with all {marker} placeholders replaced
        """
        tool_names = list(self.tools._tools.keys()) if self.tools else None
        return substitute_markers(self.system_prompt, context, tool_names)

    @abstractmethod
    async def run(
        self,
        user_request: str,
        context: Dict[str, Any]
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Run the agent's logic. This is an async generator that yields events.

        This method must be implemented by all concrete agent classes.
        The agent should process the user's request and yield events back
        to the caller as it progresses.

        Args:
            user_request: The user's message/prompt.
            context: A dictionary containing execution context:
                - user: User object
                - user_id: User ID
                - project_id: Project ID
                - db: AsyncSession for database operations
                - project_context_str: String with project context (optional)
                - tesslate_context: TESSLATE.md content (optional)
                - git_context: Git repository information (optional)

        Yields:
            Dictionary events with different types:
            - {'type': 'stream', 'content': '...'} - Text chunks for streaming
            - {'type': 'agent_step', 'data': {...}} - Agent iteration steps
            - {'type': 'file_ready', 'file_path': '...', 'content': '...'} - File saved
            - {'type': 'status', 'content': '...'} - Status updates
            - {'type': 'complete', 'data': {...}} - Task completion
            - {'type': 'error', 'content': '...'} - Error messages

        Example:
            async def run(self, user_request: str, context: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
                yield {'type': 'status', 'content': 'Starting task...'}
                # ... do work ...
                yield {'type': 'stream', 'content': 'Processing...'}
                # ... more work ...
                yield {'type': 'complete', 'data': {'result': 'success'}}
        """
        # This is an abstract method, so it must be implemented by subclasses.
        # The `yield` here is just to make Python recognize it as an async generator.
        yield {}
