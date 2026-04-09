package sync

import (
	"context"
	"io"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
)

// btrfsOps abstracts the btrfs operations used by the sync Daemon.
type btrfsOps interface {
	SubvolumeExists(ctx context.Context, name string) bool
	SnapshotSubvolume(ctx context.Context, source, dest string, readOnly bool) error
	DeleteSubvolume(ctx context.Context, name string) error
	Send(ctx context.Context, snapshotPath string, parentPath string) (io.ReadCloser, error)
	RenameSubvolume(ctx context.Context, oldName, newName string) error
	ListSubvolumes(ctx context.Context, prefix string) ([]btrfs.SubvolumeInfo, error)
	Receive(ctx context.Context, destDir string, reader io.Reader) error
	GetSubvolumeIdentity(ctx context.Context, name string) (btrfs.SubvolumeIdentity, error)
	GetQgroupUsage(ctx context.Context, name string) (exclusive int64, limit int64, err error)
	GetGeneration(ctx context.Context, name string) (uint64, error)
}

// casOps abstracts the CAS store operations used by the sync Daemon.
// Only READ operations and blob writes — manifest/tombstone writes go
// through HubOps (single-writer model).
type casOps interface {
	PutBlob(ctx context.Context, r io.Reader) (string, error)
	GetBlob(ctx context.Context, hash string) (io.ReadCloser, error)
	DeleteBlob(ctx context.Context, hash string) error
	GetManifest(ctx context.Context, volumeID string) (*cas.Manifest, error)
	CleanupStaging(ctx context.Context) (int, error)
	HasTombstone(ctx context.Context, volumeID string) (bool, error)
}

// HubOps abstracts the Hub RPCs used by the sync Daemon for manifest writes.
// All manifest/tombstone mutations go through the Hub (single-writer model)
// to eliminate S3 write races between multiple CSI nodes.
type HubOps interface {
	AppendSnapshot(ctx context.Context, volumeID string, snap cas.Snapshot) (newHead string, err error)
	SetManifestHead(ctx context.Context, volumeID, targetHash, saveBranchName string) (newHead string, branchSaved bool, err error)
	DeleteVolumeManifest(ctx context.Context, volumeID string) error
	DeleteTombstone(ctx context.Context, volumeID string) error
}

// templateOps abstracts the template manager operations used by the sync Daemon.
type templateOps interface {
	UploadTemplate(ctx context.Context, name string) (string, error)
	EnsureTemplateByHash(ctx context.Context, name, expectedHash string) error
}

// ---------------------------------------------------------------------------
// LocalHubOps — direct CAS adapter for "all" mode (minikube)
// ---------------------------------------------------------------------------

// localHubOps implements HubOps by writing directly to the CAS store.
// Used in "all" mode where Hub and daemon run in the same process.
type localHubOps struct {
	store *cas.Store
}

// NewLocalHubOps creates a HubOps that writes manifests directly to CAS.
func NewLocalHubOps(store *cas.Store) HubOps {
	return &localHubOps{store: store}
}

func (l *localHubOps) AppendSnapshot(ctx context.Context, volumeID string, snap cas.Snapshot) (string, error) {
	manifest, err := l.store.GetManifest(ctx, volumeID)
	if err != nil {
		manifest = &cas.Manifest{VolumeID: volumeID, Snapshots: make(map[string]cas.Snapshot)}
	}
	manifest.AppendSnapshot(snap)
	if err := l.store.PutManifest(ctx, manifest); err != nil {
		return "", err
	}
	return manifest.Head, nil
}

func (l *localHubOps) SetManifestHead(ctx context.Context, volumeID, targetHash, saveBranchName string) (string, bool, error) {
	manifest, err := l.store.GetManifest(ctx, volumeID)
	if err != nil {
		return "", false, err
	}
	branchSaved := false
	if saveBranchName != "" && manifest.Head != "" && manifest.Head != targetHash {
		manifest.SaveBranch(saveBranchName, manifest.Head)
		branchSaved = true
	}
	manifest.SetHead(targetHash)
	if err := l.store.PutManifest(ctx, manifest); err != nil {
		return "", false, err
	}
	return manifest.Head, branchSaved, nil
}

func (l *localHubOps) DeleteVolumeManifest(ctx context.Context, volumeID string) error {
	return l.store.DeleteManifest(ctx, volumeID)
}

func (l *localHubOps) DeleteTombstone(ctx context.Context, volumeID string) error {
	return l.store.DeleteTombstone(ctx, volumeID)
}
