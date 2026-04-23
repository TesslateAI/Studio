# Volume Manager Service

The `VolumeManager` is a thin client for the Volume Hub : a storageless orchestrator that coordinates compute nodes for volume lifecycle, cache placement, and S3 sync. The orchestrator never manages volumes directly; all intelligence lives in the Hub.

## Overview

**Files covered**:

| File | Purpose |
|------|---------|
| `volume_manager.py` | `VolumeManager` async API plus `get_volume_manager()` singleton. |
| `hub_client.py` | `HubClient` gRPC transport (JSON codec over gRPC). Talks to the Volume Hub at port 9750. |
| `fileops_client.py` | Python gRPC client for the btrfs CSI driver's FileOps service. JSON codec (not protobuf). Used for read/write/delete/stat inside user volumes without spawning exec pods. |
| `nodeops_client.py` | Python gRPC client for the btrfs CSI driver's NodeOps service. Used for per-node operations (cache placement, peer transfer, local snapshot). |
| `node_discovery.py` | Resolves per-node gRPC addresses for FileOps and NodeOps by listing btrfs CSI DaemonSet pods. Uses the synchronous kubernetes client. |

**Purpose**: Provide a simple async API for volume lifecycle operations (create, delete, cache, sync, service subvolumes) without any local state machine, node selection logic, or S3 interaction.

## Key Features

| Feature | Description |
|---------|-------------|
| **Thin client** | No local state : all intelligence (node selection, S3 sync, cache placement) is in the Hub |
| **Singleton** | Single global instance via `get_volume_manager()` |
| **Template cloning** | Create volumes from named templates (e.g. `"nextjs"`) or empty |
| **Cache orchestration** | Ensure volumes are cached on live, schedulable compute nodes |
| **S3 sync** | Trigger non-blocking S3 sync on the volume's owner node |
| **Service subvolumes** | Ephemeral per-service storage (e.g. Postgres data dir), not tracked for S3 sync |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     VolumeManager                            │
│                  (Thin Client Layer)                          │
├─────────────────────────────────────────────────────────────┤
│  create_volume(template, hint_node)  → (volume_id, node)    │
│  create_empty_volume(hint_node)      → (volume_id, node)    │
│  delete_volume(volume_id)            → None                  │
│  ensure_cached(volume_id, cands)     → node_name             │
│  trigger_sync(volume_id)             → None                  │
│  create_service_volume(base, svc)    → service_volume_id     │
├─────────────────────────────────────────────────────────────┤
│                       HubClient                              │
│              (gRPC + JSON wire format)                       │
│            Port 9750: VolumeHub service                      │
└──────────────────────┬──────────────────────────────────────┘
                       │ gRPC (application/grpc+json)
                       ▼
              ┌─────────────────┐
              │   Volume Hub    │
              │  (storageless   │
              │  orchestrator)  │
              └─────────────────┘
```

## HubClient

**File**: `orchestrator/app/services/hub_client.py`

The `HubClient` is an async gRPC client that communicates with the Volume Hub service using JSON-encoded messages over gRPC (`content-type: application/grpc+json`).

### Connection

- **Endpoint**: Configured via `volume_hub_address` setting (default: `tesslate-volume-hub.kube-system.svc:9750`)
- **Transport**: `grpc.aio.insecure_channel` (cluster-internal)
- **Max message size**: 64 MiB send and receive
- **Lazy connection**: Channel created on first RPC call

### Wire Format

Requests and responses are plain Python dicts serialized to JSON bytes. The `content-type: application/grpc+json` metadata header tells the Hub to use its registered JSON codec (same codec used by NodeOps/FileOps).

### Async Context Manager

`HubClient` supports `async with` for automatic channel cleanup:

```python
async with HubClient("tesslate-volume-hub.kube-system.svc:9750") as client:
    vol_id, node = await client.create_volume(template="nextjs")
    node = await client.ensure_cached(vol_id, candidate_nodes=["node-1"])
