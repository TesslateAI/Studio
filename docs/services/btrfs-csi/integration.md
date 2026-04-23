# btrfs-csi integration tests

End-to-end Go tests under `services/btrfs-csi/integration/`. They require a real btrfs pool, a MinIO or S3 endpoint, and either a live Hub or the in-process equivalents. Run via `go test ./integration/...` in the minikube test harness.

## Tests

| File | Coverage |
|------|----------|
| `btrfs_integration_test.go` | Raw btrfs ops: create, snapshot, send / receive, qgroup limits, delete. |
| `bundle_roundtrip_test.go` | Publish bundle -> upload CAS layers -> materialise on a new node -> verify file equality. |
| `dirty_tracking_integration_test.go` | Sync daemon dirty flag toggles correctly under concurrent writes. |
| `drain_parallel_test.go` | `DrainAll()` syncs many volumes concurrently within the preStop budget. |
| `e2e_lifecycle_test.go` | Full lifecycle: CreateVolume -> mount -> write files -> EnsureCached on second node -> peer transfer -> DeleteVolume. |
| `fileops_integration_test.go` | FileOps RPCs end-to-end through the gRPC server. |
| `gc_integration_test.go` | GC skips known volumes, deletes orphans past grace period, honors dry-run. |
| `helpers_test.go` | Shared test fixtures (pool setup, MinIO client, gRPC dials). |
| `hub_resolve_integration_test.go` | NodeResolver correctly tracks Endpoints changes; liveness filter rejects dead nodes. |
| `load_test.go` | Concurrent CreateVolume / EnsureCached storm; checks no drift between Hub registry and node state. |
| `metrics_integration_test.go` | Every documented Prometheus metric is registered and emits expected labels. |
| `nodeops_integration_test.go` | NodeOps server mTLS + RPC surface. |
| `objstore_integration_test.go` | rclone and native S3 backends satisfy the `ObjectStorage` interface identically. |
| `s3_native_integration_test.go` | Native minio-go client against MinIO. |
| `sync_integration_test.go` | Sync daemon incremental chain; restore reproduces the original bytes exactly. |
| `template_integration_test.go` | EnsureTemplate / UploadTemplate / RefreshTemplate; bundle-template path. |

## Support manifests

| File | Purpose |
|------|---------|
| `integration/minikube/kustomization.yaml` | Kustomize that spins up the driver + MinIO on minikube for CI. |
| `integration/minikube/patches/config-patch.yaml` | Overrides storage provider + bucket to the in-cluster MinIO. |
