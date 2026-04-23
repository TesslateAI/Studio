# Agent (Orchestrator Side)

OpenSail's agent runner lives in the `packages/tesslate-agent` Python submodule. The orchestrator hosts only the tool layer: the registry, scope/approval/scrubbing machinery, and every first-party tool implementation.

This README indexes what is in `orchestrator/app/agent/`. For the runner (planner, compaction, subagents, trajectory, prompt caching, model adapters), see `docs/packages/CLAUDE.md`.

## Package Layout

```
orchestrator/app/agent/
  __init__.py                    # Re-exports ToolRegistry helpers
  prompt_templates/              # Placeholder directory (no .py modules)
  tools/
    __init__.py
    registry.py                  # Tool, ToolRegistry, global singleton
    _secret_scrubber.py          # Redact project secrets in tool output
    approval_manager.py          # Pending user-input broker (approvals + node_config)
    output_formatter.py          # success_output / error_output helpers
    retry_config.py              # @tool_retry (tenacity)
    view_context.py              # ViewContext enum
    view_scoped_factory.py       # Factory for view-scoped registries
    view_scoped_registry.py      # Decorator registry filtered by active view
    providers/                   # AbstractToolProvider + GraphToolProvider
    file_ops/                    # read_file, write_file, patch_file, multi_edit,
                                 # read_many_files, apply_patch, file_undo, view_image
    shell_ops/                   # bash_exec, shell_open/close/exec, write_stdin,
                                 # list_background_processes, read_background_output,
                                 # python_repl
    nav_ops/                     # glob, grep, list_dir
    git_ops/                     # git_log, git_blame, git_status, git_diff
    memory_ops/                  # memory_read, memory_write (markdown memory.md)
    planning_ops/                # todo_read/write, save_plan, update_plan (legacy+structured)
    project_ops/                 # get_project_info, apply_setup_config, project_control,
                                 # project/container lifecycle, kanban
    delegation_ops/              # task, wait_agent, send_message_to_agent,
                                 # close_agent, list_agents
    web_ops/                     # web_fetch, web_search (Tavily/Brave/DuckDuckGo),
                                 # send_message
    skill_ops/                   # load_skill (progressive disclosure)
    schedule_ops/                # manage_schedule (create/list/update/pause/resume/
                                 # trigger/delete)
    node_config/                 # request_node_config, run_with_secrets
    graph_ops/                   # containers.py, grid.py, shell.py (view-scoped)
```

## How Tools Are Registered

Every subpackage exposes a `register_*` function called by `_register_all_tools` in `tools/registry.py::get_tool_registry`. That function is lazy and idempotent: the first `get_tool_registry()` call builds the singleton.

Subagent tools (`delegation_ops`) plus view-scoped tools (`graph_ops` through `GraphToolProvider`) follow the same pattern. `create_scoped_tool_registry(names, tool_configs)` returns a subset registry with optional description/example/system-prompt overrides, which is what marketplace agents receive.

## Cross-Cutting Concerns (in `tools/registry.py::ToolRegistry.execute`)

1. API-key scope check via `TOOL_REQUIRED_SCOPES` when `context["api_key_scopes"]` is set.
2. Edit-mode gating via `context["edit_mode"]` (`allow`, `ask`, `plan`). `DANGEROUS_TOOLS` drives the policy; `PLAN_MODE_ALLOWED` re-enables `bash_exec` in plan mode.
3. Ask-mode approval via `approval_manager.get_approval_manager()`, keyed by `context["chat_id"]`.
4. Secret scrubbing on all `ToolCategory.SHELL` results using the per-task cached map at `context["__secret_scrub_map__"]`.
5. Normalized result shape: `{"success": bool, "tool": str, "result"|"error": ...}`.

## Tool Documentation Map

| Subpackage | Doc |
|------------|-----|
| `file_ops/` | `tools/file-ops.md` |
| `shell_ops/` | `tools/shell-ops.md`, `tools/compute-tiers.md` |
| `nav_ops/` | `tools/nav-ops.md` |
| `git_ops/` | `tools/git-ops.md` |
| `memory_ops/` | `tools/memory-ops.md` |
| `planning_ops/` | `tools/planning-ops.md` |
| `project_ops/` | `tools/project-control.md`, `tools/project-ops.md`, `kanban-agent-tool.md` |
| `delegation_ops/` | `tools/delegation-ops.md` |
| `web_ops/` | `tools/web-search.md`, `tools/web-ops.md` |
| `skill_ops/` | `tools/skill-ops.md` |
| `schedule_ops/` | `tools/schedule-ops.md` |
| `node_config/` | `tools/node-config.md` |
| `graph_ops/` + providers | `tools/graph-ops.md`, `tools/view-scoped-tools.md`, `tools/view-scoped-quick-reference.md` |
| Registry internals | `tools/registry.md`, `agent-internals.md` |
| Approval flow | `tools/approval.md`, `agent-internals.md` |

## Related Docs

- `agent-runner.md`: orchestrator-to-submodule handoff (replaces the old agent-types / factory / prompts docs).
- `docs/packages/CLAUDE.md`: the actual runner (planner, compaction, subagents, trajectory, model adapters, prompt caching).
- `docs/orchestrator/services/CLAUDE.md`: services consumed by tool executors.