```

### close()

`async close()` gracefully closes the underlying gRPC channel. This is the manual alternative to using `async with` -- call it when you manage the client lifecycle yourself rather than using the context manager.

```python
client = HubClient("tesslate-volume-hub.kube-system.svc:9750")
try:
    vol_id, node = await client.create_volume(template="nextjs")
finally:
    await client.close()
```

### RPC Methods

All methods map to gRPC service methods on `/volumehub.VolumeHub/{Method}`.

| Method | gRPC RPC | Default Timeout | Returns |
|--------|----------|----------------|---------|
| `create_volume(template, hint_node, *, timeout=30.0)` | `CreateVolume` | 30s | `(volume_id, node_name)` |
| `delete_volume(volume_id, *, timeout=30.0)` | `DeleteVolume` | 30s | `None` |
| `ensure_cached(volume_id, candidate_nodes, *, timeout=120.0)` | `EnsureCached` | 120s | `node_name` |
| `trigger_sync(volume_id, *, timeout=120.0)` | `TriggerSync` | 120s | `None` |
| `volume_status(volume_id, *, timeout=30.0)` | `VolumeStatus` | 30s | `dict` |
| `create_service_volume(base_volume_id, service_name, *, timeout=30.0)` | `CreateServiceVolume` | 30s | `volume_id` |

### Error Handling

RPC failures propagate as `grpc.aio.AioRpcError` exceptions. The `VolumeManager` does not catch these : callers are responsible for handling failures (with the exception of `hibernate.py`, which catches and logs warnings for sync failures).

### volume_status Response

```python
{
    "volume_id": "vol-a1b2c3d4",
    "owner_node": "compute-node-1",
    "cached_nodes": ["compute-node-1", "compute-node-3"],
    "last_sync": "2026-03-21T12:00:00Z"  # ISO timestamp or None
}
```

## VolumeManager

**File**: `orchestrator/app/services/volume_manager.py`

Thin wrapper around `HubClient` that adds structured logging. Accessed via the `get_volume_manager()` singleton.

### create_volume()

Create a volume on a node from a template (or empty).

```python
async def create_volume(
    self, template: str | None = None, hint_node: str | None = None
) -> tuple[str, str]:
```

**Parameters**:
- `template` : Template name to clone from (e.g. `"nextjs"`). Pass `None` for an empty volume.
- `hint_node` : Preferred node for volume placement. If `None`, the Hub picks the best available node.

**Returns**: `(volume_id, node_name)` : the volume ID and the node where it was created.

### create_empty_volume()

Convenience wrapper for `create_volume(template=None)`.

```python
async def create_empty_volume(self, hint_node: str | None = None) -> tuple[str, str]:
```

**Parameters**:
- `hint_node` : Preferred node for volume placement.

**Returns**: `(volume_id, node_name)`.

### delete_volume()

Delete a volume from the Hub, S3, and all node caches. Idempotent.

```python
async def delete_volume(self, volume_id: str) -> None:
```

**Parameters**:
- `volume_id` : Volume to delete.

### ensure_cached()

Ensure a volume is cached on a live, schedulable compute node.

```python
async def ensure_cached(
    self, volume_id: str, candidate_nodes: list[str] | None = None
) -> str:
```

**Parameters**:
- `volume_id` : Volume to cache.
- `candidate_nodes` : K8s nodes the caller considers schedulable. The Hub intersects this with its own live node set and picks the best one. Pass `None` to let the Hub choose from all live nodes.

**Returns**: The node name where the volume is now cached.

**Behavior**: If the volume is already cached on a live candidate, returns immediately (fast path). Otherwise the Hub peer-transfers or restores from CAS onto the best candidate. Never returns a dead node.

### trigger_sync()

Trigger S3 sync on the node that owns the volume.

```python
async def trigger_sync(self, volume_id: str) -> None:
```

**Parameters**:
- `volume_id` : Volume whose data to sync.

**Behavior**: The Hub looks up the owner node and tells it to sync. Non-blocking from the caller's perspective.

### create_service_volume()

Create a service-specific subvolume on the Hub.

```python
async def create_service_volume(
    self, base_volume_id: str, service_name: str
) -> str:
```

**Parameters**:
- `base_volume_id` : Parent project volume ID.
- `service_name` : Service identifier (e.g. `"postgres"`).

**Returns**: The service volume ID (e.g. `"vol-a1b2c3d4-postgres"`).

**Behavior**: Service volumes hold ephemeral service data (e.g. Postgres data dir). They are tied to a base project volume and are not tracked for S3 sync.

### Singleton Accessor

```python
from app.services.volume_manager import get_volume_manager

