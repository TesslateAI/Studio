# Memory Tools (`memory_ops/`)

Persistent, cross-session agent memory stored as sectioned markdown.

## Tools

| Tool | File | Purpose |
|------|------|---------|
| `memory_read` | `memory_ops/memory_tool.py` | Read a topic section (H2 heading) or the full memory file. |
| `memory_write` | `memory_ops/memory_tool.py` | Write / append / replace a topic section. |

Both tools accept `scope: "project" | "global"`.

## Storage Layout

| Scope | Path |
|-------|------|
| `project` | `<PROJECT_ROOT>/.tesslate/memory.md` (project root from env or `context["project_root"]`) |
| `global` | `<HOME>/.tesslate/memory.md` |

Topics are delimited by `## <topic>` H2 headings. Any content before the first heading is treated as a preamble. Lock-safe via `asyncio.Lock`.

## Startup Injection

`load_memory_prefix(project_root)` is a synchronous helper that returns the project memory block wrapped for injection into the agent system prompt at dispatch time. The orchestrator calls this when building the agent context so session-one knowledge stays accessible.

## Registration

`register_memory_ops_tools(registry)`.

## Related

- `orchestrator/app/services/agent_context.py`: calls `load_memory_prefix`.
- `docs/packages/CLAUDE.md`: how the runner consumes injected memory.
