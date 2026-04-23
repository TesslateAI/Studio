# Compute Lifecycle Services

Services that manage the lifecycle of compute pods (K8s) and Docker containers beyond initial start/stop: quota enforcement, idle shutdown, hibernation, checkpointing, activity tracking, and namespace garbage collection.

## When to load

Load this doc when:
- Debugging idle timeouts or unexpected hibernation.
- Tuning the orphaned-pod reaper or namespace reaper intervals.
- Adding new activity signals that should keep a project alive.
- Writing a new checkpoint or hibernation path.

## File map

| File | Purpose |
|------|---------|
| `compute_manager.py` | Central quota enforcement for compute pods. Tracks per-user concurrent pod count, enforces `compute_max_concurrent_pods`, looks up container status by container id, reaps orphaned pods past `compute_pod_timeout`. |
| `hibernate.py` | Shared hibernation logic used by the user-facing hibernate endpoint and the idle monitor. Stops compute, syncs volume back to the Hub, transitions project to `hibernated`. |
| `idle_monitor.py` | Background loop that finds active T2 (environment-tier) projects past the idle threshold. Publishes `idle_warning` WebSocket event first, then invokes `hibernate.py`. |
| `activity_tracker.py` | DB-backed last-activity recorder. Writes per-project `last_activity_at` when routers, agents, or WebSockets emit signals. Used by `idle_monitor` to decide who to hibernate. |
| `checkpoint_manager.py` | Point-in-time project checkpoints (beyond VolumeSnapshots). Snapshots DB state (containers, env vars) for rollback. |
| `namespace_reaper.py` | Cleans up `proj-*` namespaces stuck in `Terminating`. Root cause: PVC unmount hang when btrfs-CSI gRPC drops, creating a deadlock between `kubernetes.io/pvc-protection` finalizer and the volume plugin. Reaper force-removes the finalizer after a bounded wait. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| `routers/projects.py` (`/start`, `/hibernate`) | `compute_manager`, `hibernate`, `activity_tracker` |
| ARQ cron jobs | `idle_monitor` (every `compute_reaper_interval_seconds`), `namespace_reaper` |
| WebSocket router (`routers/chat.py`) | `activity_tracker` |
| `routers/snapshots.py` | `checkpoint_manager` |

## Related

- [orchestration.md](./orchestration.md): pod/container spec creation.
- [volume-manager.md](./volume-manager.md): Hub sync and cache placement used during hibernate.
- [snapshot-manager.md](./snapshot-manager.md): VolumeSnapshot-based persistence and timeline.
- [pubsub.md](./pubsub.md): `idle_warning` broadcast channel.
