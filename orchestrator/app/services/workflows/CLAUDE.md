# services/workflows/

The workflow engine + the self-evolving agent surface (G-track, issue #469).
Turns a multi-action `AutomationDefinition` into a step graph and walks it,
keeps an immutable history of every shape change, lets agents propose new
shapes through an approval pipeline, and (optionally) lets a per-workflow
"doctor" agent draft fixes when a workflow keeps failing.

Tracking issue: #469 (epic). Phases A–G shipped on `feat/workflow-engine`.

## Layers

### Engine (Phases A–F)

- `engine.py` — `execute_workflow(...)` is called by the dispatcher when
  `len(actions) > 1`. Walks actions in ordinal order, instantiates the
  registered handler per step, persists one `AutomationStepRun` row per
  step, and returns the FINAL step's output so the dispatcher's existing
  `_deliver_and_finalize` works unchanged.
- `handlers/base.py` — `StepHandler` Protocol + `register_handler`
  decorator + `get_handler` lookup. Process-global registry; tests can
  `reset_registry()` between cases.
- Step kinds: `agent_turn.py` (`agent.run`), `app_action.py`
  (`app.invoke`), `gateway_send.py` (`gateway.send`), `deliver.py`
  (Phase D), `branch.py`, `sub_workflow.py` (Phase F). The CHECK
  constraint on `automation_actions.action_type` accepts new kinds
  without a migration round.
- `runners/` — compute-profile aware step execution (Phase B).
- `event_log.py` — append-only run-event writes. `emit_run_finished`
  (G5) fans out a synthetic `run.failed` workflow_event when a run
  lands on a non-`succeeded` terminal status; subscribers (the
  per-workflow doctor) get a fresh `AutomationEvent` to react to.

### Self-evolving track (Phases G1–G7)

- `versions.py` — `snapshot_definition_to_version(...)` writes one
  immutable `WorkflowVersion` per shape change. `head_version_id` on
  the definition is the live pointer; every run stamps its
  `workflow_version_id`.
- `proposals.py` — `WorkflowProposal` lifecycle: create / list / get /
  decide / withdraw / apply. `create_proposal` computes a structured
  `diff_summary` that deep-walks `contract` child keys so policy
  allow-lists like `["contract.allowed_tools"]` are reachable.
  Auto-apply path (G3): if `auto_apply_policy` matches AND `dry_run`
  passes, applies immediately and bumps the diff budget. `apply_proposal`
  refuses callers that supply neither `actor_user_id` nor
  `proposer_user_id` (defense in depth against a skipped route auth).
- `dry_run.py` — pure-static validation of a proposed payload before
  it ever touches a definition row.
- `health.py` — `compute_snapshot(...)` reads runs/steps/events/proposals
  for one automation in one window and upserts a
  `WorkflowHealthSnapshot`. Doctor reads these via the
  `read_workflow_history` tool.
- `doctor.py` — `ensure_doctor_for(target)` materialises a child
  `AutomationDefinition` whose contract is scoped to
  `allowed_workflow_ids: [target.id]`. The doctor's only trigger is a
  `workflow_event` subscription to the target's `run.failed` /
  `error.raised` / `step.failed`; its only action is an `agent.run`
  with `read_workflow_history` + `manage_workflow_proposal` in scope.
- `learnings.py` — `WorkflowLearning` cross-workflow team-scoped memory
  (G6) so multiple doctors share what they've learned.
- `convergence.py` — three guards keep agents from thrashing (G7):
  cooldown between self-edits, diff budget cap, generation rollback
  on bad health.

## How to add a new step kind

1. Drop a file under `handlers/` with a class that has
   `kind: ClassVar[str]` and `async def execute(self, ctx) -> StepResult`.
2. Decorate the class with `@register_handler`.
3. Import the module from `handlers/__init__.py` so registration runs
   at package import time.
4. The engine picks it up automatically. No engine.py change needed.

If the new kind needs its own DB transaction boundary (e.g. it dispatches
a child run that commits multiple times), build a fresh `AsyncSession`
bound to `ctx.db.bind` rather than reusing `ctx.db` — see
`handlers/sub_workflow.py` for the pattern.

## Constraint: synchronous steps only

A step that hands off async (returns `{"enqueued": True}`, e.g. tier-0
`agent.run`) is rejected mid-graph with a typed
`AsyncStepInMultiStepError`. Single-step tier-0 automations stay on the
legacy dispatcher path and are unaffected.

## Agent tool scope

Agent-callable tools that touch workflow rows
(`manage_workflow_proposal`, `read_workflow_history`) honour
`contract.allowed_workflow_ids` when set. The doctor relies on this
to prevent a doctor for workflow X from editing any of the owner's
other workflows. Empty / missing scope list falls through to the
original owner-only check — non-doctor agents are unaffected.

## Inbound triggers

Phase E adds `slack_message` + `email_inbound` trigger kinds.
Endpoints live at `/api/triggers/inbound/*` and REJECT unsigned
traffic (HMAC-SHA256 of `v0:{ts}:{body}` against
`settings.inbound_*_signing_secret`). Without the secrets configured
the routes return 503 — explicit failure beats accepting anonymous
internet traffic on a misconfigured deploy. Slack's native
`X-Slack-Signature` (`v0=<hex>`) is also accepted so subscriptions
work without an adapter.

## Related contexts

- Caller: `app/services/automations/dispatcher.py` (lazy-imports
  `engine.execute_workflow` when `len(actions) > 1`).
- Schemas: `models_automations.AutomationStepRun` (migration 0099);
  G-track models in `models_workflows.py` (migrations 0106–0112);
  workflow_event trigger index (migration 0113).
- Tests: `tests/services/workflows/` — `conftest.session_maker`
  fixture uses `Base.metadata.create_all` against in-memory SQLite to
  sidestep a pre-existing migration 0089 SQLite batch issue.
