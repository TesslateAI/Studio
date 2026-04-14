# Desktop agents: tickets, budgets, approvals

Multi-agent orchestration primitives used by the desktop unified workspace.
All three services share the same `agent_tasks` table and are designed to be
non-blocking / pause-not-crash — a failed budget check or a missing approval
never tears down the worker.

## Ticket allocator

File: `/orchestrator/app/services/agent_tickets.py`.

Tickets are `AgentTask` rows identified by a globally monotonic human-readable
`ref_id` of the form `TSK-NNNN` (`REF_PREFIX = "TSK-"`, `REF_WIDTH = 4`).
`next_ref_id()` uses `max(cast(substr(ref_id, 5), Integer))` so the query runs
on both SQLite and Postgres without window functions.

API:

| Function                                | Purpose                                              |
| --------------------------------------- | ---------------------------------------------------- |
| `next_ref_id(session)`                  | Compute the next free `TSK-NNNN`.                    |
| `create_ticket(session, *, project_id, title, assignee_agent_id=…, parent_task_id=…, goal_ancestry=…, requires_approval_for=…)` | Allocate `ref_id` and insert a `queued` ticket. |
| `checkout_ticket(session, *, worker_id, project_id=None)` | Atomic pop: `UPDATE … WHERE id IN (SELECT id … LIMIT 1) RETURNING id`. Returns the claimed `AgentTask` or `None`. |
| `finish_ticket(session, *, ticket_id, status)` | Mark ticket terminal (`completed` / `failed` / `cancelled`). |

The single-statement `UPDATE … RETURNING` with a scalar subquery over
`status == "queued"` ordered by `created_at` guarantees atomicity on SQLite
and Postgres; concurrent workers cannot double-claim.

## Budget interceptor

File: `/orchestrator/app/services/agent_budget.py`.

Per-agent monthly USD caps from the `agent_budgets` table, with project-scope
override precedence:

1. `(agent_id, project_id)` row — project-scoped.
2. `(agent_id, NULL)` row — agent-wide fallback.
3. Neither → `_UNLIMITED` (`ok=True, remaining_usd=Infinity`).

```python
BudgetStatus(ok: bool, remaining_usd: Decimal, reason: str | None)
```

`check_budget(session, *, agent_id, project_id=None, pending_usd=0)` returns
`ok=False, reason="monthly budget exhausted"` when `spent + pending > limit`.

**Never raises.** Unexpected dialect/row errors log at `debug` and return
`_UNLIMITED` so the budget can never become a correctness-critical dependency
(pause-not-crash policy). `record_spend()` and `reset_if_due()` follow the
same defensive pattern. `RESET_WINDOW_DAYS = 30`.

## Approval gate

File: `/orchestrator/app/services/agent_approval.py`.

`AgentTask.requires_approval_for` is a JSON list of tool names. The `str[]`
shape is the entire contract — any tool whose name matches is gated.

```python
class ApprovalRequired(Exception):
    tool_name: str
    ticket_id: uuid.UUID
```

`check_tool_allowed(session, *, ticket_id, tool_name)`:

- No matching ticket → no-op (already resolved upstream).
- Empty / missing `requires_approval_for` → no-op.
- `tool_name` not in the list → no-op.
- Match → flip `status = "awaiting_approval"`, commit, raise
  `ApprovalRequired`. The caller suspends the run cleanly; the worker loop
  treats this as a clean pause rather than a crash.

`approve_ticket(session, *, ticket_id)` flips the row back to `queued` for
the next worker checkout.

## Endpoints

Router: `/orchestrator/app/routers/desktop/ (tickets.py, sessions.py)`.

### `GET /api/desktop/agents/tickets`

Query params (all optional): `project_id: UUID`, `status: str`. Returns
`{tickets: [_serialize_ticket(t), ...]}`. Each ticket shape:

```json
{
  "id": "<uuid>",
  "ref_id": "TSK-0042",
  "project_id": "<uuid>",
  "parent_task_id": "<uuid>|null",
  "status": "queued|running|awaiting_approval|completed|failed|cancelled",
  "title": "...",
  "assignee_agent_id": "<uuid>|null",
  "requires_approval_for": ["bash", ...],
  "goal_ancestry": ["cloud:xyz", ...],
  "created_at": "...",
  "updated_at": "...",
  "completed_at": "..."|null
}
```

### `POST /api/desktop/agents/{ticket_id}/approve`

Loads the ticket (404 if missing), calls `approve_ticket()`, returns
`{ticket_id, status: "queued"}`.

### `GET /api/desktop/agents/sessions` (unified-workspace filter matrix)

Same row shape as `/tickets` but eager-loads `AgentTask.directories` +
`AgentTask.project` and adds `source: "local"` plus a `directories: [{id,
path}]` array.

Filter matrix:

| Query param    | Effect                                                         |
| -------------- | -------------------------------------------------------------- |
| `project_id`   | `AgentTask.project_id == project_id`                           |
| `status`       | `AgentTask.status == status`                                   |
| `directory_id` | `AgentTask.directories.any(Directory.id == directory_id)`     |
| `runtime`      | `AgentTask.directories.any(Directory.runtime == runtime)`      |

Filters combine with `AND`. Result ordered by `created_at`, deduped by id.

### `GET /api/desktop/agents/{ticket_id}/diff`

Placeholder: returns `{ticket_id, trajectory: [], diff: ""}`. Real trajectory
+ diff wiring lands with `handoff_client` maturation (see
`/docs/desktop/unified-workspace.md`).

## Related

- `/docs/desktop/unified-workspace.md` — `Directory` ↔ `AgentTask` join, handoff bundle.
- `/docs/orchestrator/agent/CLAUDE.md` — agent loop integration points.
