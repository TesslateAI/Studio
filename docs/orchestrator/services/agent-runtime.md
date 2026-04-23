# Agent Runtime Services

Services that support AI agent execution beyond the core loop: approval gating, budget enforcement, ticket allocation, audit logging, model adapters, context compaction, prompt caching, and the submodule adapter to `packages/tesslate-agent`.

The core agent loop itself lives in `packages/tesslate-agent` (see [../../packages/CLAUDE.md](../../packages/CLAUDE.md)); this doc covers the orchestrator-side support services.

## When to load

Load this doc when:
- Gating agent actions on approval or budget limits.
- Debugging model-specific adapter behavior (Anthropic vs OpenAI vs Bedrock).
- Tuning context compaction thresholds.
- Adding a new subagent type.
- Wiring provider-specific prompt caching (Anthropic cache breakpoints).

## File map

### Multi-agent orchestration primitives

| File | Purpose |
|------|---------|
| `agent_approval.py` | Approval gate for multi-agent orchestration. Pauses a ticket until a user or lead agent approves. |
| `agent_budget.py` | Budget interceptor. Pre-request credit checks against LiteLLM key ledger; blocks when insufficient. |
| `agent_tickets.py` | Ticket allocator for multi-agent orchestration. Issues unique ticket ids used for approval, budget, and audit correlation. |
| `agent_audit.py` | Audit logging for agent command executions. Writes `AuditLog` rows per tool call. |

### Planning and sub-agents

| File | Purpose |
|------|---------|
| `plan_manager.py` | In-memory plan storage keyed by `user_{id}_project_{id}` so plans persist across agent iterations within a run. Same pattern as the `todos` tool. |
| `subagent_configs.py` | `SubagentConfig` dataclass plus built-in subagent-type registry. Inline prompt templates were removed during the bridge cutover; configs reference templates on disk. |

### Context and prompt plumbing

| File | Purpose |
|------|---------|
| `context_compaction.py` | Five-phase `ContextCompressor`. Triggered when the conversation approaches the context-window limit. Ported from Hermes-style structured compression onto the async `ModelAdapter` interface. |
| `prompt_caching.py` | Injects `cache_control` breakpoints into message arrays for providers that support explicit prompt caching (Anthropic Claude on Bedrock or direct API). |

### Model adapters

| File | Purpose |
|------|---------|
| `model_adapters.py` | Per-provider adapters that normalize model APIs to one interface. Lets the agent core run unchanged across Anthropic, OpenAI, Bedrock, etc. |
| `model_health.py` | Background health checker. Runs a tiny completion against each LiteLLM model every 10 minutes; caches results for `/api/marketplace/models`. |
| `model_vision.py` | Fetches `supports_vision` per model from LiteLLM `/model/info`. Cached 5 minutes (same pattern as `model_pricing.py`). |

### Submodule adapter and parser

| File | Purpose |
|------|---------|
| `tesslate_agent_adapter.py` | Adapter between the orchestrator and the versioned `tesslate-agent` package. Re-exports `TesslateAgent` / `AbstractAgent` under stable local names; `TesslateAgentAdapter.inner` preserves the raw submodule instance for direct access. |
| `tesslate_parser.py` | Parses `TESSLATE.md` from base repositories to extract dev-server startup commands, port config, and framework hints. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| `worker.py` (`execute_agent_task`) | `tesslate_agent_adapter`, `agent_audit`, `agent_budget`, `context_compaction`, `prompt_caching`, `model_adapters` |
| `routers/chat.py` (cloud SSE path) | `agent_budget`, `agent_audit`, `plan_manager` |
| `services/apps/hosted_agent_runtime.py` | `subagent_configs`, `agent_tickets` |
| ARQ cron `model_health_probe` | `model_health` |
| `routers/marketplace.py` (models list) | `model_health`, `model_vision`, `model_pricing` |

## Related

- [worker.md](./worker.md): worker bodies that drive this runtime.
- [agent-context.md](./agent-context.md): pre-run context assembly.
- [litellm.md](./litellm.md): LiteLLM proxy and key management.
- [credit-system.md](./credit-system.md): credit deduction wired to `agent_budget`.
- [../../packages/CLAUDE.md](../../packages/CLAUDE.md): versioned agent package.
