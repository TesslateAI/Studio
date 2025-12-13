"""
Tool Registry System

Manages available tools for the agent and handles tool execution.
Each tool is defined with name, description, parameters schema, and executor function.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Any, List, Optional
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """Tool categories for organization."""
    FILE_OPS = "file_operations"
    SHELL = "shell_commands"
    PROJECT = "project_management"
    BUILD = "build_operations"


@dataclass
class Tool:
    """
    Represents a tool that the agent can use.

    Attributes:
        name: Unique tool identifier
        description: What the tool does (shown to LLM)
        parameters: JSON schema for parameters
        executor: Async function that executes the tool
        category: Tool category
        examples: Example usage patterns
        system_prompt: Optional additional instructions for this tool
    """
    name: str
    description: str
    parameters: Dict[str, Any]
    executor: Callable
    category: ToolCategory
    examples: Optional[List[str]] = None
    system_prompt: Optional[str] = None

    def to_prompt_format(self) -> str:
        """Convert tool to format suitable for LLM system prompt."""
        param_descriptions = []
        for param_name, param_info in self.parameters.get("properties", {}).items():
            required = param_name in self.parameters.get("required", [])
            req_str = "required" if required else "optional"
            param_type = param_info.get("type", "string")
            desc = param_info.get("description", "")
            param_descriptions.append(f"  - {param_name} ({param_type}, {req_str}): {desc}")

        params_text = "\n".join(param_descriptions) if param_descriptions else "  No parameters"

        examples_text = ""
        if self.examples:
            examples_text = "\n  Examples:\n    " + "\n    ".join(self.examples)

        system_prompt_text = ""
        if self.system_prompt:
            system_prompt_text = f"\n  Instructions: {self.system_prompt}"

        return f"""
{self.name}: {self.description}
  Parameters:
{params_text}{examples_text}{system_prompt_text}
""".strip()


class ToolRegistry:
    """
    Registry of all available tools for the agent.

    Manages tool registration, lookup, and execution with proper error handling.
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        logger.info("ToolRegistry initialized")

    def register(self, tool: Tool):
        """Register a new tool."""
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool: {tool.name}")
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name} (category: {tool.category.value})")

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self, category: Optional[ToolCategory] = None) -> List[Tool]:
        """
        List all tools, optionally filtered by category.

        Args:
            category: Optional category filter

        Returns:
            List of Tool objects
        """
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    def get_system_prompt_section(self) -> str:
        """
        Generate the tools section for the system prompt.

        Returns:
            Formatted string describing all available tools
        """
        sections = []

        # Group by category
        for category in ToolCategory:
            tools = self.list_tools(category)
            if tools:
                sections.append(f"\n## {category.value.replace('_', ' ').title()}\n")
                for i, tool in enumerate(tools, 1):
                    sections.append(f"{i}. {tool.to_prompt_format()}\n")

        return "\n".join(sections)

    async def execute(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool with given parameters.

        Args:
            tool_name: Name of tool to execute
            parameters: Tool parameters
            context: Execution context (user_id, project_id, db session, edit_mode, etc.)

        Returns:
            Dict with success status and result/error
        """
        tool = self.get(tool_name)

        if not tool:
            logger.error(f"Unknown tool: {tool_name}")
            return {
                "success": False,
                "error": f"Unknown tool '{tool_name}'. Available tools: {', '.join(self._tools.keys())}"
            }

        # ============================================================================
        # Edit Mode Control - Applies to ALL agents
        # ============================================================================
        edit_mode = context.get('edit_mode', 'ask')  # Default to 'ask' mode

        # Define dangerous tools that require special handling
        DANGEROUS_TOOLS = {
            'write_file', 'patch_file', 'multi_edit',  # File modifications
            'bash_exec', 'shell_exec', 'shell_open',   # Shell operations
            'web_fetch',                                # Web operations (can leak data)
            # 'todo_write' excluded - safe planning operation
        }

        is_dangerous = tool_name in DANGEROUS_TOOLS

        # Plan Mode: Block all dangerous operations
        if edit_mode == 'plan' and is_dangerous:
            logger.warning(f"[PLAN MODE] Blocked tool execution: {tool_name}")
            return {
                "success": False,
                "tool": tool_name,
                "error": f"Plan mode active - {tool_name} is disabled. You can only read files and gather information. Explain what changes you would make instead."
            }

        # Ask Mode: Check if approval needed (unless explicitly skipped)
        skip_approval = context.get('skip_approval_check', False)
        if edit_mode == 'ask' and is_dangerous and not skip_approval:
            from .approval_manager import get_approval_manager
            approval_mgr = get_approval_manager()

            # Get session_id from context (use chat_id)
            session_id = context.get('chat_id', 'default')

            # Check if tool type already approved for this session
            if not approval_mgr.is_tool_approved(session_id, tool_name):
                # Need approval - return special result
                logger.info(f"[ASK MODE] Approval required for {tool_name} in session {session_id}")
                return {
                    "approval_required": True,
                    "tool": tool_name,
                    "parameters": parameters,
                    "session_id": session_id
                }
            else:
                logger.info(f"[ASK MODE] Tool {tool_name} already approved for session {session_id}")
        elif edit_mode == 'ask' and is_dangerous and skip_approval:
            logger.info(f"[ASK MODE] Skipping approval check for {tool_name} (approval granted)")

        try:
            logger.info(f"Executing tool: {tool_name} with params: {parameters} [edit_mode={edit_mode}]")

            # Execute the tool
            result = await tool.executor(parameters, context)

            # Check if the tool itself reported success/failure
            # Tools return dicts with "success" field to indicate operation status
            tool_succeeded = result.get("success", True) if isinstance(result, dict) else True

            if tool_succeeded:
                logger.info(f"Tool {tool_name} executed successfully")
            else:
                logger.warning(f"Tool {tool_name} executed but reported failure: {result.get('message', 'Unknown error')}")

            return {
                "success": tool_succeeded,
                "tool": tool_name,
                "result": result
            }

        except Exception as e:
            logger.error(f"Tool {tool_name} execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "tool": tool_name,
                "error": str(e)
            }


# Global registry instance
_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry instance."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        # Register all tools
        _register_all_tools(_registry)
    return _registry


def _register_all_tools(registry: ToolRegistry):
    """Register all essential tools from modular structure."""
    from .file_ops import register_all_file_tools
    from .shell_ops import register_all_shell_tools
    from .project_ops import register_all_project_tools
    from .planning_ops import register_all_planning_tools
    from .web_ops import register_all_web_tools

    # Register essential tools (use bash_exec for file listing, globbing, grepping)
    register_all_file_tools(registry)      # 4 tools: read_file, write_file, patch_file, multi_edit
    register_all_shell_tools(registry)     # 4 tools: bash_exec, shell_open, shell_exec, shell_close
    register_all_project_tools(registry)   # 1 tool: get_project_info
    register_all_planning_tools(registry)  # 2 tools: todo_read, todo_write
    register_all_web_tools(registry)       # 1 tool: web_fetch

    logger.info(f"Registered {len(registry._tools)} essential tools total")


def create_scoped_tool_registry(
    tool_names: List[str],
    tool_configs: Optional[Dict[str, Dict[str, Any]]] = None
) -> ToolRegistry:
    """
    Create a ToolRegistry containing only the specified tools with optional custom configurations.

    This enables agents to have restricted tool access with customized tool descriptions
    and examples, improving security and making agents more focused on their specific tasks.

    Args:
        tool_names: List of tool names to include in the scoped registry
        tool_configs: Optional dict mapping tool names to custom configs
                     Example: {"read_file": {"description": "...", "examples": [...]}}

    Returns:
        A new ToolRegistry instance with only the specified tools

    Example:
        >>> configs = {"read_file": {"description": "Read project files"}}
        >>> registry = create_scoped_tool_registry(["read_file", "write_file"], configs)
        >>> # This registry has file tools with customized descriptions
    """
    from dataclasses import replace

    scoped_registry = ToolRegistry()
    global_registry = get_tool_registry()
    tool_configs = tool_configs or {}

    missing_tools = []
    for name in tool_names:
        tool = global_registry.get(name)
        if tool:
            # Apply custom configuration if provided
            if name in tool_configs:
                config = tool_configs[name]
                custom_description = config.get("description", tool.description)
                custom_examples = config.get("examples", tool.examples)
                custom_system_prompt = config.get("system_prompt", tool.system_prompt)

                # Create a copy of the tool with custom description, examples, and system_prompt
                custom_tool = replace(
                    tool,
                    description=custom_description,
                    examples=custom_examples,
                    system_prompt=custom_system_prompt
                )
                scoped_registry.register(custom_tool)
                logger.info(f"Registered tool '{name}' with custom configuration")
            else:
                scoped_registry.register(tool)
        else:
            missing_tools.append(name)
            logger.warning(f"Tool '{name}' not found in global registry")

    if missing_tools:
        logger.warning(
            f"Could not add {len(missing_tools)} tools to scoped registry: {missing_tools}"
        )

    logger.info(
        f"Created scoped tool registry with {len(scoped_registry._tools)} tools: "
        f"{list(scoped_registry._tools.keys())}"
    )

    return scoped_registry
