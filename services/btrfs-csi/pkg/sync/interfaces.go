package sync

import (
	"context"
	"io"
	"sync"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/lease"
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

// HubOps abstracts the Hub RPCs used by the sync Daemon for manifest writes
// and volume lease coordination. All manifest/tombstone mutations go through
// the Hub (single-writer model) to eliminate S3 write races between multiple
// CSI nodes. Volume leases provide cross-node coordination for all lifecycle
// operations (sync, restore, delete, migrate).
type HubOps interface {
	// Manifest operations
	AppendSnapshot(ctx context.Context, volumeID string, snap cas.Snapshot) (newHead string, err error)
	SetManifestHead(ctx context.Context, volumeID, targetHash, saveBranchName string) (newHead string, branchSaved bool, err error)
	DeleteVolumeManifest(ctx context.Context, volumeID string) error
	DeleteTombstone(ctx context.Context, volumeID string) error

	// Volume lease operations
	AcquireVolumeLease(ctx context.Context, volumeID, holder string, ttl time.Duration) (acquired bool, currentHolder string, err error)
	ReleaseVolumeLease(ctx context.Context, volumeID, holder string) error
	RenewVolumeLease(ctx context.Context, volumeID, holder string, ttl time.Duration) (renewed bool, revoked bool, err error)
	BatchAcquireLease(ctx context.Context, requests []lease.BatchReq) ([]lease.BatchResult, error)
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
// Includes an in-process lease map for local coordination.
type localHubOps struct {
	store *cas.Store

	leaseMu sync.Mutex
	leases  map[string]*localLease // volumeID → lease
}

type localLease struct {
	holder    string
	expiresAt time.Time
	revoked   bool
}

// NewLocalHubOps creates a HubOps that writes manifests directly to CAS.
func NewLocalHubOps(store *cas.Store) HubOps {
	return &localHubOps{
		store:  store,
		leases: make(map[string]*localLease),
	}
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

// --- Lease methods for local (all-in-one) mode ---

func (l *localHubOps) AcquireVolumeLease(_ context.Context, volumeID, holder string, ttl time.Duration) (bool, string, error) {
	l.leaseMu.Lock()
	defer l.leaseMu.Unlock()

	now := time.Now()
	if existing, ok := l.leases[volumeID]; ok && now.Before(existing.expiresAt) && !existing.revoked {
		return false, existing.holder, nil
	}

	l.leases[volumeID] = &localLease{
		holder:    holder,
		expiresAt: now.Add(ttl),
	}
	return true, "", nil
}

func (l *localHubOps) ReleaseVolumeLease(_ context.Context, volumeID, holder string) error {
	l.leaseMu.Lock()
	defer l.leaseMu.Unlock()

	if existing, ok := l.leases[volumeID]; ok && existing.holder == holder {
		delete(l.leases, volumeID)
	}
	return nil
}

func (l *localHubOps) RenewVolumeLease(_ context.Context, volumeID, holder string, ttl time.Duration) (bool, bool, error) {
	l.leaseMu.Lock()
	defer l.leaseMu.Unlock()

	existing, ok := l.leases[volumeID]
	if !ok || existing.holder != holder {
		return false, false, nil
	}
	if existing.revoked {
		return false, true, nil
	}
	existing.expiresAt = time.Now().Add(ttl)
	return true, false, nil
}

func (l *localHubOps) BatchAcquireLease(_ context.Context, requests []lease.BatchReq) ([]lease.BatchResult, error) {
	l.leaseMu.Lock()
	defer l.leaseMu.Unlock()

	now := time.Now()
	results := make([]lease.BatchResult, len(requests))
	for i, req := range requests {
		results[i].VolumeID = req.VolumeID
		if existing, ok := l.leases[req.VolumeID]; ok && now.Before(existing.expiresAt) && !existing.revoked {
			results[i].CurrentHolder = existing.holder
			continue
		}
		l.leases[req.VolumeID] = &localLease{
			holder:    req.Holder,
			expiresAt: now.Add(req.TTL),
		}
		results[i].Acquired = true
	}
	return results, nil
}
