# pkg/fileops

Tier-0 file access. The Python orchestrator reads and writes project files through FileOps without running a user pod.

## Files

| File | Purpose |
|------|---------|
| `fileops.go` | Interface + DTOs (`FileInfo`, `FileContent`). |
| `server.go` | gRPC server on port `:9742`. Resolves `volume_id` to `/mnt/tesslate-pool/volumes/{id}` and enforces path containment. |
| `client.go` | gRPC client; wraps a `grpc.ClientConn` and speaks the FileOps proto. |

## RPCs

| RPC | Purpose |
|-----|---------|
| `ReadFile(volume_id, path)` | Returns bytes and `FileInfo`. |
| `ReadFiles(volume_id, paths[])` | Batch read. |
| `WriteFile(volume_id, path, data, mode)` | Atomic write via temp-and-rename. |
| `DeletePath(volume_id, path, recursive)` | Unlink or `RemoveAll`. |
| `ListDir(volume_id, path)` | Single-level listing. |
| `ListTree(volume_id, path, limit)` | Recursive walk. |
| `MkdirAll(volume_id, path, mode)` | Recursive mkdir. |
| `TarExtract` / `TarCreate` | Batch move using in-memory tar archives. |

## Safety

All paths go through `filepath.Clean` + prefix check against the volume root. Requests with `..` traversal or absolute paths outside the volume root return `codes.InvalidArgument`.

## TLS

When `FILEOPS_TLS_CERT` / `FILEOPS_TLS_KEY` / `FILEOPS_TLS_CA` are set, the server loads mTLS credentials. The client (Python side uses a separate wrapper; Go-side is `client.go`) dials with matching credentials.

## Tier

Called Tier 0 because file ops work with zero pods running: the driver pod serves reads and writes straight off the btrfs subvolume.
