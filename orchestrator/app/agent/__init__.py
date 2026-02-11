"""
Agent System

Factory-based agent system where all agents go through the unified interface.

This module provides:
- AbstractAgent: Base class for all agents
- StreamAgent: Streaming text generation agent (WebSocket)
- IterativeAgent: Tool-calling agent with think-act-reflect loop (HTTP)
- ReActAgent: ReAct (Reasoning + Acting) agent with explicit reasoning steps
- TesslateAgent: Native function-calling agent with parallel execution and subagents
- AgentFactory: Creates agents from database configurations
"""

from .base import AbstractAgent
from .factory import create_agent_from_db_model, get_available_agent_types, register_agent_type
from .iterative_agent import IterativeAgent
from .react_agent import ReActAgent
from .stream_agent import StreamAgent
from .tesslate_agent import TesslateAgent
from .tools.registry import ToolRegistry, create_scoped_tool_registry, get_tool_registry

__all__ = [
    # Core agent classes
    "AbstractAgent",
    "StreamAgent",
    "IterativeAgent",
    "ReActAgent",
    "TesslateAgent",
    # Factory functions
    "create_agent_from_db_model",
    "register_agent_type",
    "get_available_agent_types",
    # Tool registry
    "ToolRegistry",
    "get_tool_registry",
    "create_scoped_tool_registry",
]
