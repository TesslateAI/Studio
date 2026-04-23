# Packages (`packages/`)

## Purpose

Documents the `packages/` directory at the repo root. Each package is a standalone, versioned library consumed by the orchestrator, desktop sidecar, or external products. This layer separates reusable logic from the FastAPI application code.

## Index

| Package | Language | Directory | Role |
| ------- | -------- | --------- | ---- |
| `tesslate-agent` | Python | `packages/tesslate-agent/` | Canonical agent runner: tool-calling loop, trajectory recording, streamed events |
| `tesslate-app-sdk/py` | Python | `packages/tesslate-app-sdk/py/` | Async SDK for publishing, installing, invoking Tesslate Apps |
| `tesslate-app-sdk/ts` | TypeScript | `packages/tesslate-app-sdk/ts/` | Sibling TS SDK with the same surface for Node and browser callers |
| `tesslate-embed-sdk` | TypeScript | `packages/tesslate-embed-sdk/` | iframe-side postMessage client for Studio-hosted apps |

## tesslate-agent

Primary agent runner used by both the cloud worker and the desktop sidecar. Single-process, batteries-included, zero runtime dependency on the OpenSail orchestrator.

### Packaging

| File | Role |
| ---- | ---- |
| `packages/tesslate-agent/pyproject.toml` | Hatchling build config. Name `tesslate-agent`, `requires-python >=3.11`, deps: `litellm>=1.50`, `pydantic>=2`, `ptyprocess`, `pathspec`, `aiofiles`, `httpx`, `tenacity`. Console script: `tesslate-agent = tesslate_agent.cli.__main__:main`. |
| `packages/tesslate-agent/README.md` | Install and CLI usage reference, env var matrix for providers, LiteLLM proxy mode, project-root containment guarantee. |
| `packages/tesslate-agent/src/tesslate_agent/__init__.py` | `__version__ = "0.1.0"`. |

### Core agent (`src/tesslate_agent/agent/`)

| File | Role |
| ---- | ---- |
| `base.py` | `AbstractAgent` ABC. `__init__(system_prompt, tools)`, `get_processed_system_prompt(context)` expands `{mode}`, `{project_name}`, `{project_path}`, `{timestamp}`, `{user_name}`, `{tool_list}`. `run(user_request, context)` is the abstract async generator contract. |
| `tesslate_agent.py` | Concrete `TesslateAgent`. Drives a `ModelAdapter` via OpenAI tool-calling contract. Loop: build messages, call `chat_with_tools`, dispatch tool calls (parallel for `PARALLEL_SAFE_TOOLS`, sequential otherwise), feed results back, compact at `compaction_threshold * context_window_tokens`. Retry on transient keywords. `MAX_TOOL_OUTPUT=10_000` truncation per result. No DB, no Redis, no billing coupling. |
| `models.py` | `ModelAdapter` ABC + `LiteLLMAdapter`. Provider-env-var resolution for 12+ providers. `MissingApiKeyError` with actionable message. `chat_with_tools` (sync + streaming shapes). `create_model_adapter()` factory verifies credentials eagerly. LiteLLM proxy mode via `LITELLM_API_BASE` + `LITELLM_MASTER_KEY`. |
| `trajectory.py` | `TrajectoryRecorder`. ATIF v1.4 (`AGENT_NAME=tesslate-agent`, `AGENT_VERSION=1.0.0`, `SCHEMA_VERSION=ATIF-v1.4`). Methods: `record_system`, `record_user`, `record_assistant`, `record_tool_call`, `record_tool_result`, `to_atif()`. In-memory, serialised by the caller. |

### Tool registry + support (`agent/tools/`)

