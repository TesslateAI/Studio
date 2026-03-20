package template

import (
	"context"
	"fmt"
	"strings"
	"sync"

	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
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

// EnsureTemplate checks whether the template subvolume exists locally. If it
// does not, the template is downloaded from the CAS store and received into
// the pool.
func (m *Manager) EnsureTemplate(ctx context.Context, name string) error {
	tmplPath := fmt.Sprintf("templates/%s", name)

	// Fast path: already present.
	if m.btrfs.SubvolumeExists(ctx, tmplPath) {
		klog.V(4).Infof("Template %s already exists", name)
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
		klog.V(4).Infof("Template %s already exists (after lock)", name)
		return nil
	}

	klog.V(2).Infof("Template %s not found locally, downloading from CAS", name)
	return m.downloadTemplate(ctx, name)
}

// EnsureTemplateByHash ensures a template exists locally and matches the
// expected blob hash. If the template is missing, it is downloaded from the
// CAS store. Used by sync/restore to ensure the exact version.
func (m *Manager) EnsureTemplateByHash(ctx context.Context, name, expectedHash string) error {
	if name == "" {
		return fmt.Errorf("template name required for EnsureTemplateByHash")
	}

	tmplPath := fmt.Sprintf("templates/%s", name)

	// If already present, trust it (templates are immutable read-only snapshots).
	if m.btrfs.SubvolumeExists(ctx, tmplPath) {
		klog.V(4).Infof("Template %s exists locally (expected hash %s)", name, cas.ShortHash(expectedHash))
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

	if m.btrfs.SubvolumeExists(ctx, tmplPath) {
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

	hash, err := m.cas.PutBlob(ctx, sendReader)
	_ = sendReader.Close()
	if err != nil {
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
func (m *Manager) downloadTemplateByHash(ctx context.Context, name, hash string) error {
	reader, err := m.cas.GetBlob(ctx, hash)
	if err != nil {
		return fmt.Errorf("download template %s blob %s: %w", name, cas.ShortHash(hash), err)
	}
	defer reader.Close()

	// btrfs receive creates the subvolume with the basename from the send
	// stream. For templates, the send stream name is the template name.
	if err := m.btrfs.Receive(ctx, "templates", reader); err != nil {
		return fmt.Errorf("btrfs receive template %q: %w", name, err)
	}

	klog.Infof("Downloaded and received template %s (hash=%s) from CAS", name, cas.ShortHash(hash))
	return nil
}
