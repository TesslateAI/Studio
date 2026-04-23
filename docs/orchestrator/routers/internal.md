# Internal Router

**File**: `orchestrator/app/routers/internal.py`

**Base path**: `/api/internal`

## Purpose

Cluster-internal endpoints invoked by in-cluster components (Volume Hub, CSI driver, cron jobs). Not exposed through ingress for public use; callers authenticate with a shared secret via `verify_internal_secret`.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/known-volume-ids` | internal secret | Return the set of volume IDs the orchestrator currently tracks (used by the volume-hub reaper to find orphaned btrfs subvolumes). |
| POST | `/volume-events` | internal secret | Ingest async volume lifecycle events (cached, sync complete, deleted) emitted by the hub. |

## Auth

`verify_internal_secret` compares the `X-Internal-Secret` header against `settings.internal_api_secret`. These endpoints must not be reachable from outside the cluster.

## Related

- Volume hub client: [../../../orchestrator/app/services/hub_client.py](../../../orchestrator/app/services/hub_client.py).
- Volume manager: [../../../orchestrator/app/services/volume_manager.py](../../../orchestrator/app/services/volume_manager.py).
- btrfs CSI + hub: `services/btrfs-csi/`.
