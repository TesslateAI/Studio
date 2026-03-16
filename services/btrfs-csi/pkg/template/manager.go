package template

import (
	"context"
	"fmt"
	"io"
	"strings"
	"sync"
	"time"

	"github.com/klauspost/compress/zstd"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/objstore"
)

// Manager downloads golden templates from object storage and prepares them as
// local btrfs subvolumes under /pool/templates/.
type Manager struct {
	btrfs    *btrfs.Manager
	store    objstore.ObjectStorage
	poolPath string

	mu        sync.Mutex            // guards tmplLocks
	tmplLocks map[string]*sync.Mutex // per-template download locks
}

// NewManager creates a template Manager.
func NewManager(btrfs *btrfs.Manager, store objstore.ObjectStorage, poolPath string) *Manager {
	return &Manager{
		btrfs:     btrfs,
		store:     store,
		poolPath:  poolPath,
		tmplLocks: make(map[string]*sync.Mutex),
	}
}

// EnsureTemplate checks whether the template subvolume exists locally. If it
// does not, the template is downloaded from S3 and received into the pool.
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

	// Re-check after acquiring lock — another goroutine may have downloaded it.
	if m.btrfs.SubvolumeExists(ctx, tmplPath) {
		klog.V(4).Infof("Template %s already exists (after lock)", name)
		return nil
	}

	klog.V(2).Infof("Template %s not found locally, downloading from object storage", name)
	return m.downloadTemplate(ctx, name)
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
		// sub.Path is something like "templates/node-20" -- extract the name.
		name := strings.TrimPrefix(sub.Path, "templates/")
		if name != "" && !strings.Contains(name, "/") {
			names = append(names, name)
		}
	}
	return names, nil
}

// RefreshTemplate forces a re-download of the named template from S3,
// replacing the existing local subvolume.
func (m *Manager) RefreshTemplate(ctx context.Context, name string) error {
	tmplPath := fmt.Sprintf("templates/%s", name)

	// Delete existing subvolume if present.
	if m.btrfs.SubvolumeExists(ctx, tmplPath) {
		if err := m.btrfs.DeleteSubvolume(ctx, tmplPath); err != nil {
			return fmt.Errorf("delete existing template %q: %w", name, err)
		}
		klog.V(2).Infof("Deleted existing template %s for refresh", name)
	}

	return m.downloadTemplate(ctx, name)
}

// UploadTemplate snapshots the named template and uploads it to S3 as a
// compressed btrfs send stream.
func (m *Manager) UploadTemplate(ctx context.Context, name string) error {
	tmplPath := fmt.Sprintf("templates/%s", name)
	snapPath := fmt.Sprintf("snapshots/%s", name)

	if !m.btrfs.SubvolumeExists(ctx, tmplPath) {
		return fmt.Errorf("template %q does not exist", name)
	}

	// Create a read-only snapshot for the send.
	if m.btrfs.SubvolumeExists(ctx, snapPath) {
		if err := m.btrfs.DeleteSubvolume(ctx, snapPath); err != nil {
			return fmt.Errorf("delete stale upload snapshot: %w", err)
		}
	}
	if err := m.btrfs.SnapshotSubvolume(ctx, tmplPath, snapPath, true); err != nil {
		return fmt.Errorf("snapshot template for upload: %w", err)
	}

	// Ensure cleanup of the upload snapshot.
	defer func() {
		cleanCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if m.btrfs.SubvolumeExists(cleanCtx, snapPath) {
			_ = m.btrfs.DeleteSubvolume(cleanCtx, snapPath)
		}
	}()

	// Send and compress.
	sendReader, err := m.btrfs.Send(ctx, snapPath, "")
	if err != nil {
		return fmt.Errorf("btrfs send template: %w", err)
	}

	pr, pw := io.Pipe()
	compressErrCh := make(chan error, 1)
	go func() {
		defer sendReader.Close()

		encoder, encErr := zstd.NewWriter(pw)
		if encErr != nil {
			pw.CloseWithError(encErr)
			compressErrCh <- encErr
			return
		}

		_, copyErr := io.Copy(encoder, sendReader)
		closeErr := encoder.Close()
		if copyErr != nil {
			pw.CloseWithError(copyErr)
			compressErrCh <- copyErr
			return
		}
		if closeErr != nil {
			pw.CloseWithError(closeErr)
			compressErrCh <- closeErr
			return
		}
		pw.Close()
		compressErrCh <- nil
	}()

	s3Key := fmt.Sprintf("templates/%s/latest.zst", name)
	if uploadErr := m.store.Upload(ctx, s3Key, pr, -1); uploadErr != nil {
		_ = pr.Close()
		return fmt.Errorf("upload template %q: %w", name, uploadErr)
	}
	_ = pr.Close()

	if compressErr := <-compressErrCh; compressErr != nil {
		return fmt.Errorf("zstd compress template: %w", compressErr)
	}

	klog.Infof("Uploaded template %s to %s", name, s3Key)
	return nil
}

// downloadTemplate fetches a template from S3 and receives it into the pool.
// If the S3 object does not exist, a warning is logged but no error is returned
// (the template may not have been uploaded yet).
func (m *Manager) downloadTemplate(ctx context.Context, name string) error {
	if m.store == nil {
		return fmt.Errorf("object storage not configured, cannot download template %s", name)
	}

	s3Key := fmt.Sprintf("templates/%s/latest.zst", name)

	exists, err := m.store.Exists(ctx, s3Key)
	if err != nil {
		return fmt.Errorf("check object storage for template %s: %w", name, err)
	}
	if !exists {
		return fmt.Errorf("template %s not found in object storage at %s", name, s3Key)
	}

	reader, err := m.store.Download(ctx, s3Key)
	if err != nil {
		return fmt.Errorf("download template %s from object storage: %w", name, err)
	}
	defer reader.Close()

	// Decompress the zstd stream.
	decoder, err := zstd.NewReader(reader)
	if err != nil {
		return fmt.Errorf("create zstd decoder for template %s: %w", name, err)
	}
	defer decoder.Close()

	// Pipe decompressed data into btrfs receive targeting the templates directory.
	// The send stream embeds the snapshot basename (which is just "{name}"),
	// so btrfs receive creates "templates/{name}" directly.
	if err := m.btrfs.Receive(ctx, "templates", decoder); err != nil {
		return fmt.Errorf("btrfs receive template %q: %w", name, err)
	}

	klog.Infof("Downloaded and received template %s from object storage", name)
	return nil
}
