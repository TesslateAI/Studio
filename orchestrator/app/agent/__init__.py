"""
Universal Agent System

Model-agnostic agent that uses prompt engineering and regex parsing
to enable tool calling with ANY LLM (not just function-calling models).

"""

from .agent import UniversalAgent
from .tools.registry import ToolRegistry, get_tool_registry

__all__ = ["UniversalAgent", "ToolRegistry", "get_tool_registry"]
