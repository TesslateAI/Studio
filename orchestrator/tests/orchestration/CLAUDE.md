# tests/orchestration

## Purpose
Unit tests for the local-runtime orchestration helpers: per-project root
resolution and the host-port allocator. Pure in-memory / tmpdir; no
Docker, k8s, or network dependencies.

## Key files
- `test_local_ports.py` — allocate/release/reclaim + persistence round-trip.
- `test_local_project_root.py` — per-project root resolution under desktop
  mode is disjoint across projects.

## Related contexts
- `app/services/orchestration/CLAUDE.md`
- `tests/services/orchestration/` — pre-existing `LocalOrchestrator` tests
  (file ops, PTY, exec).

## When to load
Load when changing the port allocator, `_get_project_root`, or adding new
local-runtime unit tests.
