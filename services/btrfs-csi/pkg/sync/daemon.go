package sync

import (
	"context"
	"fmt"
	"io"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/klauspost/compress/zstd"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/metrics"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/objstore"
)

// countingWriter wraps an io.Writer and tracks the number of bytes written.
type countingWriter struct {
	w     io.Writer
	bytes int64
}

func (cw *countingWriter) Write(p []byte) (int, error) {
	n, err := cw.w.Write(p)
	cw.bytes += int64(n)
	return n, err
}

// trackedVolume holds per-volume sync state.
type trackedVolume struct {
	volumeID   string
	lastSnapID string // previous sync snapshot name for incremental sends
	lastSyncAt time.Time
}

// Daemon periodically snapshots tracked volumes and uploads them to object storage.
type Daemon struct {
	btrfs    *btrfs.Manager
	store    objstore.ObjectStorage
	interval time.Duration
	mu       sync.Mutex
	tracked  map[string]*trackedVolume // volumeID -> tracking state
	stopCh   chan struct{}
	wg       sync.WaitGroup
}

// NewDaemon creates a sync Daemon that uses the given btrfs manager, object
// storage backend, and sync interval.
func NewDaemon(btrfs *btrfs.Manager, store objstore.ObjectStorage, interval time.Duration) *Daemon {
	return &Daemon{
		btrfs:    btrfs,
		store:    store,
		interval: interval,
		tracked:  make(map[string]*trackedVolume),
		stopCh:   make(chan struct{}),
	}
}

// Start begins the periodic sync loop. It blocks until Stop is called or the
// provided context is cancelled.
func (d *Daemon) Start(ctx context.Context) {
	klog.Info("Sync daemon starting")
	d.wg.Add(1)
	defer d.wg.Done()

	ticker := time.NewTicker(d.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			klog.Info("Sync daemon context cancelled, stopping")
			return
		case <-d.stopCh:
			klog.Info("Sync daemon stop signal received")
			return
		case <-ticker.C:
			if err := d.syncAll(ctx); err != nil {
				klog.Errorf("Sync cycle error: %v", err)
			}
		}
	}
}

// Stop signals the daemon to stop and waits for the sync loop to finish.
func (d *Daemon) Stop() {
	select {
	case <-d.stopCh:
		// Already closed.
	default:
		close(d.stopCh)
	}
	d.wg.Wait()
	klog.Info("Sync daemon stopped")
}

// TrackVolume registers a volume for periodic S3 sync.
func (d *Daemon) TrackVolume(volumeID string) {
	d.mu.Lock()
	defer d.mu.Unlock()

	if _, exists := d.tracked[volumeID]; exists {
		return
	}
	d.tracked[volumeID] = &trackedVolume{volumeID: volumeID}
	klog.V(2).Infof("Tracking volume %s for sync", volumeID)
}

// UntrackVolume removes a volume from sync tracking and deletes its sync
// snapshot if one exists.
func (d *Daemon) UntrackVolume(volumeID string) {
	d.mu.Lock()
	tv, exists := d.tracked[volumeID]
	if !exists {
		d.mu.Unlock()
		return
	}
	lastSnap := tv.lastSnapID
	delete(d.tracked, volumeID)
	d.mu.Unlock()

	// Clean up the last sync snapshot if it exists.
	if lastSnap != "" {
		snapPath := fmt.Sprintf("snapshots/%s", lastSnap)
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if d.btrfs.SubvolumeExists(ctx, snapPath) {
			if err := d.btrfs.DeleteSubvolume(ctx, snapPath); err != nil {
				klog.Warningf("Failed to cleanup sync snapshot %s: %v", lastSnap, err)
			}
		}
	}
	klog.V(2).Infof("Untracked volume %s from sync", volumeID)
}

// SyncVolume performs an immediate sync of a single volume to S3.
func (d *Daemon) SyncVolume(ctx context.Context, volumeID string) error {
	d.mu.Lock()
	tv, exists := d.tracked[volumeID]
	if !exists {
		d.mu.Unlock()
		return fmt.Errorf("volume %q is not tracked for sync", volumeID)
	}
	// Copy state under lock to avoid holding it during I/O.
	lastSnapID := tv.lastSnapID
	d.mu.Unlock()

	newSnapID, err := d.syncOne(ctx, volumeID, lastSnapID)
	if err != nil {
		return err
	}

	d.mu.Lock()
	if tv, ok := d.tracked[volumeID]; ok {
		tv.lastSnapID = newSnapID
		tv.lastSyncAt = time.Now()
	}
	d.mu.Unlock()
	return nil
}

