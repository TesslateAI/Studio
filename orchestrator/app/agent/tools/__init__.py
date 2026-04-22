"""Agent tool registry and execution primitives."""

from __future__ import annotations

from .approval_manager import ApprovalManager, get_approval_manager
from .output_formatter import (
    error_output,
    format_file_size,
    pluralize,
    strip_ansi_codes,
    success_output,
    truncate_session_id,
)
from .registry import (
    Tool,
    ToolCategory,
    ToolRegistry,
    create_scoped_tool_registry,
    get_tool_registry,
)
from .retry_config import (
    create_custom_retry,
    create_retry_decorator,
    is_retryable_error,
    tool_retry,
    tool_retry_aggressive,
    tool_retry_gentle,
)

__all__ = [
    "ApprovalManager",
    "get_approval_manager",
    "error_output",
    "format_file_size",
    "pluralize",
    "strip_ansi_codes",
    "success_output",
    "truncate_session_id",
    "Tool",
    "ToolCategory",
    "ToolRegistry",
    "create_scoped_tool_registry",
    "get_tool_registry",
    "create_custom_retry",
    "create_retry_decorator",
    "is_retryable_error",
    "tool_retry",
    "tool_retry_aggressive",
    "tool_retry_gentle",
]
