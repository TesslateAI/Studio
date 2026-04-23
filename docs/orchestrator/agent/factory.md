# Scoped Tool Registry (Replaces `factory.py`)

> The old `orchestrator/app/agent/factory.py` has been removed together with the inline agent classes. Tool selection now happens directly via `create_scoped_tool_registry`.

## What Changed

| Removed | Replacement |
|---------|-------------|
| `AGENT_CLASS_MAP` | Single runner in `packages/tesslate-agent` |
| `create_agent_from_db_model()` | `TesslateAgentRunner(...)` constructed in `orchestrator/app/services/agent_handlers.py` |
| `AbstractAgent` base | `packages/tesslate-agent`'s runner class |
| Agent-type string routing | Marketplace field still exists but is informational |

## Current API

```python
from orchestrator.app.agent.tools.registry import (
    create_scoped_tool_registry,
    get_tool_registry,
)

# All registered tools (global singleton)
registry = get_tool_registry()

# Per-agent subset with optional overrides
scoped = create_scoped_tool_registry(
    tool_names=["read_file", "write_file", "patch_file", "bash_exec"],
    tool_configs={
        "read_file": {
            "description": "Read React component files.",
            "examples": ['{"tool_name":"read_file","parameters":{"file_path":"src/App.tsx"}}'],
            "system_prompt": "Prefer reading before writing.",
        },
    },
)
```

`tool_configs` supports three override keys: `description`, `examples`, `system_prompt`. Missing tools are logged but do not raise.

## View-Scoped Registry

For UI-view-specific tools, use `tools/view_scoped_factory.py`:

```python
from orchestrator.app.agent.tools.view_scoped_factory import (
    register_provider_class,
    get_view_scoped_registry,
)
from orchestrator.app.agent.tools.view_context import ViewContext
from orchestrator.app.agent.tools.providers.graph_provider import GraphToolProvider

register_provider_class(ViewContext.GRAPH, GraphToolProvider)
registry = get_view_scoped_registry(ViewContext.GRAPH, project_id=..., user_id=...)
```

See `tools/view-scoped-tools.md` and `tools/view-scoped-quick-reference.md`.

## Selecting the Model / Provider

Model selection is no longer part of this package. It is handled inside `packages/tesslate-agent` based on the agent's `model` string (`builtin/...`, `custom/provider/model`, or a BYOK provider prefix in `BUILTIN_PROVIDERS`). See `docs/packages/CLAUDE.md`.

## Related Docs

- `agent-runner.md` (`agent-types.md` filename): orchestrator-to-submodule handoff.
- `tools/registry.md`: `Tool` dataclass and registry internals.
- `tools/view-scoped-tools.md`: view filtering pattern.
