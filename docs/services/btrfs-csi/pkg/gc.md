# pkg/gc

Per-node garbage collector for orphaned btrfs subvolumes and stale CAS blobs.

## File

`collector.go`: `Config` (`Interval`, `GracePeriod`, `DryRun`, `OrchestratorURL`), `Collector.Run(ctx)`.

## Algorithm

1. Tick every `Interval` (default 10 minutes).
2. Call `GET {orchestrator}/api/internal/known-volume-ids`. The orchestrator returns every `Project.volume_id` it still tracks.
3. List local subvolumes at `/mnt/tesslate-pool/volumes/`.
4. For each subvolume not in the known set and older than `GracePeriod` (default 24h), `btrfs subvolume delete`.
5. Delete orphaned snapshots under `/mnt/tesslate-pool/snapshots/`.
6. Call `cas.Store.GC()` to drop blobs and manifests no longer referenced.

## Safety

- Grace period ensures a newly created volume isn't reaped before the orchestrator registers it.
- `DryRun` logs the deletion plan but makes no changes; enabled via flag during rollouts.
- The known-volume-ids endpoint is authenticated via a shared secret header.
