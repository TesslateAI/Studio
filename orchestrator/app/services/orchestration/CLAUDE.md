# Orchestration services context

## Purpose
Container / filesystem / process orchestrators that implement
`BaseOrchestrator`. A factory (`factory.py`) picks the right backend per
project row via `Project.runtime` (`local` | `docker` | `k8s`). For desktop
shells with no per-row override, the default is `local`.

## Key files
- `base.py` — abstract backend interface (all file-op + lifecycle methods).
- `deployment_mode.py` — `DeploymentMode` enum including `DESKTOP`.
- `factory.py` — `OrchestratorFactory.resolve_for_project(project)`.
- `local.py` — filesystem + subprocess backend. `_get_project_root(project)`
  returns `$OPENSAIL_HOME/projects/{slug}-{id}` under desktop mode,
  else falls back to `$PROJECT_ROOT` / `cwd`.
- `local_ports.py` — per-project host-port allocator for the local runtime.
  Persists to `$OPENSAIL_HOME/cache/ports.json` (atomic write).
  Reclaims ports whose owning pid is gone via `reclaim_dead`.
- `docker.py`, `kubernetes_orchestrator.py` — production backends.

## Related contexts
- `docs/orchestrator/orchestration/CLAUDE.md` — cross-backend architecture.
- `app/services/desktop_paths.py` — `$OPENSAIL_HOME` resolver.

## When to load
Load when touching orchestrator backends, the per-project runtime selector,
or desktop local-runtime filesystem / port behavior.
