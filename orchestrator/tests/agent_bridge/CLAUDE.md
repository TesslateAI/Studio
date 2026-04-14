# tests/agent_bridge

## Purpose
Verify the `app.services.tesslate_agent_bridge` seam imports cleanly from
the `tesslate-agent` submodule. These tests guard the contract between the
orchestrator and the agent package without booting a full agent run.

## Key files
- `test_bridge_import.py` — import smoke test + construction smoke test

## Related contexts
- `/orchestrator/app/services/tesslate_agent_bridge.py`
- `/packages/tesslate-agent/src/tesslate_agent/agent/tesslate_agent.py`

## When to load
Touching the bridge surface or the submodule entry point.
