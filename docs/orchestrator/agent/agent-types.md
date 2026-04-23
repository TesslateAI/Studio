# Agent Runner (Submodule Handoff)

> The former `StreamAgent`, `IterativeAgent`, `ReActAgent`, and `TesslateAgent` classes have been removed from `orchestrator/app/agent/`. OpenSail now runs agents through the `packages/tesslate-agent` submodule.

## Where the Code Lives

| Layer | Path | Owner |
|-------|------|-------|
| Orchestrator entrypoint | `orchestrator/app/services/tesslate_agent_adapter.py` | Orchestrator |
| Agent runner | `packages/tesslate-agent/tesslate_agent/` | Packages repo |
| Tool registry consumed by runner | `orchestrator/app/agent/tools/` | Orchestrator |
| Task queue dispatcher | `orchestrator/app/worker.py` + `orchestrator/app/services/agent_handlers.py` | Orchestrator |

## What the Orchestrator Provides

| Responsibility | Where |
|----------------|-------|
| Build `AgentTaskPayload` | `orchestrator/app/services/agent_context.py` + `agent_task.py` |
| Queue a task | `ArqTaskQueue.enqueue` (cloud) or `LocalTaskQueue.enqueue` (desktop) |
| Pick up the job | `app.worker.WorkerSettings` -> `agent_handlers.handle_agent_task` |
| Build tool registry | `create_scoped_tool_registry(names, tool_configs)` in `tools/registry.py` |
| Resolve model / BYOK provider | `packages/tesslate-agent` plus DB lookups (`UserProvider`, `UserCustomModel`) |
| Stream events back | `orchestrator/app/services/pubsub.py` (Redis Streams cloud, in-process desktop) |
| Progressive persistence | `AgentStep` rows written per iteration |

## What the Submodule Provides

Features documented in `docs/packages/CLAUDE.md`:

- Native function-calling loop with `text_delta` streaming
- Planner / plan mode (`plan_manager` in packages)
- Context compaction with optional cheaper auxiliary model
- Subagent orchestration (paired with orchestrator `delegation_ops` tools)
- Prompt caching breakpoints (system + trailing rolling window)
- Trajectory recording for replay and analytics
- Extended thinking routing (Anthropic / DeepSeek effort levels)

## Invocation Flow

```
POST /api/chat/agent/stream
  routers/chat.py
    services.agent_context.build_agent_task_payload()
    task_queue.enqueue(handle_agent_task)
        -> worker.py picks up job
           agent_handlers.handle_agent_task(payload)
             tools = create_scoped_tool_registry(agent.tools, agent.tool_configs)
             runner = TesslateAgentRunner(tools=tools, ...)
             async for ev in runner.run(...):  pubsub.publish(ev)
```

For the external API flow (`POST /api/external/agent/invoke`), substitute `routers/external_agent.py` at the top. The rest of the pipeline is identical.

## Related Docs

- `docs/packages/CLAUDE.md`: runner internals.
- `docs/orchestrator/services/task-queue.md`: ARQ vs local queue.
- `docs/orchestrator/services/pubsub.md`: Redis Streams wiring.
- `docs/guides/real-time-agent-architecture.md`: end-to-end real-time flow.
- `docs/orchestrator/routers/external-agent.md`: external API surface.
