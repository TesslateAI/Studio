# Agent Factory

**File**: `orchestrator/app/agent/factory.py`

The agent factory is the central point for creating agent instances from database configurations. It maps agent type strings to Python classes and handles tool registry scoping.

## Overview

The factory pattern decouples agent creation from usage, enabling:
- Dynamic agent type selection from database
- Marketplace agent system
- Tool access control per agent
- Custom tool configurations

## AGENT_CLASS_MAP

Maps agent type strings (stored in database) to Python classes:

```python
AGENT_CLASS_MAP: Dict[str, Type[AbstractAgent]] = {
    "StreamAgent": StreamAgent,
    "IterativeAgent": IterativeAgent,
    "ReActAgent": ReActAgent,
    # Add new agent types here
}
```

### Adding New Agent Types

```python
# 1. Import your custom agent
from .my_custom_agent import MyCustomAgent

# 2. Register in the map
AGENT_CLASS_MAP["MyCustomAgent"] = MyCustomAgent

# 3. Now it can be instantiated from database
agent_model.agent_type = "MyCustomAgent"
agent = await create_agent_from_db_model(agent_model)
```

## create_agent_from_db_model

**Signature**:
```python
async def create_agent_from_db_model(
    agent_model: MarketplaceAgentModel,
    model_adapter=None,
    tools_override=None
) -> AbstractAgent
```

The main factory function that creates agent instances.

### Parameters

- **agent_model**: Database model from `marketplace_agents` table
  - `name`: Display name
  - `slug`: URL-safe identifier
  - `agent_type`: String key from AGENT_CLASS_MAP
  - `system_prompt`: Core instructions for the agent
  - `tools`: Optional list of tool names (e.g., `["read_file", "bash_exec"]`)
  - `tool_configs`: Optional custom tool configurations

- **model_adapter**: Optional ModelAdapter for IterativeAgent/ReActAgent
  - Handles LLM API calls
  - Created via `get_model_adapter(model_name, user_id, db)`

- **tools_override**: Optional pre-configured tool registry
  - Takes precedence over `agent_model.tools`
  - Used for view-scoped tools (graph view vs code view)

### Returns

Ready-to-use agent instance that can be executed with `.run()`

### Validation

The factory validates:

```python
# 1. System prompt exists
if not agent_model.system_prompt or not agent_model.system_prompt.strip():
    raise ValueError(
        f"Agent '{agent_model.name}' does not have a system prompt. "
        f"All agents must have a non-empty system_prompt to function."
    )

# 2. Agent type is recognized
AgentClass = AGENT_CLASS_MAP.get(agent_type_str)
if not AgentClass:
    available_types = ", ".join(AGENT_CLASS_MAP.keys())
    raise ValueError(
        f"Unknown agent type '{agent_type_str}'. "
        f"Available types: {available_types}"
    )
```

## Tool Registry Scoping

The factory creates scoped tool registries based on agent configuration.

### Priority Order

```python
# Priority: tools_override > agent_model.tools > global registry

if tools_override is not None:
    # 1. Use provided registry (highest priority)
    tools = tools_override
elif agent_model.tools:
    # 2. Create scoped registry from tool list
    tools = create_scoped_tool_registry(agent_model.tools, tool_configs)
else:
    # 3. Use global registry (IterativeAgent/ReActAgent only)
    if agent_type in ["IterativeAgent", "ReActAgent"]:
        tools = get_tool_registry()
```

### Scoped Tool Registry

Creates a registry with only specified tools:

```python
# Example: Restrict to file and shell tools
agent_model.tools = [
    "read_file",
    "write_file",
    "patch_file",
    "bash_exec"
]

# Factory creates scoped registry
tools = create_scoped_tool_registry(agent_model.tools)
# Result: Registry with only 4 tools instead of all 12+
```

### Custom Tool Configurations

Customize tool descriptions and examples per agent:

```python
agent_model.tool_configs = {
    "read_file": {
        "description": "Read React component source code",
        "examples": [
            '{"tool_name": "read_file", "parameters": {"file_path": "src/components/Button.tsx"}}'
        ],
        "system_prompt": "Always read TypeScript files with .tsx extension"
    },
    "bash_exec": {
        "description": "Run npm commands and scripts",
        "examples": [
            '{"tool_name": "bash_exec", "parameters": {"command": "npm test"}}'
        ]
    }
}

# Factory applies custom configs
tools = create_scoped_tool_registry(
    agent_model.tools,
    agent_model.tool_configs
)
```

### View-Scoped Tools

Different tool sets based on frontend view:

```python
# Code view: standard development tools
code_view_tools = create_scoped_tool_registry([
    "read_file", "write_file", "patch_file",
    "bash_exec", "shell_open", "shell_exec"
])

# Graph view: container management tools
graph_view_tools = create_scoped_tool_registry([
    "graph_start_container",
    "graph_stop_container",
    "graph_add_container",
    "graph_add_connection",
    "graph_container_status"
])

# Pass to factory
agent = await create_agent_from_db_model(
    agent_model,
    model_adapter=model,
    tools_override=graph_view_tools  # Use graph tools
)
```

## Agent Type-Specific Instantiation

Different agent types have different initialization requirements:

### StreamAgent
```python
if agent_type == "StreamAgent":
    agent = StreamAgent(
        system_prompt=agent_model.system_prompt,
        tools=tools  # Not used, but passed for consistency
    )
```

### IterativeAgent
```python
elif agent_type == "IterativeAgent":
    agent = IterativeAgent(
        system_prompt=agent_model.system_prompt,
        tools=tools,
        model=model_adapter  # Required for LLM calls
    )
```

### ReActAgent
```python
elif agent_type == "ReActAgent":
    agent = ReActAgent(
        system_prompt=agent_model.system_prompt,
        tools=tools,
        model=model_adapter  # Required for LLM calls
    )
```

### Generic Instantiation
```python
else:
    # Future agent types - generic instantiation
    agent = AgentClass(
        system_prompt=agent_model.system_prompt,
        tools=tools
    )
```

## Complete Example

### Database Setup

```sql
-- Create marketplace agent
INSERT INTO marketplace_agents (
    id,
    name,
    slug,
    agent_type,
    system_prompt,
    tools,
    tool_configs,
    price,
    is_public
) VALUES (
    gen_random_uuid(),
    'React Component Builder',
    'react-component-builder',
    'IterativeAgent',
    'You are an expert React developer...',
    ARRAY['read_file', 'write_file', 'patch_file', 'bash_exec'],
    '{
        "write_file": {
            "description": "Create React component files with TypeScript",
            "examples": ["..."]
        }
    }'::jsonb,
    0.00,
    true
);
```

### Python Usage

```python
from orchestrator.app.agent.factory import create_agent_from_db_model
from orchestrator.app.agent.models import get_model_adapter
from orchestrator.app.models import MarketplaceAgent
from sqlalchemy import select

async def run_agent_task(db, user, project, user_request):
    # 1. Fetch agent from marketplace
    result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.slug == 'react-component-builder'
        )
    )
    agent_model = result.scalar_one()

    # 2. Create model adapter
    model = await get_model_adapter(
        model_name="gpt-4",
        user_id=user.id,
        db=db
    )

    # 3. Create agent instance via factory
    agent = await create_agent_from_db_model(
        agent_model=agent_model,
        model_adapter=model
    )

    # 4. Prepare execution context
    context = {
        "user_id": user.id,
        "project_id": project.id,
        "db": db,
        "edit_mode": "allow",
        "project_context": {
            "project_name": project.name,
            "project_description": project.description
        }
    }

    # 5. Run agent
    async for event in agent.run(user_request, context):
        # Handle events
        if event['type'] == 'agent_step':
            print(f"Step: {event['data']['response_text']}")
        elif event['type'] == 'complete':
            print(f"Done! {event['data']['final_response']}")
        elif event['type'] == 'error':
            print(f"Error: {event['content']}")
```

### With View-Scoped Tools

