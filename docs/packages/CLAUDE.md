# Purpose

Documents the `packages/` directory at the repo root. Each package is a standalone, versioned library that can be consumed by the orchestrator, desktop sidecar, or external products. This layer separates reusable logic from the FastAPI application code.

# Packages Overview

| Package | Language | Directory | Role |
|---------|----------|-----------|------|
| `tesslate-agent` | Python | `packages/tesslate-agent/` | Canonical agent runner — executes tool-calling loops, manages trajectory, streams events |
| `tesslate-app-sdk` | Python | `packages/tesslate-app-sdk/py/` | Sandboxed runtime SDK for apps built on Tesslate (MCP tools, skills, model proxy) |
| `tesslate-embed-sdk` | TypeScript | `packages/tesslate-embed-sdk/` | Client library for embedding the Studio UI into external products |

## tesslate-agent

Primary agent runner used by both the cloud worker and the desktop sidecar.

Key files:
- `packages/tesslate-agent/src/` — source root
- `packages/tesslate-agent/pyproject.toml` — package manifest and dependencies
- `packages/tesslate-agent/tests/` — unit and integration tests
- `packages/tesslate-agent/docs/` — package-level documentation
- `packages/tesslate-agent/examples/` — usage examples

Entry points exposed to the orchestrator:
- `tesslate_agent.agent.base.AbstractAgent` — abstract base class
- `tesslate_agent.agent.tesslate_agent.TesslateAgent` — concrete implementation
- `tesslate_agent.agent.tools.registry.ToolRegistry` — tool registration

The legacy inline agent lives at `orchestrator/app/agent/stream_agent.py` and `orchestrator/app/agent/factory.py`. It is being superseded by this package but may still run for specific flows during the transition.

## tesslate-app-sdk

Python SDK consumed by app creators writing applications that run on the platform. Provides a stable API surface for calling platform features without coupling to orchestrator internals.

Key files:
- `packages/tesslate-app-sdk/py/` — Python source
- `packages/tesslate-app-sdk/pyproject.toml` — package manifest

Covers: MCP tool invocation, skill loading, model proxy calls, sandboxed environment utilities.

## tesslate-embed-sdk

TypeScript library for embedding the Studio UI into external sites or products.

Key files:
- `packages/tesslate-embed-sdk/src/` — TypeScript source
- `packages/tesslate-embed-sdk/package.json` — npm manifest
- `packages/tesslate-embed-sdk/tsconfig.json` — TypeScript config
- `packages/tesslate-embed-sdk/vitest.config.ts` — test configuration

# Integration Points

## Cloud worker (ARQ)

The ARQ worker (`orchestrator/app/worker.py`) drives agent tasks via the adapter, not by calling `tesslate-agent` directly.

Adapter: `orchestrator/app/services/tesslate_agent_adapter.py`

Responsibilities of the adapter:
1. Re-exports `TesslateAgent` and `AbstractAgent` under stable local names.
2. `run_turn()` drives a single request/response cycle and writes each trajectory event as an `AgentStep` row (append-only) so real-time Redis streams remain functional.
3. `AgentAdapterContext` is the neutral invocation envelope shared by routers and the worker.

## Desktop sidecar (PyInstaller)

The desktop sidecar imports `tesslate-agent` directly (no adapter layer). It replaces the old inline `stream_agent.py` for the Tauri shell's local orchestration path.

See `docs/desktop/CLAUDE.md` for the full desktop architecture.

## External agent API

`POST /api/external/agent/invoke` enqueues tasks to the same ARQ queue, so it also runs through the adapter. See `docs/orchestrator/routers/external-agent.md`.

# Related Contexts

- `docs/desktop/CLAUDE.md` — desktop sidecar and direct tesslate-agent usage
- `docs/orchestrator/agent/CLAUDE.md` — legacy inline agent (stream_agent.py, factory.py, tools/)
- `docs/orchestrator/services/worker.md` — ARQ worker task lifecycle
- `orchestrator/app/services/tesslate_agent_adapter.py` — adapter source

# When to Load

Load this context when:
- Working on the agent runner itself (`packages/tesslate-agent/`)
- Debugging why agent behavior differs between cloud and desktop
- Adding or changing tools that must be registered in `ToolRegistry`
- Maintaining the adapter (`tesslate_agent_adapter.py`) or the ARQ worker
- Building or consuming `tesslate-app-sdk` or `tesslate-embed-sdk`
- Investigating the migration path from the legacy inline agent to this package
