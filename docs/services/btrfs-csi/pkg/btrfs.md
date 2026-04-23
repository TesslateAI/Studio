# pkg/btrfs

Thin wrappers over the `btrfs` userspace tool, raw kernel ioctls, and send-stream parsing. This is the only package that shells out to `btrfs`.

## Files

| File | Purpose |
|------|---------|
| `btrfs.go` | Subvolume CRUD (`CreateSubvolume`, `DeleteSubvolume`, `SnapshotSubvolume`), send / receive pipelines, qgroup management, receive UUID extraction. |
| `rewrite.go` | Parses btrfs send stream headers and commands to rewrite parent UUIDs; needed for cross-node incremental receive. |
| `statfs_linux.go` | Linux `syscall.Statfs` shim used by `GetSubvolumeSize`. |
| `statfs_other.go` | Stub for non-Linux builds so the package compiles on dev machines. |

## Key operations

| Go function | Underlying command or syscall |
|-------------|-------------------------------|
| `CreateSubvolume` | `btrfs subvolume create` |
| `DeleteSubvolume` | `btrfs subvolume delete` |
| `SnapshotSubvolume` | `btrfs subvolume snapshot` (writable or `-r` read-only) |
| `Send` / `SendIncremental` | `btrfs send [-p parent]` piped to writer |
| `Receive` | `btrfs receive` reading from pipe |
| `SetQgroupLimit` | `btrfs qgroup limit` |
| `GetQgroupUsage` | `btrfs qgroup show` |
| `GetSubvolumeSize` | `statfs` over the pool |
| `ExtractReceiveUUID` | Parses the stream prelude to learn the UUID assigned on the remote side. |

## Send-stream rewrite

`rewrite.go` walks the btrfs send stream (17-byte magic, 10-byte command headers, CRC32C). It can patch parent UUIDs so a stream produced against parent `A` can be replayed against a local equivalent of `A` that was received under a different UUID. This is what lets peer-transfer and CAS restore work across nodes.

## Testing

`btrfs_test.go` and `rewrite_test.go` cover the send-stream parser with golden fixtures and exercise quota parsing edge cases.
