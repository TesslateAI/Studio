# Tool Registry Internals

Covers the cross-cutting files in `orchestrator/app/agent/tools/` that every tool goes through.

## Files

| File | Role |
|------|------|
| `registry.py` | `Tool` dataclass, `ToolCategory`, `ToolRegistry`, scope map, edit-mode gating, global singleton, `create_scoped_tool_registry` |
| `_secret_scrubber.py` | Per-task cached scrub map; replaces project-secret substrings with `«secret:KEY»` in shell tool output |
| `approval_manager.py` | Redis-backed pending-input broker. Two kinds: `approval` (tool approvals) and `node_config` (form input) |
| `output_formatter.py` | `success_output`, `error_output`, `pluralize`, `format_file_size`, `truncate_output` |
| `retry_config.py` | `@tool_retry` decorator using tenacity; classifies retryable vs non-retryable exceptions |
| `view_context.py` | `ViewContext` enum: `GRAPH`, `BUILDER`, `TERMINAL`, `KANBAN`, `UNIVERSAL` |
| `view_scoped_factory.py` | Provider registration + cached registry builder |
| `view_scoped_registry.py` | `ViewScopedToolRegistry` decorator filtering by active view |
| `providers/base.py` | `AbstractToolProvider` ABC |
| `providers/graph_provider.py` | `GraphToolProvider` (feeds `graph_ops` tools to the GRAPH view) |

## ToolRegistry.execute Pipeline

1. Look up the tool; return a structured unknown-tool error if missing.
2. **API-key scope check** against `TOOL_REQUIRED_SCOPES` when `context["api_key_scopes"]` is set.
3. **Edit-mode gate**:
   - `DANGEROUS_TOOLS`: `write_file`, `patch_file`, `multi_edit`, `apply_patch`, `bash_exec`, `shell_exec`, `shell_open`, `web_fetch`, `web_search`, `send_message`
   - `plan` mode: blocks everything dangerous except `PLAN_MODE_ALLOWED = {"bash_exec"}`
   - `ask` mode: requires approval via `approval_manager`; caches per-session per-tool approvals
4. Execute the tool.
5. For `ToolCategory.SHELL`, post-process with `_secret_scrubber.scrub_tool_result` using the per-context secret map.
6. Return `{"success": bool, "tool": str, "result"|"error": ...}`.

## TOOL_REQUIRED_SCOPES (API-key)

| Scope | Tools |
|-------|-------|
| `file.write` | `write_file`, `patch_file`, `multi_edit`, `apply_patch` |
| `file.delete` | `delete_file` |
| `terminal.access` | `bash_exec`, `shell_exec`, `shell_open`, `shell_close` |
| `file.read` | `web_fetch`, `web_search` |
| `channel.manage` | `send_message` |
| `container.view` | `container_status`, `container_logs`, `container_health` |
| `container.start_stop` | `container_restart` |
| `kanban.edit` | `kanban_create`, `kanban_move`, `kanban_update`, `kanban_comment` |

Tools not listed (`read_file`, `grep`, `todo_write`, `get_project_info`, etc.) are unrestricted.

## Secret Scrubber

| Constant | Default | Meaning |
|----------|---------|---------|
| `_MIN_LEN` | 6 | Minimum secret length considered for the map |
| `_SCRUB_MIN_LEN` | 12 | Minimum length to scrub during `scrub_text` |
| `_ENTROPY_FLOOR` | 3.0 bits/char | Below this, value looks like prose, skipped |
| `_ENTROPY_CEILING` | 4.0 bits/char | Above this OR longer than `_NAIVE_LEN`, substring-contains is used |
| `_NAIVE_LEN` | 20 | Length threshold that switches from boundary to substring match |

The map is cached on `context["__secret_scrub_map__"]` for the life of the task.

## Approval Manager

- Redis channels: `tesslate:pending_input` (canonical), `tesslate:approvals` (legacy).
- Keyspace reserved: `pending_input:{input_id}` for future durable handoff.
- `is_tool_approved(session_id, tool)` caches per-session approvals (`chat_id` is the session).
- Responses: `allow_once`, `allow_all`, `stop`.
- `kind="node_config"` is driven by the `request_node_config` tool and resumes on `POST /api/chat/node-config/{input_id}/submit`.

## Retry Classifier (`retry_config.py`)

| Retryable | Non-retryable |
|-----------|---------------|
| `ConnectionError` | `FileNotFoundError` |
| `TimeoutError` | `PermissionError` |
| | `NotADirectoryError`, `IsADirectoryError` |

Exponential backoff 1s, 2s, 4s; up to 3 attempts; logs each sleep.

## Output Formatter

Always return `success_output(message=..., details={...}, file_path=...)` or `error_output(message=..., suggestion=...)` from executors. The top-level `success` field is populated automatically; the agent display layer relies on this shape.