| File | Role |
| ---- | ---- |
| `registry.py` | `ToolCategory` enum (`FILE_OPS`, `SHELL`, `PROJECT`, `BUILD`, `WEB`, `NAV_OPS`, `MEMORY_OPS`, `GIT_OPS`, `DELEGATION_OPS`, `PLANNING`, `VIEW_GRAPH`). `Tool` dataclass (`name`, `description`, `parameters`, `executor`, `category`, `examples`, `system_prompt`). `ToolRegistry` with scope checks + edit-mode gating (`plan` / `ask` / `auto`). |
| `approval_manager.py` | Policy-gated synchronous approval for dangerous tools. Reads `TESSLATE_AGENT_APPROVAL_POLICY` env (`allow` default, `deny` otherwise). `ApprovalRequest` dataclass + `VALID_RESPONSES = {allow_once, allow_all, stop}`. |
| `retry_config.py` | Tenacity-based multi-layer retry. Retries `ConnectionError`, `TimeoutError`, transient `httpx.RequestError`, plus `IOError`/`OSError` minus `FileNotFoundError` / `PermissionError`. Exponential backoff 1s -> 2s -> 4s, up to 3 attempts. |
| `output_formatter.py` | `success_output()` / `error_output()` helpers. Produce standardized `{success, message, details, ...}` dicts consumed by every tool. |

### Tools (`agent/tools/<subdir>/`)

| Subdir | Tools | Register function |
| ------ | ----- | ----------------- |
| `file_ops/` | `read_file`, `write_file` (`read_write.py`); `read_many_files` (`read_many.py`); `patch_file`, `multi_edit` (`edit.py`); `apply_patch` (`apply_patch_tool.py`); `view_image` (`view_image.py`); `file_undo` (`undo_tool.py`). Shared `EDIT_HISTORY` ring buffer in `edit_history.py` powers undo. Multi-strategy matcher in `fuzzy_editor.py` (exact, flexible whitespace, Levenshtein, optional LLM repair). | `register_file_ops_tools` |
| `shell_ops/` | `bash_exec` (`bash.py`); `shell_open` / `shell_close` (`session.py`); `shell_exec` (`execute.py`); `write_stdin` (`write_stdin.py`); `list_background_processes` / `read_background_output` (`background.py`); `python_repl` (`python_repl.py`, per-session interpreter with deadline). Backed by shared PTY session registry in `tesslate_agent.orchestration`. | (see module `__init__.py`) |
| `nav_ops/` | `glob` (`glob_tool.py`, gitignore-aware); `grep` (`grep_tool.py`, ripgrep-backed with content/count/files modes); `list_dir` (`list_dir_tool.py`, bounded-depth paginated tree). | `register_nav_ops_tools` |
| `git_ops/` | `git_log`, `git_blame`, `git_status`, `git_diff`. All read-only via orchestrator `execute_command`. Porcelain parsers produce LLM-friendly dicts. | `register_git_ops_tools` |
| `web_ops/` | `web_fetch` (`fetch.py`, httpx with retry 1s/2s/4s); `web_search` (`search.py`). `providers.py` implements Tavily -> Brave -> DuckDuckGo fallback keyed by env vars `TAVILY_API_KEY`, `BRAVE_SEARCH_API_KEY`. | `register_web_ops_tools` |
| `memory_ops/` | `memory_read`, `memory_write`. `MemoryStore` is async lock-safe, persists sectioned markdown. `load_memory_prefix()` wraps memory for injection into the system prompt at startup. | `register_memory_ops_tools` |
| `planning_ops/` | `update_plan`. `PLAN_STORE`, `PlanStep`, `PlanState` for structured multi-step plans. | `register_planning_ops_tools` |
| `delegation_ops/` | `task`, `wait_agent`, `send_message_to_agent`, `close_agent`, `list_agents`. `SUBAGENT_REGISTRY` (module-global), `SubagentRecord`, `SubagentRegistry`. Depth limit: `MAX_SUBAGENT_DEPTH`. | `register_delegation_ops_tools` |

### Orchestration (`src/tesslate_agent/orchestration/`)

| File | Role |
| ---- | ---- |
| `base.py` | `BaseOrchestrator` ABC. Slim file + shell ops interface; no project/container lifecycle. Implementations expose filesystem + shell primitives scoped to a single project root. |
| `local.py` | `LocalOrchestrator`. Filesystem + subprocess backend for sandboxed hosts. Project root from `PROJECT_ROOT` env var (fallback `cwd`). Ignores container/volume/cache identifiers. Honors `subdir`. Post-symlink root containment check refuses escapes. |
| `factory.py` | `OrchestratorFactory`. Pluggable registry keyed by `DeploymentMode`. Caches instances. Registers the `local` backend at import; downstream packages register Docker / K8s. |
| `deployment_mode.py` | `DeploymentMode` StrEnum: `DOCKER`, `KUBERNETES`, `LOCAL`. `from_string()` parser. |

