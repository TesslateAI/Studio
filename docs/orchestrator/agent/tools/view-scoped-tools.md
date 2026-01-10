# View-Scoped Agent Tools

This documentation covers the view-scoped tool system that enables agents to have different tools available based on the current UI view.

## Overview

The view-scoped tool system provides a scalable, abstract factory pattern with polymorphism for view-specific agent tools. Tools are only available when their associated view (e.g., Graph View) is active, and are automatically disabled when the user navigates to other views (e.g., Builder Mode).

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     ViewContext (Enum)                          │
│  GRAPH | BUILDER | TERMINAL | KANBAN | UNIVERSAL               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 AbstractToolProvider (ABC)                      │
│  + get_view_context() -> ViewContext                           │
│  + get_tools() -> List[Tool]                                   │
│  + validate_context(context) -> bool                           │
└─────────────────────────────────────────────────────────────────┘
                              △
                              │
                  ┌───────────┴───────────┐
                  │                       │
         ┌────────┴────────┐    ┌─────────┴─────────┐
         │GraphToolProvider│    │ Future Providers  │
         │- container tools│    │ (extensible)      │
         │- grid tools     │    │                   │
         │- shell tools    │    │                   │
         └─────────────────┘    └───────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  ViewScopedToolRegistry                         │
│  - Wraps base ToolRegistry (decorator pattern)                 │
│  - Filters tools based on active view                          │
│  - Caches compiled registries for performance                  │
└─────────────────────────────────────────────────────────────────┘
```

## Key Components

### ViewContext Enum

Located at: `orchestrator/app/agent/tools/view_context.py`

Defines the available UI view contexts:

```python
class ViewContext(Enum):
    GRAPH = "graph"        # Architecture/Graph canvas view
    BUILDER = "builder"    # Builder mode - container-scoped development
    TERMINAL = "terminal"  # Terminal panel focus
    KANBAN = "kanban"      # Kanban board view
    UNIVERSAL = "universal" # Available in all views
```

### AbstractToolProvider

Located at: `orchestrator/app/agent/tools/providers/base.py`

Abstract base class that all view-specific providers must implement:

```python
class AbstractToolProvider(ABC):
    @abstractmethod
    def get_view_context(self) -> ViewContext:
        """Return the view context this provider serves."""
        pass

    @abstractmethod
    def get_tools(self) -> List[Tool]:
        """Return list of tools available in this view context."""
        pass

    def validate_context(self, context: Dict[str, Any]) -> bool:
        """Validate execution context for this view."""
        return True

    def is_tool_available(self, tool_name: str, context: Dict[str, Any]) -> bool:
        """Check if a specific tool is available."""
        return any(t.name == tool_name for t in self.get_tools())
```

### ViewScopedToolRegistry

Located at: `orchestrator/app/agent/tools/view_scoped_registry.py`

Wraps the base ToolRegistry using the decorator pattern:

- Maintains providers for each view context
- Filters available tools based on current active view
- Caches compiled registries per view for performance
- Delegates execution to the appropriate registry

### ViewScopedToolFactory

Located at: `orchestrator/app/agent/tools/view_scoped_factory.py`

Factory functions for creating view-scoped registries:

```python
def create_view_scoped_registry(
    view_context: ViewContext,
    project_id: Optional[UUID] = None,
    container_id: Optional[UUID] = None,
    base_tool_names: Optional[List[str]] = None,
    use_cache: bool = True
) -> ViewScopedToolRegistry:
    """Create a view-scoped tool registry."""
    pass
```

## Graph View Tools

When the user is in the Graph/Architecture view, the following additional tools become available:

### Container Control Tools

Located at: `orchestrator/app/agent/tools/graph_ops/containers.py`

| Tool | Description | Parameters |
|------|-------------|------------|
| `graph_start_container` | Start a specific container | `container_id: string` |
| `graph_stop_container` | Stop a specific container | `container_id: string` |
| `graph_start_all` | Start all containers in project | None |
| `graph_stop_all` | Stop all containers in project | None |
| `graph_container_status` | Get status of all containers | None |

### Grid Management Tools

Located at: `orchestrator/app/agent/tools/graph_ops/grid.py`

| Tool | Description | Parameters |
|------|-------------|------------|
| `graph_add_container` | Add new container to grid | `name, base_id?, container_type?, position_x?, position_y?, port?` |
| `graph_add_browser_preview` | Add browser preview node | `container_id?, position_x?, position_y?` |
| `graph_add_connection` | Create connection between containers | `source_container_id, target_container_id, connector_type?, label?, config?` |
| `graph_remove_item` | Remove item from grid | `item_type: container|connection|browser_preview, item_id` |

### Shell Tools (Container-Targeted)

Located at: `orchestrator/app/agent/tools/graph_ops/shell.py`

| Tool | Description | Parameters |
|------|-------------|------------|
| `graph_shell_open` | Open shell session in specific container | `container_id, command?` |
| `graph_shell_exec` | Execute command in specific container | `container_id, command, timeout?` |
| `graph_shell_close` | Close shell session | `session_id` |

## Usage

### Frontend Integration

Pass `viewContext` prop to ChatContainer:

```tsx
// In Graph View (ProjectGraphCanvas.tsx)
<ChatContainer
  projectId={project?.id}
  containerId={selectedContainer?.id}
  viewContext="graph"  // Graph-specific tools available
  agents={agents}
  // ...