// syncAll iterates over all tracked volumes and syncs each one.
func (d *Daemon) syncAll(ctx context.Context) error {
	d.mu.Lock()
	// Snapshot the list of tracked volumes to avoid holding the lock during I/O.
	type syncItem struct {
		volumeID   string
		lastSnapID string
	}
	items := make([]syncItem, 0, len(d.tracked))
	for _, tv := range d.tracked {
		items = append(items, syncItem{volumeID: tv.volumeID, lastSnapID: tv.lastSnapID})
	}
	d.mu.Unlock()

	if len(items) == 0 {
		klog.V(5).Info("No volumes to sync")
		return nil
	}

	klog.V(4).Infof("Starting sync cycle for %d volumes", len(items))
	var firstErr error
	for _, item := range items {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		newSnapID, err := d.syncOne(ctx, item.volumeID, item.lastSnapID)
		if err != nil {
			klog.Errorf("Sync failed for volume %s: %v", item.volumeID, err)
			metrics.SyncFailures.Inc()
			if firstErr == nil {
				firstErr = err
			}
			continue
		}

		d.mu.Lock()
		if tv, ok := d.tracked[item.volumeID]; ok {
			tv.lastSnapID = newSnapID
			tv.lastSyncAt = time.Now()
		}
		d.mu.Unlock()
		metrics.SyncLag.WithLabelValues(item.volumeID).Set(0)
	}

	return firstErr
}

