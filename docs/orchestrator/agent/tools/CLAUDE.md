# Tools Context for Claude

**Purpose**: Agent tool development in `orchestrator/app/agent/tools/`.

## Core Files (cross-cutting)

| File | Role |
|------|------|
| `registry.py` | `Tool`, `ToolCategory`, `ToolRegistry`, global singleton, scope map, edit-mode gate, `create_scoped_tool_registry` |
| `_secret_scrubber.py` | Redact project secrets in shell tool output before the agent sees them |
| `approval_manager.py` | Pending user-input broker (`approval` and `node_config` kinds) |
| `output_formatter.py` | `success_output`, `error_output`, sizing/pluralization helpers |
| `retry_config.py` | `@tool_retry` with tenacity; retryable vs permanent error classification |
| `view_context.py` | `ViewContext` enum: `GRAPH`, `BUILDER`, `TERMINAL`, `KANBAN`, `UNIVERSAL` |
| `view_scoped_factory.py` | Factory + cache for view-scoped registries |
| `view_scoped_registry.py` | Registry decorator filtering tools by active view |
| `providers/base.py` | `AbstractToolProvider` ABC |
| `providers/graph_provider.py` | `GraphToolProvider` for the `GRAPH` view |

See `agent-internals.md` (parent dir) for the full `ToolRegistry.execute` pipeline, `TOOL_REQUIRED_SCOPES` table, scrubber thresholds, and retry classifier.

## Tool Subpackages

| Subpackage | Tools | Doc |
|------------|-------|-----|
| `file_ops/` | `read_file`, `write_file`, `read_many_files`, `patch_file`, `multi_edit`, `apply_patch`, `file_undo`, `view_image` | [file-ops.md](file-ops.md) |
| `shell_ops/` | `bash_exec`, `shell_open`, `shell_close`, `shell_exec`, `write_stdin`, `list_background_processes`, `read_background_output`, `python_repl` | [shell-ops.md](shell-ops.md), [compute-tiers.md](compute-tiers.md) |
| `nav_ops/` | `glob`, `grep`, `list_dir` | [nav-ops.md](nav-ops.md) |
| `git_ops/` | `git_log`, `git_blame`, `git_status`, `git_diff` | [git-ops.md](git-ops.md) |
| `memory_ops/` | `memory_read`, `memory_write` | [memory-ops.md](memory-ops.md) |
| `planning_ops/` | `todo_read`, `todo_write`, `save_plan`, legacy `update_plan`, structured `update_plan` | [planning-ops.md](planning-ops.md) |
| `project_ops/` | `get_project_info`, `project_control`, `apply_setup_config`, `project_start/stop/restart`, `container_start/stop/restart`, `kanban` | [project-ops.md](project-ops.md), [project-control.md](project-control.md), [../kanban-agent-tool.md](../kanban-agent-tool.md) |
| `delegation_ops/` | `task`, `wait_agent`, `send_message_to_agent`, `close_agent`, `list_agents` | [delegation-ops.md](delegation-ops.md) |
| `web_ops/` | `web_fetch`, `web_search`, `send_message` | [web-search.md](web-search.md), [web-ops.md](web-ops.md) |
| `skill_ops/` | `load_skill` | [skill-ops.md](skill-ops.md) |
| `schedule_ops/` | `manage_schedule` | [schedule-ops.md](schedule-ops.md) |
| `node_config/` | `request_node_config`, `run_with_secrets` | [node-config.md](node-config.md) |
| `graph_ops/` (view-scoped) | `graph_start_container`, `graph_stop_container`, `graph_add_container`, `graph_add_connection`, `graph_add_browser_preview`, `graph_shell_*` | [graph-ops.md](graph-ops.md), [view-scoped-tools.md](view-scoped-tools.md), [view-scoped-quick-reference.md](view-scoped-quick-reference.md) |

## Edit Mode Policy

| Mode | Dangerous tool behavior |
|------|-------------------------|
| `allow` | Execute directly |
| `ask` | Pause via `approval_manager`; session-scoped approval cache keyed by `chat_id` |
| `plan` | Blocked except `bash_exec` (`PLAN_MODE_ALLOWED`) |

`DANGEROUS_TOOLS`: `write_file`, `patch_file`, `multi_edit`, `apply_patch`, `bash_exec`, `shell_exec`, `shell_open`, `web_fetch`, `web_search`, `send_message`.

Safe tools (read_file, get_project_info, todo_write, nav/git/memory reads, planning) run unrestricted in every mode.

## Registering a Tool

```python
from orchestrator.app.agent.tools.registry import Tool, ToolCategory
from orchestrator.app.agent.tools.output_formatter import success_output, error_output
from orchestrator.app.agent.tools.retry_config import tool_retry

@tool_retry
async def my_tool_executor(params, context):
    value = params.get("value")
    if not value:
        return error_output(message="'value' is required", suggestion="Pass a non-empty string")
    return success_output(message=f"Did a thing with {value}", details={"echo": value})

registry.register(Tool(
    name="my_tool",
    description="What this tool does",
    category=ToolCategory.FILE_OPS,
    parameters={
        "type": "object",
        "properties": {"value": {"type": "string", "description": "..."}},
        "required": ["value"],
    },
    executor=my_tool_executor,
    examples=['{"tool_name":"my_tool","parameters":{"value":"hi"}}'],
))
```

## Related Contexts

| Context | When |
|---------|------|
| `docs/orchestrator/agent/CLAUDE.md` | Package overview, registration flow |
| `docs/orchestrator/agent/agent-internals.md` | Registry / scrubber / approval / retry internals |
| `docs/orchestrator/services/CLAUDE.md` | Orchestration, encryption, channels, gateway called by executors |
| `docs/orchestrator/routers/CLAUDE.md` | HTTP equivalents of these tools |
| `docs/packages/CLAUDE.md` | The actual runner that drives these tools |
