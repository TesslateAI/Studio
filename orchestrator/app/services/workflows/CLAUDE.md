# services/workflows/

The workflow engine: turns a multi-action `AutomationDefinition` into a step graph and walks it. Plugs into the existing automations dispatcher in `services/automations/dispatcher.py` for multi-step automations only; single-action automations stay on the legacy path.

Tracking issue: #469 (epic). Phase A scope: #470.

## What lives here

- `engine.py` — the driver. `execute_workflow(...)` is called by the dispatcher when `len(actions) > 1`. Walks actions in ordinal order, instantiates the registered handler per step, persists one `AutomationStepRun` row per step, returns the FINAL step's output dict so the dispatcher's existing `_deliver_and_finalize` works unchanged.
- `handlers/base.py` — `StepHandler` Protocol + `register_handler` decorator + `get_handler` lookup. The registry is a process-global dict; tests can `reset_registry()` between cases.
- `handlers/agent_turn.py`, `app_action.py`, `gateway_send.py` — Phase A handlers that wrap the existing `_dispatch_*` functions in `services/automations/dispatcher.py`. Lazy imports avoid the circular dependency since the dispatcher imports the engine lazily inside `dispatch_automation`.
- Future phases add: `handlers/approval_gate.py`, `handlers/deliver.py` (Phase D), `handlers/branch.py`, `handlers/parallel.py`, `handlers/sub_workflow.py` (Phase F), and `runners/` for compute-profile aware step execution (Phase B).

## How to add a new step kind

1. Drop a file under `handlers/` with a class that has `kind: ClassVar[str]` and `async def execute(self, ctx) -> StepResult`.
2. Decorate the class with `@register_handler`.
3. Import the module from `handlers/__init__.py` so its registration runs at package import time.
4. The engine picks it up automatically. No engine.py change needed.

The CHECK constraint on `automation_actions.action_type` is permissive enough to accept new kinds the engine adds without a migration round (see `models_automations.py:AutomationAction` doc).

## Phase A constraint: synchronous steps only

A step that hands off async (returns `{"enqueued": True}`, e.g. tier-0 `agent.run`) is rejected mid-graph with a typed `AsyncStepInMultiStepError`. Phase B wires the worker callback so an async step can advance the engine, after which the constraint relaxes. Single-step tier-0 automations stay on the legacy dispatcher path and are unaffected.

## Related contexts

- Caller: `app/services/automations/dispatcher.py` (lazy imports `engine.execute_workflow` when `len(actions) > 1`).
- Schema: `models_automations.AutomationStepRun` (migration 0099). Status enum mirrors `AutomationRun.status` plus `skipped`.
- Tests: `tests/services/workflows/`. The test fixture uses `Base.metadata.create_all` against in-memory SQLite to sidestep an unrelated migration 0089 SQLite batch issue.
