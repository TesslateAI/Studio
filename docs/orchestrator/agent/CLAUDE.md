# Agent Context for Claude

**Purpose**: Orchestrator-side agent tool registry and execution machinery.

The inline agent runner (StreamAgent, IterativeAgent, ReActAgent, TesslateAgent) has been removed from `orchestrator/app/agent/`. The active agent runner lives in the `packages/tesslate-agent` submodule and is invoked through `orchestrator/app/services/tesslate_agent_adapter.py`.

What remains in `orchestrator/app/agent/` is the first-party tool layer that the submodule and external callers register against:

| Area | Location |
|------|----------|
| Package entry | `orchestrator/app/agent/__init__.py` (re-exports `ToolRegistry`, `get_tool_registry`, `create_scoped_tool_registry`) |
| Tool registry core | `orchestrator/app/agent/tools/registry.py` |
| Tool subpackages | `orchestrator/app/agent/tools/*/` |
| Prompt template stub | `orchestrator/app/agent/prompt_templates/` (empty placeholder retained for import-path compatibility; no Python modules) |

## File Map

| File | Purpose |
|------|---------|
| `tools/registry.py` | `Tool` dataclass, `ToolRegistry`, scope enforcement, edit-mode gating, global registry singleton, `create_scoped_tool_registry`. See `tools/registry.md` |
| `tools/_secret_scrubber.py` | Redacts project secrets in shell tool output before returning to the agent. Entropy + length heuristic. |
| `tools/approval_manager.py` | Brokers "agent paused awaiting user": `kind="approval"` (tool approvals) and `kind="node_config"` (form input). Redis pub/sub + in-memory map. |
| `tools/output_formatter.py` | `success_output`, `error_output`, and size/pluralization helpers all tool executors must use. |
| `tools/retry_config.py` | `@tool_retry` decorator (tenacity) with retryable/non-retryable exception classification. |
| `tools/view_context.py` | `ViewContext` enum: `GRAPH`, `BUILDER`, `TERMINAL`, `KANBAN`, `UNIVERSAL`. |
| `tools/view_scoped_factory.py` | Factory for `ViewScopedToolRegistry` with pluggable providers. |
| `tools/view_scoped_registry.py` | Registry decorator that filters tools by active view. |
| `tools/providers/base.py` | `AbstractToolProvider`. |
| `tools/providers/graph_provider.py` | `GraphToolProvider`, supplies graph_ops tools in the GRAPH view. |

## Tool Subpackages (all register through `_register_all_tools`)

| Subpackage | Tools | Registration entry | Doc |
|------------|-------|---------------------|-----|
| `file_ops/` | `read_file`, `write_file`, `read_many_files`, `patch_file`, `multi_edit`, `apply_patch`, `file_undo`, `view_image` | `register_all_file_tools` | `tools/file-ops.md` |
| `shell_ops/` | `bash_exec`, `shell_open`, `shell_close`, `shell_exec`, `write_stdin`, `list_background_processes`, `read_background_output`, `python_repl` | `register_all_shell_tools` | `tools/shell-ops.md` |
| `nav_ops/` | `glob`, `grep`, `list_dir` | `register_nav_ops_tools` | `tools/nav-ops.md` |
| `git_ops/` | `git_log`, `git_blame`, `git_status`, `git_diff` | `register_git_ops_tools` | `tools/git-ops.md` |
| `memory_ops/` | `memory_read`, `memory_write` | `register_memory_ops_tools` | `tools/memory-ops.md` |
| `planning_ops/` | `todo_read`, `todo_write`, `save_plan`, legacy `update_plan`, structured `update_plan` | `register_all_planning_tools` | `tools/planning-ops.md` |
| `project_ops/` | `get_project_info`, `project_control`, `apply_setup_config`, `project_start/stop/restart`, `container_start/stop/restart`, `kanban` | `register_all_project_tools` | `tools/project-control.md`, `tools/project-ops.md`, `kanban-agent-tool.md` |
| `delegation_ops/` | `task`, `wait_agent`, `send_message_to_agent`, `close_agent`, `list_agents` | `register_delegation_ops_tools` | `tools/delegation-ops.md` |
| `web_ops/` | `web_fetch`, `web_search`, `send_message` | `register_all_web_tools` | `tools/web-search.md`, `tools/web-ops.md` |
| `skill_ops/` | `load_skill` | `register_all_skill_tools` | `tools/skill-ops.md` |
| `schedule_ops/` | `manage_schedule` | `register_schedule_ops_tools` | `tools/schedule-ops.md` |
| `node_config/` | `request_node_config`, `run_with_secrets` | `register_all_node_config_tools` | `tools/node-config.md` |
| `graph_ops/` | `graph_start_container`, `graph_stop_container`, `graph_add_container`, `graph_add_connection`, `graph_add_browser_preview`, `graph_shell_*` | `register_all_graph_tools` (via `GraphToolProvider`) | `tools/graph-ops.md` |

## Cross-Cutting Concerns

| Concern | Where it happens |
|---------|------------------|
| Edit mode gating (allow/ask/plan) | `ToolRegistry.execute` reads `context["edit_mode"]`; dangerous tools gated |
| API-key scope enforcement | `ToolRegistry.TOOL_REQUIRED_SCOPES` + `_check_tool_scope` |
| Secret scrubbing | All `ToolCategory.SHELL` results are post-processed by `scrub_tool_result` |
| Approval pause/resume | `approval_manager.py` + Redis channel `tesslate:pending_input` (and legacy `tesslate:approvals`) |
| Output shape | Every executor returns `success_output` / `error_output` dicts |

## Related Contexts

| Context | When to load |
|---------|--------------|
| `docs/packages/CLAUDE.md` | Working on the actual agent runner in `packages/tesslate-agent` |
| `docs/orchestrator/agent/tools/CLAUDE.md` | Developing or modifying tools |
| `docs/orchestrator/services/CLAUDE.md` | Tool executors that call into services (orchestration, pubsub, encryption) |
| `docs/orchestrator/routers/CLAUDE.md` | Agent invocation endpoints (chat, external_agent) |
| `docs/orchestrator/agent/agent-runner.md` | How the orchestrator calls the tesslate-agent submodule |

## When to Load This Context

Load this context when:
1. Adding or modifying a tool in `orchestrator/app/agent/tools/`
2. Changing scope enforcement, edit modes, approval, or secret scrubbing
3. Wiring new view-scoped tools or providers
4. Debugging why a tool is rejected, approved, or scrubbed