```python
from orchestrator.app.agent.tools.view_scoped_factory import create_view_scoped_tools

# Get tools for current view
if view == "graph":
    tools = create_view_scoped_tools(
        view="graph",
        project_id=project.id,
        user_id=user.id
    )
else:
    tools = None  # Use agent's default tools

# Create agent with view-specific tools
agent = await create_agent_from_db_model(
    agent_model=agent_model,
    model_adapter=model,
    tools_override=tools  # Override agent's default tools
)
```

## Helper Functions

### register_agent_type

Dynamically register new agent types at runtime:

```python
def register_agent_type(agent_type: str, agent_class: Type[AbstractAgent]):
    """
    Register a new agent type in the factory.

    Useful for plugins or extensions.
    """
    if agent_type in AGENT_CLASS_MAP:
        logger.warning(f"Overwriting existing agent type: {agent_type}")

    AGENT_CLASS_MAP[agent_type] = agent_class
    logger.info(f"Registered agent type: {agent_type}")
```

Usage:
```python
from my_plugin import CustomAgent

register_agent_type("CustomAgent", CustomAgent)

# Now can be used in marketplace_agents table
agent_model.agent_type = "CustomAgent"
```

### get_available_agent_types

List all registered agent types:

```python
def get_available_agent_types() -> list[str]:
    """Get a list of all available agent types."""
    return list(AGENT_CLASS_MAP.keys())

# Usage
types = get_available_agent_types()
# ['StreamAgent', 'IterativeAgent', 'ReActAgent']
```

### get_agent_class

Get the class for an agent type:

```python
def get_agent_class(agent_type: str) -> Optional[Type[AbstractAgent]]:
    """Get the agent class for a given agent type."""
    return AGENT_CLASS_MAP.get(agent_type)

# Usage
AgentClass = get_agent_class("IterativeAgent")
if AgentClass:
    agent = AgentClass(system_prompt="...", tools=...)
```

## Logging

The factory logs key operations:

```python
# Agent creation start
logger.info(f"[AgentFactory] Creating agent '{agent_model.name}' of type '{agent_type_str}'")

# Tool registry selection
logger.info(f"[AgentFactory] Using provided tools_override registry")
# or
logger.info(f"[AgentFactory] Creating scoped tool registry with tools: {agent_model.tools}")
# or
logger.info(f"[AgentFactory] Using global tool registry for {agent_type_str}")

# Custom tool configs
logger.info(f"[AgentFactory] Applying custom tool configurations for {len(tool_configs)} tools")

# Success
logger.info(
    f"[AgentFactory] Successfully created {agent_type_str} "
    f"for agent '{agent_model.name}' (slug: {agent_model.slug})"
)
logger.info(f"[AgentFactory] Agent has access to {len(tools._tools)} tools")
```

## Best Practices

### 1. Always Validate System Prompts

```python
# Before saving to database
if not system_prompt or not system_prompt.strip():
    raise ValueError("System prompt cannot be empty")
```

### 2. Use Scoped Tools for Security

```python
# Don't give all agents full access
agent_model.tools = None  # ❌ Bad: Full access to all tools

# Restrict to needed tools
agent_model.tools = ["read_file", "write_file"]  # ✅ Good: Limited access
```

### 3. Test Custom Tool Configs

```python
# Test that custom descriptions make sense
tool_configs = {
    "bash_exec": {
        "description": "Run Python scripts",  # ❌ Bad: Misleading
        "description": "Execute shell commands"  # ✅ Good: Accurate
    }
}
```

### 4. Handle Model Adapter Errors

```python
try:
    model = await get_model_adapter(model_name, user_id, db)
except ValueError as e:
    # Handle API key issues, invalid model names, etc.
    logger.error(f"Failed to create model adapter: {e}")
    raise
```

## Related Files

- `orchestrator/app/agent/base.py` - AbstractAgent interface
- `orchestrator/app/agent/tools/registry.py` - Tool registry system
- `orchestrator/app/agent/tools/view_scoped_factory.py` - View-scoped tool creation
- `orchestrator/app/models.py` - MarketplaceAgent database model
- `orchestrator/app/routers/chat.py` - Agent execution endpoint
