# pkg/driver

Implements the CSI spec servers (Identity, Controller, Node) and wires them to the Hub and NodeOps.

## Files

| File | Purpose |
|------|---------|
| `driver.go` | `Driver` struct. Reads `--mode`, opens the CSI unix socket, registers gRPC servers, launches the optional Hub, sync daemon, GC, and metrics server. |
| `identity.go` | CSI Identity service. Returns plugin name `btrfs.csi.tesslate.io`, capabilities (`CONTROLLER_SERVICE`, `VOLUME_ACCESSIBILITY_CONSTRAINTS`). |
| `controller.go` | CSI Controller. `CreateVolume` / `DeleteVolume` / `CreateSnapshot` / `DeleteSnapshot`. In Hub mode delegates to `volumehub.Server`; in `all` mode calls NodeOps directly. |
| `node.go` | CSI Node. `NodeStageVolume` / `NodePublishVolume` bind-mount the btrfs subvolume into the pod's target path. Enforces `maxVolumesPerNode = 500`. |
| `quota.go` | `ParseQuota("5Gi")` helper for translating human-readable sizes into bytes for `SetQgroupLimit`. |

## CSI flow in Hub mode

```
csi-provisioner sidecar
  ↓ CreateVolume
Controller (hub)
  ↓ volumehub.Server.CreateVolume
    pick node, NodeOps.CreateSubvolume on that node
  ↓ returns VolumeID + topology
csi-provisioner binds PVC
  ↓ kubelet NodeStageVolume / NodePublishVolume
Node (daemon) bind-mounts /mnt/tesslate-pool/volumes/{id} → pod target
```

## Topology

Controller sets `accessible_topology = {kubernetes.io/hostname: <nodeName>}` so the kube-scheduler co-locates the workload with its volume.

## Max volumes per node

`node.go` enforces `maxVolumesPerNode = 500` on `NodeGetInfo`. Past this count the scheduler will pack new volumes onto other nodes.
