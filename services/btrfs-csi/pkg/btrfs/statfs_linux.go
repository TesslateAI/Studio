package btrfs

import "syscall"

// syscallStatfs is the platform statfs struct used by GetSubvolumeSize.
type syscallStatfs = syscall.Statfs_t

// statfs calls the platform statfs syscall.
func statfs(path string, buf *syscallStatfs) error {
	return syscall.Statfs(path, buf)
}