### CLI (`src/tesslate_agent/cli/`)

| File | Role |
| ---- | ---- |
| `__main__.py` | Entry for `tesslate-agent` console script. Argparse: `run --task ... --model ... --workdir ... --output trajectory.json`, `tools list`, `--version`. Exit code `3` on argparse error. |
| `runner.py` | `run_agent()` coroutine. Pins `DEPLOYMENT_MODE=local` + `PROJECT_ROOT=<workdir>` before importing anything that caches an orchestrator. Builds context, instantiates `TesslateAgent`, drives the loop, always writes an ATIF trajectory before returning. |
| `context.py` | Context builders. `StubUser` dataclass (id/email/display_name). `make_standalone_context()` synthesises project identifiers from the working directory so the agent's tool context matches the orchestrator shape. |
| `prompts.py` | Default system prompts tuned for long-horizon autonomous work (`DEFAULT_BENCHMARK_SYSTEM_PROMPT`). Covers grounding rules, convention matching, scope discipline, tool usage guidance. |
| `trajectory_bridge.py` | Adapter that consumes `TesslateAgent`'s event stream and feeds a `TrajectoryRecorder`. Normalises tool calls/results, assistant turns, errors, final answer. `finalize()` returns the ATIF dict. |

### Tests (`packages/tesslate-agent/tests/`)

Pytest with `asyncio_mode = "auto"`. Suites mirror the source tree:

- `agent/test_litellm_adapter.py`, `test_registry.py`, `test_tesslate_agent.py`
- `agent/tools/{file_ops,shell_ops,nav_ops,git_ops,web_ops,memory_ops,planning_ops,delegation_ops}/test_*.py` with `conftest.py` fixtures
- `cli/test_runner_smoke.py`
- `orchestration/test_local_orchestrator.py`

## tesslate-app-sdk (py)

Async Python SDK for authoring and managing Tesslate Apps.

| File | Role |
| ---- | ---- |
| `packages/tesslate-app-sdk/py/pyproject.toml` | Package manifest. Runtime deps: `httpx`, `pydantic`. |
| `packages/tesslate-app-sdk/py/README.md` | Install + usage (`ManifestBuilder` fluent API, `AppClient` context manager). Bearer-only auth (`tsk_*`), no CSRF needed. |
| `packages/tesslate-app-sdk/py/src/tesslate_app_sdk/__init__.py` | Re-exports `AppClient`, `AppSdkOptions`, `AppSdkHttpError`, `AppManifest_2025_01`, `ManifestBuilder`. |
| `packages/tesslate-app-sdk/py/src/tesslate_app_sdk/client.py` | `AppClient` (httpx.AsyncClient wrapper), `AppSdkOptions` (validates `tsk_` prefix), `AppSdkHttpError`. Covers version info, manifest publish, install, invoke, list, uninstall. |
| `packages/tesslate-app-sdk/py/src/tesslate_app_sdk/manifest.py` | Pydantic models `AppManifestApp`, `AppManifestSurface`, `AppManifestBilling`, `AppManifestCompatibility`, `AppManifest_2025_01`. `ManifestBuilder` fluent builder. Canonical schema: `docs/specs/app-manifest-2025-01.md`. |
| `packages/tesslate-app-sdk/py/tests/test_client.py` | httpx MockTransport-based client tests. |

## tesslate-app-sdk (ts)

Parallel TypeScript SDK for Node / browser callers.

