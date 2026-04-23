# btrfs-csi

OpenSail's storage stack. Ships the btrfs CSI driver, the Volume Hub gRPC orchestrator, and per-node FileOps / NodeOps / Drain servers from a single Go binary.

See also: `docs/architecture/storage-architecture.md` for the end-to-end narrative.

## Binary layout

| Binary | File | Modes |
|--------|------|-------|
| `btrfs-csi-driver` | `cmd/driver/main.go` | `node`, `hub`, `all` |
| `btrfs-csi-migrate` | `cmd/migrate/main.go` | one-shot migration from legacy sync format |

## Driver modes

| Mode | Workload | Services started | Use case |
|------|----------|------------------|----------|
| `node` | DaemonSet | CSI Identity + Node, NodeOps :9741, FileOps :9742, Drain :9743, Sync daemon, GC | Production multi-node |
| `hub` | Deployment | CSI Identity + Controller, Hub gRPC :9750 | Production control plane |
| `all` | Single pod | Everything | Minikube / single-node dev |

## Package map

| Package | Doc |
|---------|-----|
| `pkg/btrfs` | [pkg/btrfs.md](pkg/btrfs.md) |
| `pkg/cas` | [pkg/cas.md](pkg/cas.md) |
| `pkg/driver` | [pkg/driver.md](pkg/driver.md) |
| `pkg/fileops` | [pkg/fileops.md](pkg/fileops.md) |
| `pkg/gc` | [pkg/gc.md](pkg/gc.md) |
| `pkg/ioutil` | [pkg/ioutil.md](pkg/ioutil.md) |
| `pkg/lease` | [pkg/lease.md](pkg/lease.md) |
| `pkg/metrics` | [pkg/metrics.md](pkg/metrics.md) |
| `pkg/nodeops` | [pkg/nodeops.md](pkg/nodeops.md) |
| `pkg/objstore` | [pkg/objstore.md](pkg/objstore.md) |
| `pkg/sync` | [pkg/sync.md](pkg/sync.md) |
| `pkg/template` | [pkg/template.md](pkg/template.md) |
| `pkg/volumehub` | [pkg/volumehub.md](pkg/volumehub.md) |

Entrypoints: [cmd/driver.md](cmd/driver.md), [cmd/migrate.md](cmd/migrate.md).

Deploy manifests: [deploy/README.md](deploy/README.md). Integration tests: [integration.md](integration.md).

## gRPC surfaces

| Service | Port | Served by | Consumed by |
|---------|------|-----------|-------------|
| CSI Identity / Controller | unix socket | Hub (or all) | `csi-provisioner`, `csi-snapshotter` sidecars |
| CSI Identity / Node | unix socket | Node DaemonSet | kubelet via `csi-node-driver-registrar` |
| Volume Hub | TCP :9750 (JSON codec) | Hub Deployment | Python orchestrator (`hub_client.py`) |
| NodeOps | TCP :9741 (mTLS-optional) | Node DaemonSet | Hub and CSI Controller |
| FileOps | TCP :9742 (mTLS-optional) | Node DaemonSet | Python orchestrator (FileOpsClient) |
| Drain HTTP | TCP :9743 | Node DaemonSet | preStop hook |

## Object storage

The CAS layer stores zstd-compressed btrfs send streams addressed by SHA256. Implemented by `pkg/objstore`:

| Implementation | File | Backends |
|----------------|------|----------|
| Native minio-go client | `pkg/objstore/s3.go` | S3 (AWS, MinIO, DO Spaces) |
| rclone subprocess | `pkg/objstore/rclone.go` | S3, GCS, Azure Blob |

## Metrics

Prometheus registry exposed on `:9080/metrics`. Histograms for volume create / sync / restore durations, counters for GC actions, gauges for cached-volume counts. See [pkg/metrics.md](pkg/metrics.md).
