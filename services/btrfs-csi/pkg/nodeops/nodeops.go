// Package nodeops defines the internal gRPC service for controller-to-node
// delegation of btrfs operations. The CSI controller (Deployment) cannot
// perform btrfs operations directly — it delegates to the node plugin
// (DaemonSet) on the target node via this service.
package nodeops

import (
	"context"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
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

	// TrackVolume registers a volume for periodic CAS sync with template context.
	TrackVolume(ctx context.Context, volumeID, templateName, templateHash string) error

	// UntrackVolume removes a volume from sync tracking.
	UntrackVolume(ctx context.Context, volumeID string) error

	// EnsureTemplate ensures a template subvolume exists locally.
	EnsureTemplate(ctx context.Context, name string) error

	// RestoreVolume restores a volume from the CAS store by replaying its
	// manifest layer chain. Used for cross-node migration.
	RestoreVolume(ctx context.Context, volumeID string) error

	// PromoteToTemplate snapshots a volume as a read-only template, uploads
	// to CAS, and records the name→hash mapping. The source volume is deleted.
	PromoteToTemplate(ctx context.Context, volumeID, templateName string) error

	// SetOwnership recursively chowns a subvolume to the given uid:gid.
	SetOwnership(ctx context.Context, name string, uid, gid int) error

	// SyncVolume triggers an immediate CAS sync for a single volume.
	SyncVolume(ctx context.Context, volumeID string) error

	// DeleteVolumeCAS deletes the CAS manifest and local layer snapshots.
	// Blob cleanup happens via GC.
	DeleteVolumeCAS(ctx context.Context, volumeID string) error

	// GetSyncState returns the sync tracking state of all volumes on this node.
	GetSyncState(ctx context.Context) ([]TrackedVolumeState, error)

	// SendVolumeTo sends a volume to a target node via btrfs send | zstd stream.
	// targetAddr is the target node's NodeOps gRPC address (host:port).
	SendVolumeTo(ctx context.Context, volumeID, targetAddr string) error

	// SendTemplateTo sends a template to a target node via btrfs send | zstd stream.
	SendTemplateTo(ctx context.Context, templateName, targetAddr string) error

	// HasBlobs checks which blob hashes exist as local snapshots/templates.
	HasBlobs(ctx context.Context, hashes []string) ([]bool, error)

	// CreateUserSnapshot creates a labeled snapshot layer for a volume.
	// Returns the blob hash that identifies the snapshot.
	CreateUserSnapshot(ctx context.Context, volumeID, label string) (string, error)

	// RestoreFromSnapshot restores a volume to a specific snapshot hash.
	RestoreFromSnapshot(ctx context.Context, volumeID, targetHash string) error

	// GetVolumeMetadata returns CAS metadata for a volume (manifest info).
	GetVolumeMetadata(ctx context.Context, volumeID string) (*VolumeMetadata, error)
}

// SubvolumeInfo mirrors btrfs.SubvolumeInfo for the nodeops API boundary.
type SubvolumeInfo struct {
	ID       int    `json:"id"`
	Name     string `json:"name"`
	Path     string `json:"path"`
	ReadOnly bool   `json:"read_only"`
}

// TrackedVolumeState reports the sync daemon state for a tracked volume.
type TrackedVolumeState struct {
	VolumeID     string `json:"volume_id"`
	TemplateHash string `json:"template_hash,omitempty"`
	LastSyncAt   string `json:"last_sync_at,omitempty"` // ISO 8601 or empty
}

// VolumeMetadata holds CAS metadata for a volume, derived from its manifest.
type VolumeMetadata struct {
	VolumeID     string      `json:"volume_id"`
	TemplateName string      `json:"template_name,omitempty"`
	TemplateHash string      `json:"template_hash,omitempty"`
	LatestHash   string      `json:"latest_hash,omitempty"`
	LayerCount   int         `json:"layer_count"`
	Snapshots    []cas.Layer `json:"snapshots,omitempty"` // layers with type="snapshot"
}
