# pkg/ioutil

One helper: the stall detector.

## File

`stall.go`: `StallReader` and `StallWriter`. Each wraps an `io.Reader` / `io.Writer` and fails with `ErrStalled` if zero bytes flow for longer than `StallTimeout` (default 30s).

## Why

Both sides of a btrfs send / receive pipeline can hang quietly: network partitions, a node running out of disk, or a remote receiver that deadlocked. A 30-second zero-progress window is conservative: even a slow S3 link makes partial progress more often than that. Real stalls trigger a clean cancel up the call stack instead of a hung goroutine.

## Usage

Wrap the reader and writer on both ends of `SendVolumeTo`, `btrfs receive` pipes, and CAS blob uploads. The sync daemon and Hub both import this package.
