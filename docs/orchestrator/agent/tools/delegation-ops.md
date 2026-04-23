# Delegation Tools (`delegation_ops/`)

First-party subagent orchestration. Lets the main agent spawn and communicate with scoped subagents.

## Tools

| Tool | File | Purpose |
|------|------|---------|
| `task` | `task_tool.py` | Spawn a new subagent with a task description and scoped tool set. |
| `wait_agent` | `task_tool.py` | Block until a named subagent produces a response or exits. |
| `send_message_to_agent` | `task_tool.py` | Push a message to a running subagent. |
| `close_agent` | `task_tool.py` | Signal a subagent to shut down and return its final output. |
| `list_agents` | `task_tool.py` | Return the live `SubagentRecord` list for the current run. |

## Registry

`agent_registry.py` defines:

| Symbol | Role |
|--------|------|
| `SUBAGENT_REGISTRY` | Global in-process registry (dict of `SubagentRecord`) |
| `SubagentRecord` | Per-subagent state (status, channel, metadata) |
| `SubagentRegistry` | Class holding registry operations |
| `MAX_SUBAGENT_DEPTH` | Prevents runaway recursive spawning |

## Registration

`register_delegation_ops_tools(registry)` wires all five tools. The runner in `packages/tesslate-agent` pairs with this registry to execute subagents; the orchestrator only provides the tool surface and registry state.

## Related

- `docs/packages/CLAUDE.md`: subagent execution model in the runner.
- `docs/orchestrator/services/CLAUDE.md`: cross-pod session routing for subagent channels.
