package template

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/google/uuid"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/ioutil"
)

// Manager downloads golden templates from the CAS store and prepares them as
// local btrfs subvolumes under /pool/templates/.
type Manager struct {
	btrfs    *btrfs.Manager
	cas      *cas.Store
	poolPath string

	mu        sync.Mutex            // guards tmplLocks
	tmplLocks map[string]*sync.Mutex // per-template download locks
}

// NewManager creates a template Manager backed by the CAS store.
func NewManager(btrfs *btrfs.Manager, casStore *cas.Store, poolPath string) *Manager {
	return &Manager{
		btrfs:     btrfs,
		cas:       casStore,
		poolPath:  poolPath,
		tmplLocks: make(map[string]*sync.Mutex),
	}
}

// EnsureTemplate checks whether the template subvolume exists locally and is
// read-only. If present but writable, it is set read-only in place. If
// missing, the template is downloaded from CAS.
func (m *Manager) EnsureTemplate(ctx context.Context, name string) error {
	tmplPath := fmt.Sprintf("templates/%s", name)

	// Fast path: already present — ensure read-only.
	if m.btrfs.SubvolumeExists(ctx, tmplPath) {
		if err := m.btrfs.EnsureReadOnly(ctx, tmplPath); err != nil {
			return fmt.Errorf("ensure template %q read-only: %w", name, err)
		}
		klog.V(4).Infof("Template %s ready (ensured ro)", name)
		return nil
	}

	// Acquire per-template lock to prevent concurrent downloads.
	m.mu.Lock()
	lk, ok := m.tmplLocks[name]
	if !ok {
		lk = &sync.Mutex{}
		m.tmplLocks[name] = lk
	}
	m.mu.Unlock()

	lk.Lock()
	defer lk.Unlock()

	// Re-check after acquiring lock.
	if m.btrfs.SubvolumeExists(ctx, tmplPath) {
		if err := m.btrfs.EnsureReadOnly(ctx, tmplPath); err != nil {
			return fmt.Errorf("ensure template %q read-only: %w", name, err)
		}
		klog.V(4).Infof("Template %s ready after lock (ensured ro)", name)
		return nil
	}

	klog.V(2).Infof("Template %s not found locally, downloading from CAS", name)
	return m.downloadTemplate(ctx, name)
}

// EnsureTemplateByHash ensures a template exists locally and is read-only.
// If present but writable, it is set read-only in place. If missing,
// downloaded from CAS by hash.
func (m *Manager) EnsureTemplateByHash(ctx context.Context, name, expectedHash string) error {
	if name == "" {
		return fmt.Errorf("template name required for EnsureTemplateByHash")
	}

	tmplPath := fmt.Sprintf("templates/%s", name)

	// Fast path: already present — ensure read-only.
	if m.btrfs.SubvolumeExists(ctx, tmplPath) {
		if err := m.btrfs.EnsureReadOnly(ctx, tmplPath); err != nil {
			return fmt.Errorf("ensure template %q read-only: %w", name, err)
		}
		klog.V(4).Infof("Template %s ready (ensured ro, expected hash %s)", name, cas.ShortHash(expectedHash))
		return nil
	}

	// Download by hash.
	m.mu.Lock()
	lk, ok := m.tmplLocks[name]
	if !ok {
		lk = &sync.Mutex{}
		m.tmplLocks[name] = lk
	}
	m.mu.Unlock()

	lk.Lock()
	defer lk.Unlock()

	// Re-check after acquiring lock.
	if m.btrfs.SubvolumeExists(ctx, tmplPath) {
		if err := m.btrfs.EnsureReadOnly(ctx, tmplPath); err != nil {
			return fmt.Errorf("ensure template %q read-only: %w", name, err)
		}
		return nil
	}

	klog.V(2).Infof("Downloading template %s by hash %s from CAS", name, cas.ShortHash(expectedHash))
	return m.downloadTemplateByHash(ctx, name, expectedHash)
}

// UploadTemplate sends the named template directly to the CAS store and
// records the name→hash mapping in the template index. Returns the blob hash.
// The template is sent directly (not via an intermediate snapshot) so that
// the UUID in the send stream matches the UUID used as -p parent in layer
// sends — enabling cross-node incremental restore.
func (m *Manager) UploadTemplate(ctx context.Context, name string) (string, error) {
	if m.cas == nil {
		return "", fmt.Errorf("CAS store not configured, cannot upload template %q", name)
	}
	tmplPath := fmt.Sprintf("templates/%s", name)

	if !m.btrfs.SubvolumeExists(ctx, tmplPath) {
		return "", fmt.Errorf("template %q does not exist", name)
	}

	// Send the template directly. Templates are already read-only (created
	// by PromoteToTemplate or btrfs receive), so no snapshot is needed.
	sendReader, err := m.btrfs.Send(ctx, tmplPath, "")
	if err != nil {
		return "", fmt.Errorf("btrfs send template: %w", err)
	}

	stallCtx, stallCancel := context.WithCancelCause(ctx)
	stallR := ioutil.NewStallReader(sendReader, stallCtx, stallCancel, ioutil.StallTimeout)

	hash, err := m.cas.PutBlob(stallCtx, stallR)
	stallR.Close()
	if err != nil {
		if cause := context.Cause(stallCtx); cause != nil {
			err = fmt.Errorf("%w (cause: %v)", err, cause)
		}
		return "", fmt.Errorf("put template blob: %w", err)
	}

	// Update template index.
	if err := m.cas.SetTemplateHash(ctx, name, hash); err != nil {
		return "", fmt.Errorf("set template hash: %w", err)
	}

	klog.Infof("Uploaded template %s as blob %s", name, cas.ShortHash(hash))
	return hash, nil
}

