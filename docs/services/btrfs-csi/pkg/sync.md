# pkg/sync

Per-node sync daemon. Tracks tracked volumes, produces incremental btrfs send streams, uploads them to CAS, and drains on preStop.

## Files

| File | Purpose |
|------|---------|
| `interfaces.go` | `btrfsOps` abstraction used by the daemon so tests can stub out `Send` / `Receive` / `Snapshot`. |
| `daemon.go` | `Daemon` with `Track`, `Untrack`, `SyncVolume`, `DrainAll`. Runs a ticker that walks tracked volumes. |

## Sync tick

For every tracked volume:

1. Create a local snapshot `snapshots/vol-{id}-{ts}`.
2. Parent = the previous snapshot (or nothing for a first sync).
3. `btrfs send -p {parent} {new snapshot}` into a pipe.
4. Tee through SHA256 + zstd into a CAS staging key.
5. Promote to `blobs/sha256:{hash}.zst` (or dedup).
6. Append the new layer to `manifests/{volume_id}.json`.
7. Delete older local snapshots; keep the latest so the next tick can send an incremental.

## Drain

`DrainAll()` is called during graceful shutdown:

1. Iterate every tracked volume and do a final sync.
2. Write sentinel `/run/csi/drain-complete` when complete.

The preStop hook in `deploy/manifests/node.yaml` polls for this sentinel for up to 580s. `terminationGracePeriodSeconds` is `600`.

## Dirty tracking

Each volume has an in-memory dirty flag toggled on `TrackVolume` and cleared after a successful sync. The integration test `dirty_tracking_integration_test.go` exercises this against a live btrfs pool.

## Interaction with Hub

The daemon holds leases granted by the Hub (`pkg/lease`). After a peer transfer, the source node drops the lease and stops syncing; the target node picks it up and becomes the new owner.
