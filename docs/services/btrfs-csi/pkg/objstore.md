# pkg/objstore

Provider-agnostic object storage. Two implementations behind one interface.

## Files

| File | Purpose |
|------|---------|
| `objstore.go` | `ObjectStorage` interface and `ObjectInfo` struct. Covers `Upload`, `Download`, `Delete`, `Exists`, `List`, `Copy`, `EnsureBucket`. |
| `s3.go` | Native implementation via `minio-go`. Used by default for `--storage-provider=s3`. Supports AWS S3, MinIO, DO Spaces. |
| `rclone.go` | Subprocess implementation that shells out to `rclone`. Used for `gcs` and `azureblob`, plus S3 when rclone features are needed. Provider config is passed via `RCLONE_*` env vars and a generated config file. |

## Provider selection

`--storage-provider` chooses the implementation at boot. `s3` picks the native client; `gcs` and `azureblob` pick rclone. When using rclone, remote paths use the `:provider:bucket/key` syntax so no persistent config file is required.

## Server-side copy

Both implementations implement `Copy(src, dst)` using server-side copy primitives (S3 `CopyObject`, rclone `copyto`). The CAS pipeline relies on this for the staging-to-content-addressed promotion step (zero bandwidth).

## Tests

`rclone_test.go` and `s3_test.go` exercise both paths with MinIO fixtures spun up via the test harness.