// ListTemplates returns the names of all template subvolumes currently
// available in the pool.
func (m *Manager) ListTemplates(ctx context.Context) ([]string, error) {
	subs, err := m.btrfs.ListSubvolumes(ctx, "templates/")
	if err != nil {
		return nil, fmt.Errorf("list template subvolumes: %w", err)
	}

	names := make([]string, 0, len(subs))
	for _, sub := range subs {
		name := strings.TrimPrefix(sub.Path, "templates/")
		if name != "" && !strings.Contains(name, "/") {
			names = append(names, name)
		}
	}
	return names, nil
}

// RefreshTemplate forces a re-download of the named template from the CAS
// store, replacing the existing local subvolume.
func (m *Manager) RefreshTemplate(ctx context.Context, name string) error {
	tmplPath := fmt.Sprintf("templates/%s", name)

	if m.btrfs.SubvolumeExists(ctx, tmplPath) {
		if err := m.btrfs.DeleteSubvolume(ctx, tmplPath); err != nil {
			return fmt.Errorf("delete existing template %q: %w", name, err)
		}
		klog.V(2).Infof("Deleted existing template %s for refresh", name)
	}

	return m.downloadTemplate(ctx, name)
}

// downloadTemplate fetches a template from the CAS store by name. Looks up the
// hash from the template index, then downloads and receives the blob.
func (m *Manager) downloadTemplate(ctx context.Context, name string) error {
	if m.cas == nil {
		return fmt.Errorf("CAS store not configured, cannot download template %s", name)
	}

	hash, err := m.cas.GetTemplateHash(ctx, name)
	if err != nil {
		return fmt.Errorf("get template hash for %s: %w", name, err)
	}

	return m.downloadTemplateByHash(ctx, name, hash)
}

// downloadTemplateByHash fetches a template blob by hash and receives it into
// the templates directory.
//
// btrfs receive writes the subvolume under the name embedded in the send
// stream — which is the *source* subvolume's name, not our requested
// template name (e.g. "bundle:<hash>"). We work around this by receiving
// into a unique staging directory then renaming the single received
// subvolume into its final location.
func (m *Manager) downloadTemplateByHash(ctx context.Context, name, hash string) error {
	reader, err := m.cas.GetBlob(ctx, hash)
	if err != nil {
		return fmt.Errorf("download template %s blob %s: %w", name, cas.ShortHash(hash), err)
	}

	// Staging dir: templates/.recv/<uuid>. On the same btrfs FS as the
	// final templates/ subvolume so os.Rename works atomically.
	stagingRel := filepath.Join("templates", ".recv", uuid.NewString())
	stagingAbs := filepath.Join(m.poolPath, stagingRel)
	if err := os.MkdirAll(stagingAbs, 0o755); err != nil {
		return fmt.Errorf("mkdir staging %q: %w", stagingRel, err)
	}
	// Always clean up the (now-empty) staging dir on exit.
	defer os.RemoveAll(stagingAbs)

	stallCtx, stallCancel := context.WithCancelCause(ctx)
	stallR := ioutil.NewStallReader(reader, stallCtx, stallCancel, ioutil.StallTimeout)

	if err := m.btrfs.Receive(stallCtx, stagingRel, stallR); err != nil {
		stallR.Close()
		if cause := context.Cause(stallCtx); cause != nil {
			err = fmt.Errorf("%w (cause: %v)", err, cause)
		}
		return fmt.Errorf("btrfs receive template %q: %w", name, err)
	}
	stallR.Close()

	// Discover the single received subvolume inside staging. We expect
	// exactly one; 0 or >1 is a protocol error.
	entries, readErr := os.ReadDir(stagingAbs)
	if readErr != nil {
		return fmt.Errorf("read staging %q after receive: %w", stagingRel, readErr)
	}
	var received string
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		candidate := filepath.Join(stagingRel, e.Name())
		if m.btrfs.SubvolumeExists(ctx, candidate) {
			if received != "" {
				// Multiple subvolumes; cleanup all and error out.
				for _, ee := range entries {
					if ee.IsDir() {
						_ = m.btrfs.DeleteSubvolume(ctx, filepath.Join(stagingRel, ee.Name()))
					}
				}
				return fmt.Errorf(
					"btrfs receive %q produced multiple subvolumes under %q",
					name, stagingRel,
				)
			}
			received = e.Name()
		}
	}
	if received == "" {
		return fmt.Errorf("btrfs receive %q produced no subvolume under %q", name, stagingRel)
	}

	receivedRel := filepath.Join(stagingRel, received)
	targetRel := filepath.Join("templates", name)

	// If a stale target somehow exists, bail out after cleaning up staging.
	if m.btrfs.SubvolumeExists(ctx, targetRel) {
		_ = m.btrfs.DeleteSubvolume(ctx, receivedRel)
		return fmt.Errorf("template %q already exists at %q", name, targetRel)
	}

	// Rename via the btrfs Manager (os.Rename first, snapshot+delete fallback).
	if renameErr := m.btrfs.RenameSubvolume(ctx, receivedRel, targetRel); renameErr != nil {
		_ = m.btrfs.DeleteSubvolume(ctx, receivedRel)
		return fmt.Errorf("rename received subvolume %q → %q: %w", receivedRel, targetRel, renameErr)
	}

	// Templates must be read-only.
	if err := m.btrfs.EnsureReadOnly(ctx, targetRel); err != nil {
		klog.Warningf("EnsureReadOnly on template %q after restore failed: %v", name, err)
	}

	klog.Infof("Downloaded and received template %s (hash=%s) from CAS (staged in %s as %q)",
		name, cas.ShortHash(hash), stagingRel, received)
	return nil
}
