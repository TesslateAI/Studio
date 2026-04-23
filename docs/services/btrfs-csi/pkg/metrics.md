# pkg/metrics

Prometheus metrics for every subsystem.

## File

`metrics.go`: exposes `RegisterAll()` and the HTTP handler used by the `:9080/metrics` endpoint.

## Highlights

| Metric | Type | Scope |
|--------|------|-------|
| `tesslate_csi_volume_create_duration_seconds` | Histogram | CSI Controller |
| `tesslate_csi_volume_delete_duration_seconds` | Histogram | CSI Controller |
| `tesslate_csi_snapshot_create_duration_seconds` | Histogram | CSI Controller |
| `tesslate_sync_duration_seconds` | Histogram | Sync daemon |
| `tesslate_sync_bytes_sent_total` | Counter | Sync daemon |
| `tesslate_hub_cached_volumes` | Gauge | Hub registry |
| `tesslate_hub_node_capacity_bytes` | Gauge | Hub, per node |
| `tesslate_gc_subvolumes_deleted_total` | Counter | GC |
| `tesslate_fileops_bytes_read_total` | Counter | FileOps |
| `tesslate_fileops_bytes_written_total` | Counter | FileOps |

## Registration

The driver binary creates a dedicated `prometheus.Registry` and scopes every metric through a `tesslate_` prefix to avoid clashing with client-go's default process/go collectors.
