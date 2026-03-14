// Package nodeops defines the internal gRPC service for controller-to-node
// delegation of btrfs operations. The CSI controller (Deployment) cannot
// perform btrfs operations directly — it delegates to the node plugin
// (DaemonSet) on the target node via this service.
package nodeops

import (
	"context"
)

// NodeOps defines the operations that the controller delegates to nodes.
type NodeOps interface {
	// CreateSubvolume creates a btrfs subvolume at the given path.
	CreateSubvolume(ctx context.Context, name string) error

	// DeleteSubvolume deletes the btrfs subvolume at the given path.
	DeleteSubvolume(ctx context.Context, name string) error

	// SnapshotSubvolume creates a snapshot of source at dest.
	SnapshotSubvolume(ctx context.Context, source, dest string, readOnly bool) error

	// SubvolumeExists returns true if the subvolume exists.
	SubvolumeExists(ctx context.Context, name string) (bool, error)

	// GetCapacity returns total and available bytes on the pool.
	GetCapacity(ctx context.Context) (total, available int64, err error)

	// ListSubvolumes lists subvolumes matching the prefix.
	ListSubvolumes(ctx context.Context, prefix string) ([]SubvolumeInfo, error)

	// TrackVolume registers a volume for periodic S3 sync.
	TrackVolume(ctx context.Context, volumeID string) error

	// UntrackVolume removes a volume from sync tracking.
	UntrackVolume(ctx context.Context, volumeID string) error

	// EnsureTemplate ensures a template subvolume exists locally.
	EnsureTemplate(ctx context.Context, name string) error

	// RestoreVolume restores a volume from object storage (S3) to the local
	// node. Used for cross-node migration when a volume is needed on a
	// different node than where it was last active. Returns an error if no
	// backup exists in S3.
	RestoreVolume(ctx context.Context, volumeID string) error
}

// SubvolumeInfo mirrors btrfs.SubvolumeInfo for the nodeops API boundary.
type SubvolumeInfo struct {
	ID       int    `json:"id"`
	Name     string `json:"name"`
	Path     string `json:"path"`
	ReadOnly bool   `json:"read_only"`
}
