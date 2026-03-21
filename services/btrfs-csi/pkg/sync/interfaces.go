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
	GetQgroupUsage(ctx context.Context, name string) (exclusive int64, limit int64, err error)
}

// casOps abstracts the CAS store operations used by the sync Daemon.
type casOps interface {
	PutBlob(ctx context.Context, r io.Reader) (string, error)
	GetBlob(ctx context.Context, hash string) (io.ReadCloser, error)
	GetManifest(ctx context.Context, volumeID string) (*cas.Manifest, error)
	PutManifest(ctx context.Context, m *cas.Manifest) error
	DeleteManifest(ctx context.Context, volumeID string) error
}

// templateOps abstracts the template manager operations used by the sync Daemon.
type templateOps interface {
	UploadTemplate(ctx context.Context, name string) (string, error)
	EnsureTemplateByHash(ctx context.Context, name, expectedHash string) error
}
