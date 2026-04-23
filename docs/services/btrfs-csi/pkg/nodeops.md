# pkg/nodeops

Internal gRPC service for controller-to-node delegation. The CSI Controller runs in the Hub Deployment and has no btrfs. Every mutating operation therefore hops to a specific node via NodeOps on port `:9741`.

## Files

| File | Purpose |
|------|---------|
| `nodeops.go` | `NodeOps` interface definition (reference table below). |
| `server.go` | gRPC server. Reads + writes btrfs pool, CAS, templates. Optional mTLS (`NODEOPS_TLS_*`). |
| `client.go` | gRPC client, used by the Hub and the Controller. |

## RPC surface

| RPC | Purpose |
|-----|---------|
| `CreateSubvolume(name)` | `btrfs subvolume create`. |
| `DeleteSubvolume(name)` | `btrfs subvolume delete`. |
| `SnapshotSubvolume(source, dest, readOnly)` | CoW clone. |
| `SubvolumeExists(name)` | Existence check. |
| `GetCapacity()` | Pool total / available bytes. |
| `ListSubvolumes(prefix)` | Prefix list. |
| `TrackVolume(id, template, hash)` / `UntrackVolume(id)` | Register / remove for sync daemon. |
| `EnsureTemplate(name)` / `EnsureTemplateByHash(name, hash)` | Ensure template is present locally. |
| `RestoreVolume(id)` | Replay CAS manifest layers on this node. |
| `PromoteToTemplate(source, name)` | Promote a volume to a template and upload to CAS. |
| `SyncVolume(id)` | Immediate incremental sync for one volume. |
| `DeleteVolumeCAS(id)` | Remove manifest and layer snapshots. |
| `SetOwnership(path, uid, gid)` | Recursive chown. |
| `SendVolumeTo(id, targetNode)` | Peer-transfer via btrfs send / receive. |
| `SendTemplateTo(name, targetNode)` | Peer-transfer a template. |
| `GetSyncState()` | Returns tracked volumes with last sync + dirty flags. |
| `HasBlobs(hashes[])` | Which blob hashes exist locally (for restore planning). |
| `CreateUserSnapshot(id, label)` | Labeled CAS snapshot layer. |
| `RestoreFromSnapshot(id, hash)` | Truncate manifest + replay. |
| `GetVolumeMetadata(id)` | Manifest summary: layers, snapshots, hashes. |
| `SetQgroupLimit(id, bytes)` / `GetQgroupUsage(id)` | Per-volume quotas. |

## Security

mTLS is opt-in. When enabled (`NODEOPS_TLS_CERT` + key + CA), the server verifies client certificates; the Hub presents a cert signed by the same CA. On minikube mTLS is disabled and the service is reachable only from inside the pod network via NetworkPolicy.
