"""
Agent Factory

Dynamically creates agent instances from database configurations.
This is the central point for instantiating any type of agent in the marketplace.

The factory:
1. Maps agent_type strings to Python classes
2. Creates scoped tool registries if needed
3. Instantiates and returns the appropriate agent
"""

import logging
from typing import Dict, Type, Optional

from .base import AbstractAgent
from .stream_agent import StreamAgent
from .iterative_agent import IterativeAgent
from .tools.registry import create_scoped_tool_registry, get_tool_registry
from ..models import MarketplaceAgent as MarketplaceAgentModel

logger = logging.getLogger(__name__)


# Map agent_type string from DB to Python class
AGENT_CLASS_MAP: Dict[str, Type[AbstractAgent]] = {
    "StreamAgent": StreamAgent,
    "IterativeAgent": IterativeAgent,
    # Add new agent types here as you create them!
    # Example:
    # "ReActAgent": ReActAgent,
    # "PlannerAgent": PlannerAgent,
}


async def create_agent_from_db_model(
    agent_model: MarketplaceAgentModel,
    model_adapter=None
) -> AbstractAgent:
    """
    Factory function to create an agent instance from its database model.

    This function:
    1. Looks up the agent class based on agent_type
    2. Creates a scoped tool registry if tools are specified
    3. Instantiates the agent with the appropriate configuration
    4. Returns the ready-to-use agent instance

    Args:
        agent_model: The MarketplaceAgent database model
        model_adapter: Optional ModelAdapter for IterativeAgent

    Returns:
        An instantiated agent ready to run

    Raises:
        ValueError: If the agent_type is not recognized or system_prompt is missing

    Example:
        >>> agent_model = await db.get(MarketplaceAgent, 1)
        >>> agent = await create_agent_from_db_model(agent_model)
        >>> async for event in agent.run("Build a login page", context):
        ...     print(event)
    """
    agent_type_str = agent_model.agent_type

    # Validate that agent has a system prompt
    if not agent_model.system_prompt or not agent_model.system_prompt.strip():
        raise ValueError(
            f"Agent '{agent_model.name}' (slug: {agent_model.slug}) does not have a system prompt. "
            f"All agents must have a non-empty system_prompt to function."
        )

    # Look up the agent class
    AgentClass = AGENT_CLASS_MAP.get(agent_type_str)

    if not AgentClass:
        available_types = ", ".join(AGENT_CLASS_MAP.keys())
        raise ValueError(
            f"Unknown agent type '{agent_type_str}'. "
            f"Available types: {available_types}"
        )

    logger.info(f"[AgentFactory] Creating agent '{agent_model.name}' of type '{agent_type_str}'")

    # Create scoped tool registry if tools are defined
    tools = None
    if agent_model.tools:
        logger.info(f"[AgentFactory] Creating scoped tool registry with tools: {agent_model.tools}")
        tools = create_scoped_tool_registry(agent_model.tools)
    else:
        # For IterativeAgent, use global registry if no specific tools defined
        if agent_type_str == "IterativeAgent":
            logger.info(f"[AgentFactory] Using global tool registry for IterativeAgent")
            tools = get_tool_registry()

    # Instantiate the agent
    # Different agent types may have different initialization requirements
    if agent_type_str == "StreamAgent":
        agent = StreamAgent(
            system_prompt=agent_model.system_prompt,
            tools=tools  # StreamAgent doesn't use tools, but we pass it for consistency
        )
    elif agent_type_str == "IterativeAgent":
        agent = IterativeAgent(
            system_prompt=agent_model.system_prompt,
            tools=tools,
            model=model_adapter  # IterativeAgent needs a model adapter
        )
    else:
        # Generic instantiation for future agent types
        agent = AgentClass(
            system_prompt=agent_model.system_prompt,
            tools=tools
        )

    logger.info(
        f"[AgentFactory] Successfully created {agent_type_str} "
        f"for agent '{agent_model.name}' (slug: {agent_model.slug})"
    )

    if tools:
        logger.info(f"[AgentFactory] Agent has access to {len(tools._tools)} tools")

    return agent


def register_agent_type(agent_type: str, agent_class: Type[AbstractAgent]):
    """
    Register a new agent type in the factory.

    This allows dynamic registration of agent types at runtime,
    useful for plugins or extensions.

    Args:
        agent_type: The string identifier for the agent type
        agent_class: The Python class that implements AbstractAgent

    Example:
        >>> from my_agents import CustomAgent
        >>> register_agent_type("CustomAgent", CustomAgent)
    """
    if agent_type in AGENT_CLASS_MAP:
        logger.warning(f"[AgentFactory] Overwriting existing agent type: {agent_type}")

    AGENT_CLASS_MAP[agent_type] = agent_class
    logger.info(f"[AgentFactory] Registered agent type: {agent_type}")


def get_available_agent_types() -> list[str]:
    """
    Get a list of all available agent types.

    Returns:
        List of agent type strings
    """
    return list(AGENT_CLASS_MAP.keys())


def get_agent_class(agent_type: str) -> Optional[Type[AbstractAgent]]:
    """
    Get the agent class for a given agent type.

    Args:
        agent_type: The agent type string

    Returns:
        The agent class, or None if not found
    """
    return AGENT_CLASS_MAP.get(agent_type)