// syncOne performs the sync algorithm for a single volume:
//  1. Create a read-only snapshot of volumes/{id} at snapshots/{id}@sync-new
//  2. btrfs send (incremental if lastSnapID exists) | zstd | upload to object storage
//  3. Delete the previous sync snapshot
//  4. Return the new snapshot name
func (d *Daemon) syncOne(ctx context.Context, volumeID, lastSnapID string) (string, error) {
	start := time.Now()

	volumePath := fmt.Sprintf("volumes/%s", volumeID)
	newSnapName := fmt.Sprintf("%s@sync-new", volumeID)
	newSnapPath := fmt.Sprintf("snapshots/%s", newSnapName)

	// Verify the volume exists.
	if !d.btrfs.SubvolumeExists(ctx, volumePath) {
		return "", fmt.Errorf("volume subvolume %q does not exist", volumePath)
	}

	// If a stale sync-new snapshot exists (from a previous failed run), remove it.
	// If removal fails, fall back to a unique name so the sync can proceed.
	if d.btrfs.SubvolumeExists(ctx, newSnapPath) {
		if err := d.btrfs.DeleteSubvolume(ctx, newSnapPath); err != nil {
			klog.Warningf("stale sync snapshot %q undeletable, using unique suffix: %v", newSnapPath, err)
			newSnapName = fmt.Sprintf("%s@sync-%d", volumeID, time.Now().UnixNano())
			newSnapPath = fmt.Sprintf("snapshots/%s", newSnapName)
		}
	}

	// 1. Create a read-only snapshot.
	if err := d.btrfs.SnapshotSubvolume(ctx, volumePath, newSnapPath, true); err != nil {
		return "", fmt.Errorf("create sync snapshot: %w", err)
	}

	// 2. Send (incremental or full) and upload to object storage.
	var parentPath string
	var objKey string
	ts := time.Now().UTC().Format("20060102T150405Z")

	if lastSnapID != "" {
		parentSnapPath := fmt.Sprintf("snapshots/%s", lastSnapID)
		if d.btrfs.SubvolumeExists(ctx, parentSnapPath) {
			parentPath = parentSnapPath
			objKey = fmt.Sprintf("volumes/%s/incremental-%s.zst", volumeID, ts)
		} else {
			// Parent disappeared; fall back to full send.
			klog.Warningf("Previous sync snapshot %s missing, falling back to full send for %s", lastSnapID, volumeID)
			objKey = fmt.Sprintf("volumes/%s/full-%s.zst", volumeID, ts)
		}
	} else {
		objKey = fmt.Sprintf("volumes/%s/full-%s.zst", volumeID, ts)
	}

	sendReader, err := d.btrfs.Send(ctx, newSnapPath, parentPath)
	if err != nil {
		// Clean up the snapshot we just created.
		_ = d.btrfs.DeleteSubvolume(ctx, newSnapPath)
		return "", fmt.Errorf("btrfs send: %w", err)
	}

	// Pipe through zstd compression before uploading.
	pr, pw := io.Pipe()
	cw := &countingWriter{w: pw}
	compressErrCh := make(chan error, 1)
	go func() {
		defer sendReader.Close()

		encoder, encErr := zstd.NewWriter(cw)
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

	// Upload the compressed stream. Size is unknown (-1) since we are streaming.
	if uploadErr := d.store.Upload(ctx, objKey, pr, -1); uploadErr != nil {
		_ = pr.Close()
		_ = d.btrfs.DeleteSubvolume(ctx, newSnapPath)
		return "", fmt.Errorf("upload to object storage key %q: %w", objKey, uploadErr)
	}
	_ = pr.Close()

	if compressErr := <-compressErrCh; compressErr != nil {
		_ = d.btrfs.DeleteSubvolume(ctx, newSnapPath)
		return "", fmt.Errorf("zstd compression: %w", compressErr)
	}

	metrics.SyncDuration.Observe(time.Since(start).Seconds())
	metrics.SyncBytesTransferred.Add(float64(cw.bytes))
	klog.V(2).Infof("Synced volume %s to %s", volumeID, objKey)

	// 3. Delete the previous sync snapshot if it exists.
	if lastSnapID != "" {
		oldSnapPath := fmt.Sprintf("snapshots/%s", lastSnapID)
		if d.btrfs.SubvolumeExists(ctx, oldSnapPath) {
			if delErr := d.btrfs.DeleteSubvolume(ctx, oldSnapPath); delErr != nil {
				klog.Warningf("Failed to delete previous sync snapshot %s: %v", lastSnapID, delErr)
			}
		}
	}

	// 4. Return the new snapshot name.
	return newSnapName, nil
}

// ListObjects lists all object keys matching the given prefix.
func (d *Daemon) ListObjects(ctx context.Context, prefix string) ([]string, error) {
	if d.store == nil {
		return nil, fmt.Errorf("object storage not configured")
	}

	objects, err := d.store.List(ctx, prefix)
	if err != nil {
		return nil, err
	}

	keys := make([]string, 0, len(objects))
	for _, obj := range objects {
		keys = append(keys, obj.Key)
	}
	return keys, nil
}

// RestoreFromStorage downloads a compressed btrfs send stream from object
// storage and receives it into the volumes directory to reconstruct a
// subvolume. Used for cross-node migration when a volume is needed on a
// different node. If objKey is empty, the latest full send is found
// automatically.
func (d *Daemon) RestoreFromStorage(ctx context.Context, volumeID, objKey string) error {
	if d.store == nil {
		return fmt.Errorf("object storage not configured")
	}

	// Auto-discover latest full send if no key specified.
	if objKey == "" {
		keys, err := d.ListObjects(ctx, fmt.Sprintf("volumes/%s/", volumeID))
		if err != nil {
			return fmt.Errorf("list storage objects: %w", err)
		}
		if len(keys) == 0 {
			return fmt.Errorf("no snapshots in object storage for volume %q", volumeID)
		}
		// Prefer the latest full send; fall back to latest object.
		objKey = keys[len(keys)-1]
		for i := len(keys) - 1; i >= 0; i-- {
			if strings.HasPrefix(filepath.Base(keys[i]), "full-") {
				objKey = keys[i]
				break
			}
		}
	}

	klog.Infof("Restoring volume %q from storage: %s", volumeID, objKey)

	reader, err := d.store.Download(ctx, objKey)
	if err != nil {
		return fmt.Errorf("download %q: %w", objKey, err)
	}
	defer reader.Close()

	// Decompress the zstd stream.
	decoder, decErr := zstd.NewReader(reader)
	if decErr != nil {
		return fmt.Errorf("zstd decoder: %w", decErr)
	}
	defer decoder.Close()

	// Receive into the volumes directory.
	if err := d.btrfs.Receive(ctx, "volumes", decoder); err != nil {
		return fmt.Errorf("btrfs receive volume %q: %w", volumeID, err)
	}

	// btrfs receive creates the subvolume with the snapshot basename from the
	// send stream (e.g. "{volID}@sync-new"). Rename to the canonical path that
	// NodePublishVolume expects.
	receivedPath := fmt.Sprintf("volumes/%s@sync-new", volumeID)
	canonicalPath := fmt.Sprintf("volumes/%s", volumeID)

	if d.btrfs.SubvolumeExists(ctx, receivedPath) {
		// Remove any stale subvolume at the target path.
		if d.btrfs.SubvolumeExists(ctx, canonicalPath) {
			if err := d.btrfs.DeleteSubvolume(ctx, canonicalPath); err != nil {
				return fmt.Errorf("delete stale volume %q before rename: %w", canonicalPath, err)
			}
		}
		// Create a writable snapshot (btrfs receive creates read-only snapshots).
		if err := d.btrfs.SnapshotSubvolume(ctx, receivedPath, canonicalPath, false); err != nil {
			return fmt.Errorf("snapshot %q -> %q: %w", receivedPath, canonicalPath, err)
		}
		// Delete the intermediate read-only snapshot.
		if err := d.btrfs.DeleteSubvolume(ctx, receivedPath); err != nil {
			klog.Warningf("Failed to clean up intermediate snapshot %q: %v", receivedPath, err)
		}
	}

	klog.Infof("Volume %q restored from storage successfully", volumeID)
	return nil
}
