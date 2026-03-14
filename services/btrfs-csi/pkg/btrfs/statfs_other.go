//go:build !linux

package btrfs

import "fmt"

// syscallStatfs is a stub for non-Linux platforms. The btrfs CSI driver only
// runs on Linux, but this allows the package to compile elsewhere for
// development and testing.
type syscallStatfs struct {
	Bsize  int64
	Blocks uint64
	Bfree  uint64
}

// statfs is a no-op stub on non-Linux platforms.
func statfs(path string, buf *syscallStatfs) error {
	return fmt.Errorf("statfs not supported on this platform")
}
