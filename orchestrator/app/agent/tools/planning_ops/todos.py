"""
Todo Planning Tools

Tools for managing agent task lists and planning.
Stores todos in-memory per conversation session.
"""

import logging
from typing import Dict, Any, List
from datetime import datetime
from uuid import UUID

from ..registry import Tool, ToolCategory
from ..output_formatter import success_output, error_output, pluralize

logger = logging.getLogger(__name__)

# In-memory storage for todos (keyed by conversation_id or session_id)
# In production, you might want to persist this to database
_todo_storage: Dict[str, List[Dict[str, Any]]] = {}


def _get_session_key(context: Dict[str, Any]) -> str:
    """Generate a unique key for the current session."""
    # Use user_id + project_id as session key
    # In production, you might have a conversation_id in context
    user_id = context.get("user_id")
    project_id = context.get("project_id")
    return f"user_{user_id}_project_{project_id}"


async def todo_read_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Read the current todo list for this session.

    Args:
        params: {} (no parameters)
        context: {user_id: UUID, project_id: str}

    Returns:
        Dict with list of todos
    """
    session_key = _get_session_key(context)
    todos = _todo_storage.get(session_key, [])

    # Count by status
    pending = sum(1 for t in todos if t["status"] == "pending")
    in_progress = sum(1 for t in todos if t["status"] == "in_progress")
    completed = sum(1 for t in todos if t["status"] == "completed")

    if not todos:
        message = "No todos in current session"
    else:
        message = f"Found {len(todos)} todos: {completed} completed, {in_progress} in progress, {pending} pending"

    return success_output(
        message=message,
        todos=todos,
        details={
            "total": len(todos),
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed
        }
    )


async def todo_write_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Write/update the todo list for this session.

    This completely replaces the existing todo list. To add a single todo,
    read the list first, append your new todo, then write the updated list.

    Args:
        params: {
            todos: [
                {
                    content: str,  # Task description
                    status: "pending" | "in_progress" | "completed",
                    priority: "high" | "medium" | "low"  # Optional
                }
            ]
        }
        context: {user_id: UUID, project_id: str}

    Returns:
        Dict with success status
    """
    todos = params.get("todos", [])

    if not isinstance(todos, list):
        raise ValueError("todos must be a list")

    # Validate todo structure
    for i, todo in enumerate(todos):
        if not isinstance(todo, dict):
            raise ValueError(f"Todo {i} must be an object")
        if "content" not in todo:
            raise ValueError(f"Todo {i} is missing 'content' field")
        if "status" not in todo:
            raise ValueError(f"Todo {i} is missing 'status' field")

        # Validate status
        valid_statuses = ["pending", "in_progress", "completed"]
        if todo["status"] not in valid_statuses:
            raise ValueError(f"Todo {i} has invalid status. Must be one of: {valid_statuses}")

        # Add default priority if missing
        if "priority" not in todo:
            todo["priority"] = "medium"

        # Add timestamps if missing
        if "created_at" not in todo:
            todo["created_at"] = datetime.utcnow().isoformat()

        # Add ID if missing
        if "id" not in todo:
            todo["id"] = f"todo_{i}_{datetime.utcnow().timestamp()}"

    # Store todos
    session_key = _get_session_key(context)
    _todo_storage[session_key] = todos

    # Count by status
    pending = sum(1 for t in todos if t["status"] == "pending")
    in_progress = sum(1 for t in todos if t["status"] == "in_progress")
    completed = sum(1 for t in todos if t["status"] == "completed")

    return success_output(
        message=f"Updated todo list: {len(todos)} total ({completed} completed, {in_progress} in progress, {pending} pending)",
        todos=todos,
        details={
            "total": len(todos),
            "pending": pending,
            "in_progress": in_progress,
            "completed": completed
        }
    )


def register_planning_tools(registry):
    """Register todo planning tools."""

    registry.register(Tool(
        name="todo_read",
        description="Read the current todo list for this session. Useful for checking progress and planning next steps.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        },
        executor=todo_read_tool,
        category=ToolCategory.PROJECT,  # Using PROJECT category since there's no PLANNING category
        examples=[
            '<tool_call><tool_name>todo_read</tool_name><parameters>{}</parameters></tool_call>'
        ]
    ))

    registry.register(Tool(
        name="todo_write",
        description="Write/update the complete todo list for this session. Replaces existing todos. Use for planning multi-step tasks and tracking progress.",
        parameters={
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "Complete list of todos",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Task description"
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Current status of the task"
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                                "description": "Task priority (optional, default: medium)"
                            }
                        },
                        "required": ["content", "status"]
                    }
                }
            },
            "required": ["todos"]
        },
        executor=todo_write_tool,
        category=ToolCategory.PROJECT,
        examples=[
            '<tool_call><tool_name>todo_write</tool_name><parameters>{"todos": [{"content": "Read package.json", "status": "completed"}, {"content": "Update dependencies", "status": "in_progress"}, {"content": "Run tests", "status": "pending", "priority": "high"}]}</parameters></tool_call>'
        ]
    ))

    logger.info("Registered 2 todo planning tools")