vm = get_volume_manager()  # Creates instance on first call, returns same instance thereafter
```

## Usage Patterns

### Project Creation : Template Snapshot

```python
# In services/project_setup/source_acquisition.py
from ...services.volume_manager import get_volume_manager

vm = get_volume_manager()
volume_id, node_name = await vm.create_volume(template=spec.template_slug)
```

### Project Creation : Empty Volume (File Placement)

```python
# In services/project_setup/file_placement.py
from ...services.volume_manager import get_volume_manager

vm = get_volume_manager()
volume_id, node_name = await vm.create_empty_volume()
```

### Project Start : Ensure Cached on Schedulable Node

```python
# In services/compute_manager.py
from .volume_manager import get_volume_manager

vm = get_volume_manager()
candidate_nodes = await self._get_schedulable_nodes()
if not candidate_nodes:
    raise RuntimeError("No schedulable compute nodes available")
node_name = await vm.ensure_cached(volume_id, candidate_nodes=candidate_nodes)

# Update project if node changed
if node_name != project.cache_node:
    project.cache_node = node_name
    await db.commit()
```

### Service Container : Create Service Subvolume

```python
# In services/compute_manager.py
from .volume_manager import get_volume_manager

vm = get_volume_manager()
svc_volume_id = await vm.create_service_volume(volume_id, svc_dir)
# e.g. "vol-a1b2c3d4-postgres"
```

### Hibernation : Trigger S3 Sync

```python
# In services/hibernate.py
from .volume_manager import get_volume_manager

if project.volume_id:
    try:
        vm = get_volume_manager()
        await vm.trigger_sync(project.volume_id)
    except Exception:
        logger.warning(
            "[HIBERNATE] Sync trigger failed : Hub will catch up on next access"
        )
```

### FileOps Fallback : Re-cache on Node Failure

```python
# In services/orchestration/kubernetes_orchestrator.py
from ..volume_manager import get_volume_manager

vm = get_volume_manager()
new_node = await vm.ensure_cached(volume_id)
# Reconnect FileOps client to the new node
```

## Configuration

Setting in `config.py`:

```python
volume_hub_address: str = "tesslate-volume-hub.kube-system.svc:9750"
```

| Setting | Default | Description |
|---------|---------|-------------|
| `volume_hub_address` | `tesslate-volume-hub.kube-system.svc:9750` | Hub gRPC endpoint (storageless orchestrator) |

## Related Files

- `orchestrator/app/services/volume_manager.py` : VolumeManager thin client
- `orchestrator/app/services/hub_client.py` : HubClient gRPC transport
- `orchestrator/app/services/compute_manager.py` : Primary consumer (project start, service volumes)
- `orchestrator/app/services/hibernate.py` : Triggers S3 sync on hibernation
- `orchestrator/app/services/project_setup/source_acquisition.py` : Creates volumes from templates
- `orchestrator/app/services/project_setup/file_placement.py` : Creates empty volumes for file writes
- `orchestrator/app/services/orchestration/kubernetes_orchestrator.py` : Re-caches volumes on node failure
- `orchestrator/app/config.py` : `volume_hub_address` setting
- `orchestrator/tests/services/test_volume_manager.py` : Unit tests

## Related Docs

- [snapshot-manager.md](./snapshot-manager.md) : EBS VolumeSnapshot operations (separate from Volume Hub)
- [orchestration.md](./orchestration.md) : Docker/K8s container orchestration
- [CLAUDE.md](./CLAUDE.md) : Services layer overview
