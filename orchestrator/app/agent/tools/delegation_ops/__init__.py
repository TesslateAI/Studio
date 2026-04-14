"""
Delegation Operations Module

First-party subagent orchestration tools. Exposes ``task``, ``wait_agent``,
``send_message_to_agent``, ``close_agent``, and ``list_agents``. The parent
tool registry wires these in via ``register_delegation_ops_tools``.
"""

from .agent_registry import (
    MAX_SUBAGENT_DEPTH,
    SUBAGENT_REGISTRY,
    SubagentRecord,
    SubagentRegistry,
)
from .task_tool import (
    close_agent_executor,
    list_agents_executor,
    register_delegation_ops_tools,
    send_message_to_agent_executor,
    task_executor,
    wait_agent_executor,
)

__all__ = [
    "MAX_SUBAGENT_DEPTH",
    "SUBAGENT_REGISTRY",
    "SubagentRecord",
    "SubagentRegistry",
    "close_agent_executor",
    "list_agents_executor",
    "register_delegation_ops_tools",
    "send_message_to_agent_executor",
    "task_executor",
    "wait_agent_executor",
]
