# pkg/volumehub

The Volume Hub: a storageless gRPC orchestrator. Zero storage, zero btrfs. Nodes handle data; the Hub coordinates them.

## Files

| File | Purpose |
|------|---------|
| `hub.go` | Package doc, `VolumeStatus` DTO. States the invariants: Hub is a Deployment, not StatefulSet, no PVC, no `SYS_ADMIN`. |
| `server.go` | gRPC server on port `:9750`. Implements every RPC in the table below. JSON codec (`content-type: application/grpc+json`). |
| `registry.go` | `NodeRegistry` in-memory store: `volume -> owner`, `volume -> cachedNodes[]`, `template -> nodes[]`, `node -> volumes[]`, `LeastLoadedNode`, `ReconcileNodes`. |
| `discovery.go` | `NodeResolver`: watches the `tesslate-btrfs-csi-node-svc` headless Service via K8s Endpoints watch, maintains `node -> podIP`. Streaming watch, approximately 1-second latency, falls back to list-then-rewatch with exponential backoff. |
| `resources.go` | Capacity and label watcher for nodes. Provides `NodeCapacity` for placement decisions. |
| `eviction.go` | Periodic loop (5 min) that evicts stale cache entries once a grace period has elapsed after ownership transfer. |
| `client.go` | gRPC client used internally (e.g. from the CSI Controller). |
| `bundle.go` | Helpers for registering and materialising app bundles as synthetic `bundle:{hash}` templates. |

## RPC surface

| RPC | Purpose |
|-----|---------|
| `CreateVolume(template?, hint_node?)` | Generate volume ID, pick target node, ensure template, `CreateSubvolume`, register. Returns `(volume_id, node_name)`. |
| `DeleteVolume(volume_id)` | Untrack, delete on every cached node, drop manifest. Idempotent. |
| `EnsureCached(volume_id, candidate_nodes?)` | Core scheduling RPC. See liveness filtering below. |
| `TriggerSync(volume_id)` | Look up owner, delegate to `NodeOps.SyncVolume`. Non-blocking. |
| `VolumeStatus(volume_id)` | Owner, cached set, last sync, template info, layer count, snapshots. |
| `CreateServiceVolume(base_volume_id, service_name)` | Ephemeral service subvolume (e.g. postgres data dir). Not synced to S3. |
| `CreateSnapshot(volume_id, label?)` | Append labeled CAS layer. |
| `ListSnapshots(volume_id)` | Layers with `type="snapshot"`. |
| `RestoreToSnapshot(volume_id, target_hash)` | Truncate manifest + replay. |

## Liveness filtering (EnsureCached)

1. Get the live node set from the Endpoints watch.
2. Intersect caller-provided `candidate_nodes` with live nodes. Empty -> `FailedPrecondition`.
3. Compute cached-and-live nodes (proactively remove stale entries).
4. Fast path: any live cached node in the candidate set -> return it (zero data movement).
5. Peer transfer: cached on a live non-candidate -> `SendVolumeTo` streams to `pickBestCandidate()`.
6. CAS restore: no live cache -> replay manifest layers on the best candidate.

`pickBestCandidate()` chooses the least-loaded live node with deterministic lexicographic tie-break.

## Rebuild on restart

The registry is not persisted. On Hub startup `RebuildRegistry()` queries every known node for `GetSyncState` and reconstructs ownership and caches. This is why the Hub can run as a Deployment without a PVC.

## Eviction

The eviction loop drops cache entries that are older than the eviction grace period after ownership transferred elsewhere. Prevents the cached set from growing unbounded after repeated migrations.

## Bundle support

`bundle.go` registers app bundles under synthetic template names `bundle:{content-hash}`. These are materialised via the bundle manifest recipe rather than the single-blob template path. Used by the Tesslate Apps install saga.