/>

// In Builder Mode (Project.tsx)
<ChatContainer
  projectId={project?.id}
  containerId={containerId}
  viewContext="builder"  // Only base tools available
  agents={agents}
  // ...
/>
```

### Backend Integration

The view context is automatically handled in `chat.py`:

```python
if request.view_context:
    from ..agent.tools.view_context import ViewContext
    from ..agent.tools.view_scoped_factory import create_view_scoped_registry

    view_context = ViewContext.from_string(request.view_context)
    tools_override = create_view_scoped_registry(
        view_context=view_context,
        project_id=request.project_id,
        container_id=request.container_id
    )

agent_instance = await create_agent_from_db_model(
    agent_model=agent_model,
    model_adapter=model_adapter,
    tools_override=tools_override
)
```

## Adding New View-Specific Tools

### 1. Create a Tool Provider

```python
# orchestrator/app/agent/tools/providers/my_view_provider.py

from .base import AbstractToolProvider
from ..view_context import ViewContext
from ..registry import Tool

class MyViewToolProvider(AbstractToolProvider):
    def get_view_context(self) -> ViewContext:
        return ViewContext.MY_VIEW  # Add to ViewContext enum first

    def get_tools(self) -> List[Tool]:
        return [
            Tool(
                name="my_tool",
                description="Does something specific to this view",
                category=ToolCategory.PROJECT,
                parameters={...},
                executor=my_tool_executor
            )
        ]
```

### 2. Register the Provider

In `view_scoped_factory.py`:

```python
from .providers.my_view_provider import MyViewToolProvider

def _ensure_providers_registered():
    # ... existing registrations ...
    if ViewContext.MY_VIEW not in _PROVIDER_CLASSES:
        register_provider_class(ViewContext.MY_VIEW, MyViewToolProvider)
```

### 3. Update Frontend

Pass the new view context when appropriate:

```tsx
<ChatContainer
  viewContext="my_view"
  // ...
/>
```

## Design Decisions

1. **Decorator Pattern**: ViewScopedToolRegistry wraps base registry, doesn't replace it
2. **Provider Abstraction**: New views can add tools by implementing AbstractToolProvider
3. **Caching**: View registries cached after first build for performance
4. **Backwards Compatible**: Requests without view_context default to builder behavior
5. **Factory Pattern**: Centralized creation of view-scoped registries
6. **Prefixed Tool Names**: Graph tools use `graph_` prefix to avoid conflicts
7. **Full Tool Access**: Graph view includes ALL base tools PLUS graph-specific tools
8. **Invisible When Unavailable**: Tools not in current view are completely hidden from agent context

## Files Reference

### New Files

| File | Purpose |
|------|---------|
| `orchestrator/app/agent/tools/view_context.py` | ViewContext enum |
| `orchestrator/app/agent/tools/view_scoped_registry.py` | View-scoped registry |
| `orchestrator/app/agent/tools/view_scoped_factory.py` | Factory functions |
| `orchestrator/app/agent/tools/providers/__init__.py` | Providers package |
| `orchestrator/app/agent/tools/providers/base.py` | AbstractToolProvider |
| `orchestrator/app/agent/tools/providers/graph_provider.py` | Graph tools provider |
| `orchestrator/app/agent/tools/graph_ops/__init__.py` | Graph ops package |
| `orchestrator/app/agent/tools/graph_ops/containers.py` | Container control tools |
| `orchestrator/app/agent/tools/graph_ops/grid.py` | Grid management tools |
| `orchestrator/app/agent/tools/graph_ops/shell.py` | Shell tools |

### Modified Files

| File | Changes |
|------|---------|
| `orchestrator/app/agent/tools/registry.py` | Added VIEW_GRAPH category |
| `orchestrator/app/schemas.py` | Added view_context to AgentChatRequest |
| `orchestrator/app/routers/chat.py` | Uses view-scoped registry |
| `orchestrator/app/agent/factory.py` | Accepts tools_override param |
| `app/src/components/chat/ChatContainer.tsx` | Added viewContext prop |
| `app/src/pages/ProjectGraphCanvas.tsx` | Passes viewContext="graph" |
| `app/src/pages/Project.tsx` | Passes viewContext="builder" |
