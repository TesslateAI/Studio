"""
View-scoped tool registry.

This module provides a tool registry that filters tools based on the active
view context. It wraps the base ToolRegistry using the decorator pattern,
adding view-scoping behavior without modifying the base implementation.
"""

import logging
from typing import Dict, List, Optional, Any

from .registry import Tool, ToolRegistry, ToolCategory
from .view_context import ViewContext
from .providers.base import AbstractToolProvider

logger = logging.getLogger(__name__)


class ViewScopedToolRegistry:
    """
    A tool registry that filters tools based on the active view context.

    This registry:
    1. Wraps the base ToolRegistry (always available tools)
    2. Maintains providers for each view context
    3. Filters available tools based on current active view
    4. Caches compiled registries for performance

    The decorator pattern allows view-scoping without modifying existing tools.
    """

    def __init__(self, base_registry: Optional[ToolRegistry] = None):
        """
        Initialize with optional base registry for core tools.

        Args:
            base_registry: Base tools always available (file_ops, etc.)
                          If None, uses global registry.
        """
        from .registry import get_tool_registry
        self._base_registry = base_registry or get_tool_registry()
        self._providers: Dict[ViewContext, AbstractToolProvider] = {}
        self._active_view: ViewContext = ViewContext.BUILDER
        self._view_tools_cache: Dict[ViewContext, List[Tool]] = {}

    def register_provider(self, provider: AbstractToolProvider):
        """
        Register a tool provider for a specific view context.

        Args:
            provider: Tool provider instance
        """
        view_context = provider.get_view_context()
        self._providers[view_context] = provider
        # Invalidate cache for this view
        self._view_tools_cache.pop(view_context, None)
        logger.info(f"Registered tool provider for view: {view_context.value}")

    def set_active_view(self, view: ViewContext):
        """
        Set the currently active view context.

        Args:
            view: ViewContext to make active
        """
        self._active_view = view
        logger.debug(f"Active view set to: {view.value}")

    def get_active_view(self) -> ViewContext:
        """Get the currently active view context."""
        return self._active_view

    def get_available_tools(self) -> List[Tool]:
        """
        Get all tools available in the current view context.

        Returns:
            List of Tool instances (base tools + view-specific tools)
        """
        # Check cache first
        if self._active_view in self._view_tools_cache:
            return self._view_tools_cache[self._active_view]

        # Start with base tools (always available)
        tools = list(self._base_registry.list_tools())

        # Add view-specific tools from provider
        if self._active_view in self._providers:
            provider = self._providers[self._active_view]
            view_tools = provider.get_tools()
            tools.extend(view_tools)
            logger.debug(
                f"Added {len(view_tools)} tools from {self._active_view.value} provider"
            )

        # Cache the result
        self._view_tools_cache[self._active_view] = tools

        return tools

    def get(self, name: str) -> Optional[Tool]:
        """
        Get a tool by name if available in current context.

        Args:
            name: Tool name to look up

        Returns:
            Tool instance or None if not found/not available
        """
        # Check base registry first
        tool = self._base_registry.get(name)
        if tool:
            return tool

        # Check active view provider
        if self._active_view in self._providers:
            provider = self._providers[self._active_view]
            for t in provider.get_tools():
                if t.name == name:
                    return t

        return None

    def is_tool_available(
        self,
        tool_name: str,
        context: Dict[str, Any]
    ) -> bool:
        """
        Check if a tool is available in the current view context.

        Args:
            tool_name: Name of the tool to check
            context: Execution context for dynamic checks

        Returns:
            True if tool is available, False otherwise
        """
        # Base tools are always available
        if self._base_registry.get(tool_name):
            return True

        # Check view-specific provider
        if self._active_view in self._providers:
            provider = self._providers[self._active_view]
            return provider.is_tool_available(tool_name, context)

        return False

    def list_tools(self, category: Optional[ToolCategory] = None) -> List[Tool]:
        """
        List all available tools, optionally filtered by category.

        Args:
            category: Optional category filter

        Returns:
            List of Tool objects
        """
        tools = self.get_available_tools()
        if category:
            return [t for t in tools if t.category == category]
        return tools

    async def execute(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool with view-context validation and approval checks.

        First validates the tool is available in current view,
        then applies approval checks for dangerous tools,
        then delegates to appropriate registry/provider.

        Args:
            tool_name: Name of tool to execute
            parameters: Tool parameters
            context: Execution context

        Returns:
            Dict with success status and result/error
        """
        # Check view-scoped availability
        if not self.is_tool_available(tool_name, context):
            # Tool not available in this view - determine appropriate error message

            # Base shell tools excluded from graph view (must use graph_shell_exec instead)
            GRAPH_EXCLUDED_SHELL_TOOLS = {
                'bash_exec': 'graph_shell_exec',
                'shell_exec': 'graph_shell_exec',
                'shell_open': 'graph_shell_open',
                'shell_close': 'graph_shell_close',
            }

            if self._active_view == ViewContext.GRAPH and tool_name in GRAPH_EXCLUDED_SHELL_TOOLS:
                # Base shell tool excluded from graph view
                alternative = GRAPH_EXCLUDED_SHELL_TOOLS[tool_name]
                message = (
                    f"Tool '{tool_name}' is NOT available in graph view because there's no single 'current container'. "
                    f"Use '{alternative}' with a container_id instead. "
                    f"Call 'graph_container_status' first to get container IDs."
                )
            else:
                # Use provider message for graph-specific tools or generic message
                provider = self._providers.get(self._active_view)
                message = (
                    provider.get_unavailable_message(tool_name)
                    if provider else
                    f"Tool '{tool_name}' is not available in {self._active_view.value} view"
                )

            logger.warning(f"Tool {tool_name} not available in {self._active_view.value} view")
            return {
                "success": False,
                "error": message,
                "view_context": self._active_view.value
            }

        # Add view context to execution context
        context["view_context"] = self._active_view.value

        # Check if this is a view-specific tool from a provider
        if self._active_view in self._providers:
            provider = self._providers[self._active_view]
            for tool in provider.get_tools():
                if tool.name == tool_name:
                    # ============================================================
                    # Approval checks for view-specific dangerous tools
                    # ============================================================
                    # Define dangerous view-specific tools that require approval
                    VIEW_DANGEROUS_TOOLS = {
                        'graph_shell_exec', 'graph_shell_open',  # Shell operations in containers
                        'graph_start_container', 'graph_stop_container',  # Container lifecycle
                        'graph_start_all', 'graph_stop_all',  # Bulk container operations
                        'graph_add_container', 'graph_remove_item',  # Grid modifications
                        'graph_add_connection', 'graph_add_browser_preview',  # Grid modifications
                    }

                    edit_mode = context.get('edit_mode', 'ask')
                    is_dangerous = tool_name in VIEW_DANGEROUS_TOOLS

                    # Plan Mode: Block all dangerous operations
                    if edit_mode == 'plan' and is_dangerous:
                        logger.warning(f"[PLAN MODE] Blocked view tool execution: {tool_name}")
                        return {
                            "success": False,
                            "tool": tool_name,
                            "error": f"Plan mode active - {tool_name} is disabled. Explain what you would do instead."
                        }

                    # Ask Mode: Check if approval needed
                    skip_approval = context.get('skip_approval_check', False)
                    if edit_mode == 'ask' and is_dangerous and not skip_approval:
                        from .approval_manager import get_approval_manager
                        approval_mgr = get_approval_manager()

                        session_id = str(context.get('chat_id', 'default'))

                        if not approval_mgr.is_tool_approved(session_id, tool_name):
                            logger.info(f"[ASK MODE] Approval required for {tool_name} in session {session_id}")
                            return {
                                "approval_required": True,
                                "tool": tool_name,
                                "parameters": parameters,
                                "session_id": session_id
                            }
                        else:
                            logger.info(f"[ASK MODE] Tool {tool_name} already approved for session {session_id}")

                    # Execute view-specific tool
                    logger.info(f"Executing view-specific tool: {tool_name} [edit_mode={edit_mode}]")
                    try:
                        result = await tool.executor(parameters, context)
                        # Return the result directly - don't double-wrap it
                        # Tool executors already return properly formatted output
                        return result
                    except Exception as e:
                        logger.error(f"Error executing {tool_name}: {e}", exc_info=True)
                        return {
                            "success": False,
                            "error": str(e)
                        }

        # Delegate to base registry for base tools (handles edit_mode, approvals, etc.)
        return await self._base_registry.execute(tool_name, parameters, context)

    def get_system_prompt_section(self) -> str:
        """
        Generate tools section filtered by current view context.

        Returns:
            Formatted string for system prompt with available tools
        """
        available_tools = self.get_available_tools()

        sections = []
        sections.append(f"\n## Current View: {self._active_view.value.title()}\n")

        # Group by category
        for category in ToolCategory:
            tools = [t for t in available_tools if t.category == category]
            if tools:
                sections.append(f"\n### {category.value.replace('_', ' ').title()}\n")
                for i, tool in enumerate(tools, 1):
                    sections.append(f"{i}. {tool.to_prompt_format()}\n")

        return "\n".join(sections)

    def invalidate_cache(self, view: Optional[ViewContext] = None):
        """
        Invalidate the tools cache.

        Args:
            view: Specific view to invalidate, or None for all
        """
        if view:
            self._view_tools_cache.pop(view, None)
        else:
            self._view_tools_cache.clear()

    @property
    def _tools(self) -> Dict[str, Tool]:
        """
        Property for compatibility with existing code expecting _tools dict.

        Returns:
            Dict mapping tool names to Tool instances
        """
        return {t.name: t for t in self.get_available_tools()}
