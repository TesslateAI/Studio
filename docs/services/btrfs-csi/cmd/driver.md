# cmd/driver

Entry point for the `btrfs-csi-driver` binary: `services/btrfs-csi/cmd/driver/main.go`.

## Responsibilities

1. Set `GOMEMLIMIT` from the container cgroup limit (v1 and v2). Replaces what `GOMEMLIMIT=auto` does on Go 1.24+ but works on every version and does not require env var config in manifests. Leaves 10% headroom for stacks, mmap, etc.
2. Parse CLI flags (see table below).
3. Route startup into `mode=node`, `mode=hub`, or `mode=all` via `pkg/driver`.
4. Install signal handlers for graceful shutdown and trigger sync drain before exit.

## Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--endpoint` | `/run/csi/socket` | CSI unix socket path. |
| `--node-id` | hostname | Advertised CSI node id. |
| `--pool-path` | `/mnt/tesslate-pool` | Mount point of the node btrfs pool. |
| `--driver-name` | `btrfs.csi.tesslate.io` | CSI driver name used by StorageClass provisioner. |
| `--mode` | `all` | One of `node`, `hub`, `all`. |
| `--nodeops-port` | `9741` | NodeOps gRPC listen port. |
| `--fileops-port` | `9742` | FileOps gRPC listen port. |
| `--drain-port` | `9743` | Drain HTTP listen port. |
| `--hub-grpc-port` | `9750` | VolumeHub gRPC listen port (hub / all only). |
| `--storage-provider` | none | `s3`, `gcs`, `azureblob` (selects objstore backend). |
| `--storage-bucket` | none | Object storage bucket. |
| `--sync-interval` | `60s` | Sync daemon tick. |
| `--orchestrator-url` | none | Backend URL for GC known-volumes API. |
| `--default-quota` | none | Default per-volume btrfs qgroup limit (`5Gi`, etc). |

## Cgroup memory detection

Reads `/sys/fs/cgroup/memory.max` (v2), falling back to `/sys/fs/cgroup/memory/memory.limit_in_bytes` (v1). If a real limit is found, sets `debug.SetMemoryLimit(limit * 0.9)` so Go's GC becomes aggressive before the OOM killer fires.

## Shutdown

On SIGTERM / SIGINT the driver:

1. Cancels the root context.
2. Calls `syncer.DrainAll()` through the Drain HTTP endpoint (preStop hook path).
3. Closes gRPC servers and waits for in-flight RPCs.
