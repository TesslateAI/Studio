# tests/agents

## Purpose
Unit coverage for the multi-agent orchestration skeleton:

- ticket allocator (`app/services/agent_tickets.py`)
- budget interceptor (`app/services/agent_budget.py`)
- approval gate (`app/services/agent_approval.py`)

Each test migrates a throwaway SQLite file to `head` so the schema
matches what ships in production, then exercises the services via a real
`AsyncSession`.

## Key files
- `conftest.py` — `sqlite_url`, `async_session`, `session_factory`
  fixtures + a `make_project_id` helper. SQLite FKs are off by default,
  which lets tests insert `agent_tasks` rows without seeding the full
  `projects` / `users` graph.
- `test_ticket_allocator.py` — ref_id monotonicity + concurrent checkout
  disjointness (10 workers over 10 queued tickets).
- `test_budget.py` — unlimited fallback, exhaustion blocking,
  agent-wide fallback, safe-degrade contract.
- `test_approval.py` — gated tool raises `ApprovalRequired` and flips
  status; approve flips back to `queued`.

## Related contexts
- `orchestrator/app/services/agent_tickets.py`
- `orchestrator/app/services/agent_budget.py`
- `orchestrator/app/services/agent_approval.py`
- `tests/migrations/test_0050_orchestration.py` — schema-level checks.

## When to load
Load when touching anything in the orchestration skeleton (ticket
lifecycle, budget math, approval gating) or when extending the
allocator to wire into the worker claim path.
