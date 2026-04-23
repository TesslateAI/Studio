# pkg/cas

Content-addressable layer store. Every btrfs send stream is a blob identified by its SHA256; volumes, templates, snapshots, and bundles are recipes over those blobs.

## Files

| File | Purpose |
|------|---------|
| `store.go` | Blob upload / download pipeline. Tees reader through SHA256 hasher and zstd encoder into a staging key, then server-side copies into `blobs/sha256:{hash}.zst`. Dedups automatically. |
| `manifest.go` | `Manifest` struct: `{volume_id, base, template_name, layers[]}`. `LatestHash()`, `TruncateAfter(hash)`, `AppendLayer(layer)`. Persisted at `manifests/{volume_id}.json`. |
| `templates.go` | `templateIndex` at `index/templates.json`. Maps template name to blob hash. |
| `bundle_manifest.go` | Self-contained restore recipe for published app bundles. Unlike a volume manifest (long-lived, mutating), bundle manifests are immutable. |

## S3 layout

```
bucket/
  blobs/
    sha256:{hash}.zst
    _staging/{random}.zst     (temporary, cleaned up after copy)
  manifests/
    vol-{id}.json
  index/
    templates.json
```

## Upload pipeline (constant memory)

1. Caller provides `io.Reader` of a btrfs send stream.
2. `store.UploadBlob` tees through `sha256.New()` and a `zstd.Encoder` into a staging key in S3.
3. Once the reader drains, the hash is known.
4. If `blobs/sha256:{hash}.zst` already exists, delete the staging key and return (zero-cost dedup).
5. Otherwise, issue a server-side copy from staging to the content-addressed key.

## Manifest chain

Each volume manifest is a flat DAG of layers:

```
base (template blob hash)
  └─ layer 0 (type=sync, parent=base)
     └─ layer 1 (type=sync, parent=layer 0)
        └─ layer 2 (type=snapshot, label="before refactor", parent=layer 1)
           └─ layer 3 (type=sync, parent=layer 2)
```

`RestoreToSnapshot(hash)` truncates the chain after the target; `CreateSnapshot(label)` appends a labeled layer.

## Bundle manifest

Bundle manifests describe a templated app install: a base blob + optional incremental layers, packaged once at publish time. The VolumeHub references them by content hash; see `pkg/volumehub/bundle.go`.
