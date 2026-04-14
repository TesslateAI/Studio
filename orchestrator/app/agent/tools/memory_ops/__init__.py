"""
Memory Operations Module

Persistent, cross-session agent memory stored as sectioned markdown.

Exports:
    - ``MemoryStore``: Async, lock-safe read/write/list API.
    - ``register_memory_ops_tools``: Register ``memory_read`` and
      ``memory_write`` on a ``ToolRegistry``.
    - ``load_memory_prefix``: Synchronous helper that returns the
      project's persistent-memory block wrapped for injection into an
      agent system prompt at startup.
"""

from .memory_tool import (
    MemoryStore,
    load_memory_prefix,
    memory_read_tool,
    memory_write_tool,
    register_memory_ops_tools,
)

__all__ = [
    "MemoryStore",
    "load_memory_prefix",
    "memory_read_tool",
    "memory_write_tool",
    "register_memory_ops_tools",
]
