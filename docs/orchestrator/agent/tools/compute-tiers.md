# Compute Tiers in Agent Tools

**Applies to**: Kubernetes deployment mode only. Docker mode has no tiering — all `tier` / `container` params are accepted for forward-compat and ignored.

## The two tiers

| Tier | Name | Where it runs | Lifecycle | Use for |
|---|---|---|---|---|
| **1** | `ephemeral` | Short-lived pod in `tesslate-compute-pool` namespace | One-shot — pod dies after the command finishes | Isolated reads/writes against the project volume, quick scripts, no service dependencies |
| **2** | `environment` | Per-project pods in `proj-{project_id}` namespace | Persistent — started by `project_start`, stopped by `project_stop` | Anything that needs services reachable (databases, APIs), network, long-running processes, interactive shells |

Tier 1 pods mount the project volume but run in the generic ephemeral image — service containers are **not** running, and `localhost:PORT` points nowhere. Tier 2 is the full project environment with every container from `.tesslate/config.json` up.

## Picking a tier with `bash_exec`

```json
{"tool_name": "bash_exec", "parameters": {"command": "pwd", "tier": "auto"}}
```

| `tier` | Routing |
|---|---|
| `auto` *(default)* | Uses Tier 2 if `project.compute_tier == "environment"`, else Tier 1. Preserves pre-existing implicit routing. |
| `ephemeral` | Always Tier 1 — one-shot isolated pod. Good for "just look at a file" on the volume without waking the env. |
| `environment` | Always Tier 2 — execs into the running dev container. **Requires the environment to already be running** (see below). |

When the agent passes a `tier` that disagrees with the project's current `compute_tier`, an audit log row (`agent.exec.tier_override`) is written.

## Picking a container in Tier 2

For multi-container projects, `bash_exec` accepts a `container` param (Tier 2 only — ignored in ephemeral mode):

```json
{"tool_name": "bash_exec", "parameters": {"command": "ps aux", "tier": "environment", "container": "backend"}}
```

`shell_open` also accepts `container` for the same purpose.

## When the environment is not running

There is **no auto-wake**. If you call `bash_exec` with `tier="environment"` or `shell_open` and the project's Tier 2 pods are not up, you get a structured error:

```json
{
  "success": false,
  "message": "Tier 2 environment is not running",
  "suggestion": "Call project_start to start the environment, then retry bash_exec...",
  "details": {
    "tier": "environment",
    "next_tool": "project_start",
    "namespace": "proj-...",
    "reason": "namespace_not_found" | "no_running_dev_pod" | "dev_container_not_running"
  }
}
```

The recovery flow is:

1. Read `details.next_tool` → `project_start`
2. Call `project_start` (no params — blocks ~5s warm / ~60s cold until pods are Ready)
3. Retry the original `bash_exec` / `shell_open`

For quick isolated commands that don't need the environment, switch to `tier="ephemeral"` instead of starting it.

## Checking tier state without running anything

Use `project_control` with `action="tier_status"`:

```json
{"tool_name": "project_control", "parameters": {"action": "tier_status"}}
```

Returns:

```json
{
  "compute_tier": "none" | "ephemeral" | "environment",
  "active_compute_pod": "<pod-name>" | null,
  "environment_status": "stopped" | "starting" | "active" | "error" | "provisioning" | "hibernated",
  "last_activity": "<iso8601>" | null,
  "namespace": "proj-<id>" | null,
  "containers": [
    {"name": "frontend", "status": "running", "ready": true, "is_primary": true, "container_type": "base"}
  ]
}
```

Reads are DB-only — no K8s API calls. Call this before `bash_exec` with `tier="environment"` if the agent isn't sure the env is up.

## What `shell_open` can and cannot do

- Tier 2 only. There is no persistent shell on Tier 1 ephemeral pods yet.
- Requires the dev container to be running — fails with the same structured error as `bash_exec` when it isn't.
- Accepts `container` for multi-container targeting.

## Required context keys

Agent tools that interact with the tier system read these keys from the execution context:

| Key | Source | Required for | Notes |
|---|---|---|---|
| `volume_id` | `Project.volume_id` | Tier 1 ephemeral pod scheduling, Tier 2 volume hints | Tool errors if missing in K8s mode |
| `cache_node` | `Project.cache_node` | Volume placement hint | Hub is the live source of truth; DB hint only |
| `compute_tier` | `Project.compute_tier` | `auto` tier routing on `bash_exec` | |
| `active_compute_pod` | `Project.active_compute_pod` | Agent visibility into what's running | |
| `environment_status` | `Project.environment_status` | Agent visibility into env state | |
| `containers` | `Container.*` for the project | Multi-container routing and agent visibility | List of `{name, status, ready, is_primary, container_type}` |
| `container_name` | Resolved from request or default container | Default target when `container` param is omitted | |

Populated in two places today — keep them in sync when adding a third:
- `orchestrator/app/routers/chat.py` (three sites — `/api/chat/agent/stream`, legacy handler, unified handler)
- `orchestrator/app/worker.py` (ARQ worker — `AgentTaskPayload` → context)

Both call `build_tier_snapshot(project, db)` in `orchestrator/app/services/agent_context.py` to produce the container list. Reuse that helper from any new enqueue site.

## Related tools

| Tool | Purpose |
|---|---|
| `project_start` / `project_stop` / `project_restart` | Tier 2 environment lifecycle. `project_ops/project_lifecycle.py`. |
| `container_start` / `container_stop` / `container_restart` | Single-container lifecycle inside Tier 2. `project_ops/container_lifecycle.py`. |
| `bash_exec` | Shell command execution with tier routing. `shell_ops/bash.py`. |
| `shell_open` / `shell_exec` / `shell_close` | Persistent PTY session (Tier 2 only). `shell_ops/session.py` + `execute.py`. |
| `project_control tier_status` | Read-only tier state snapshot. `project_ops/project_control.py`. |