| File | Role |
| ---- | ---- |
| `packages/tesslate-app-sdk/ts/package.json` | npm manifest. Zero runtime deps; uses global fetch. |
| `packages/tesslate-app-sdk/ts/README.md` | Install + usage examples. |
| `packages/tesslate-app-sdk/ts/vitest.config.ts` | Vitest config. |
| `packages/tesslate-app-sdk/ts/src/index.ts` | `AppSdkOptions` (`baseUrl`, `apiKey: tsk_*`, injectable `fetch`). Manifest interfaces mirror the pydantic model (`AppManifest2025_01`, surface/billing/compat sub-types). Client class exposes the same REST surface as the Python SDK. |
| `packages/tesslate-app-sdk/ts/src/index.test.ts` | Vitest suite driven via an injectable fetch mock. |

## tesslate-embed-sdk

iframe-side postMessage client for Tesslate Apps rendered inside the Studio shell.

| File | Role |
| ---- | ---- |
| `packages/tesslate-embed-sdk/package.json` | npm manifest (`@tesslate/embed-sdk`). |
| `packages/tesslate-embed-sdk/README.md` | Usage, envelope protocol (`v:1`), origin-pinning notes. |
| `packages/tesslate-embed-sdk/vitest.config.ts` | Vitest config. |
| `packages/tesslate-embed-sdk/src/types.ts` | `EnvelopeKind = "request" | "response" | "event"`, `EmbedEnvelope<T>` (`v:1`, id, topic, payload, optional `error: {code, message}`), `EmbedClientOptions` (`targetOrigin` required, wildcard rejected; `timeoutMs` default 10_000). |
| `packages/tesslate-embed-sdk/src/index.ts` | `EmbedClient` class. `request<Req, Res>(topic, payload)` returns typed promise; pending map keyed by UUID with timeout timer. `on<T>(event, handler)` returns unsubscribe. `dispose()` rejects in-flight requests and removes listener. Origin-pinned on both send and receive. `EmbedRemoteError` for server-side errors. `createEmbedClient()` factory. |
| `packages/tesslate-embed-sdk/src/index.test.ts` | Vitest suite with injected `win` / `parentWin` stubs. |

## Integration Points

### Cloud worker (ARQ)

The ARQ worker (`orchestrator/app/worker.py`) drives agent tasks via the adapter, not by calling `tesslate-agent` directly.

Adapter: `orchestrator/app/services/tesslate_agent_adapter.py`

Responsibilities:
1. Re-exports `TesslateAgent` and `AbstractAgent` under stable local names.
2. `run_turn()` drives a single request/response cycle and writes each trajectory event as an `AgentStep` row (append-only) so real-time Redis streams remain functional.
3. `AgentAdapterContext` is the neutral invocation envelope shared by routers and the worker.

### Desktop sidecar (PyInstaller)

The desktop sidecar imports `tesslate-agent` directly (no adapter layer). It replaces the legacy inline `stream_agent.py` for the Tauri shell's local orchestration path. Hidden-imports list in `desktop/sidecar/spec/_common.py` includes `tesslate_agent`, `tesslate_agent.agent`, `tesslate_agent.agent.tools`, `tesslate_agent.orchestration`.

### External agent API

`POST /api/external/agent/invoke` enqueues tasks to the same ARQ queue, so it also runs through the adapter. See `docs/orchestrator/routers/external-agent.md`.

## Related Contexts

- `docs/desktop/CLAUDE.md`: desktop sidecar and direct tesslate-agent usage
- `docs/orchestrator/agent/CLAUDE.md`: legacy inline agent (`stream_agent.py`, `factory.py`, `tools/`)
- `docs/orchestrator/services/worker.md`: ARQ worker task lifecycle
- `docs/sdk/CLAUDE.md`: the top-level `sdk/` TypeScript SDK (separate from these packages)
- `orchestrator/app/services/tesslate_agent_adapter.py`: adapter source

## When to Load

Load this context when:
- Working on the agent runner (`packages/tesslate-agent/`)
- Debugging why agent behavior differs between cloud and desktop
- Adding or changing tools that must be registered in `ToolRegistry`
- Maintaining the adapter (`tesslate_agent_adapter.py`) or the ARQ worker
- Building or consuming either `tesslate-app-sdk` variant or `tesslate-embed-sdk`
- Investigating the migration path from the legacy inline agent
