# btrfs-csi + Volume Hub Agent Context

## Purpose

`services/btrfs-csi/` is the Go implementation of OpenSail's storage stack. It ships three things from a single binary:

1. **btrfs CSI driver** (Identity + Controller + Node) registered as `btrfs.csi.tesslate.io`.
2. **Volume Hub**: a storageless gRPC orchestrator that routes every volume operation to the right node.
3. **NodeOps / FileOps / Drain** per-node gRPC + HTTP services that execute btrfs send/receive, CoW cloning, file IO, and S3 sync.

Load this context for anything touching volumes, templates, snapshots, CAS, sync, GC, or node scheduling.

## Source tree

| Path | Purpose |
|------|---------|
| `cmd/driver/main.go` | Driver entrypoint. Parses flags, reads cgroup memory limit, dispatches to `mode=node`, `hub`, or `all`. |
| `cmd/migrate/main.go` | One-shot migrator that upgrades legacy template-based sync to the incremental CAS manifest chain. |
| `pkg/btrfs/` | btrfs system calls (subvolume, send, receive, quota, statfs) and rewrite helpers for send streams. |
| `pkg/cas/` | Content-addressable storage: blob store, volume manifests, bundle manifests, template index. |
| `pkg/driver/` | CSI Identity / Controller / Node servers; quota parsing; driver mode routing. |
| `pkg/fileops/` | Port 9742 FileOps gRPC: read, write, list, mkdir, delete, tar batch IO on a volume root. |
| `pkg/gc/` | Garbage collector for orphaned subvolumes and stale CAS blobs. |
| `pkg/ioutil/` | Stall detector for long-running streaming IO. |
| `pkg/lease/` | Shared lease types used by sync daemon and Hub to avoid import cycles. |
| `pkg/metrics/` | Prometheus metrics for CSI, sync, hub, GC, and fileops. |
| `pkg/nodeops/` | Port 9741 NodeOps gRPC. Controller / Hub delegates here to mutate btrfs on a specific node. |
| `pkg/objstore/` | Object-storage abstraction (S3 native via minio-go, rclone multi-provider). |
| `pkg/sync/` | Per-node sync daemon: tracks volumes, drives incremental btrfs send to CAS, drains on preStop. |
| `pkg/template/` | Template manager: ensure, upload, promote, refresh, bundle-chain materialisation. |
| `pkg/volumehub/` | Hub package: server, registry, resolver, eviction, resource watcher, client, bundle helpers. |
| `deploy/` | Kustomize base: CSI driver registration, node DaemonSet, storage/snapshot classes, secret template, PDB, NetworkPolicy, image pre-cache. |
| `overlays/minikube/` | Minikube overlay with service accounts, CSI credentials, and local-pool patch. |
| `integration/` | End-to-end tests (btrfs, bundle roundtrip, dirty-tracking, drain, fileops, GC, hub resolve, load, metrics, nodeops, objstore, s3 native, sync, template, lifecycle). |

## Related contexts

| Context | When to load |
|---------|--------------|
| `docs/architecture/storage-architecture.md` | Full narrative of the three-layer storage stack. |
| `docs/infrastructure/kubernetes/CLAUDE.md` | Where the DaemonSet and Hub Deployment live in the platform. |
| `docs/orchestrator/services/CLAUDE.md` | Python client side (`volume_manager.py`, `hub_client.py`). |
| `docs/services/tsinit/CLAUDE.md` | Sibling Go service: per-user-container supervisor. |

## Quick reference

- Driver name: `btrfs.csi.tesslate.io`.
- Ports: `9741` NodeOps, `9742` FileOps, `9743` Drain HTTP, `9750` Hub gRPC, `9080` metrics.
- Pool path: `/mnt/tesslate-pool` (btrfs, layout: `volumes/`, `templates/`, `snapshots/`, `layers/`).
- Modes: `node` (DaemonSet), `hub` (Deployment, no `SYS_ADMIN`, no btrfs), `all` (single-pod minikube).
- Hub is storageless: registry is rebuilt from node queries on restart.
- CAS layout: `blobs/sha256:*.zst`, `manifests/{volume_id}.json`, `index/templates.json`.
- gRPC codec: JSON (`content-type: application/grpc+json`) between Python client and Hub.

## When to load this context

Load before editing any `.go` file under `services/btrfs-csi/`, any manifest under `deploy/` or `overlays/`, or any integration test. Load `docs/architecture/storage-architecture.md` alongside for the conceptual picture.
