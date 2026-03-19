package sync

import (
	"context"
	"fmt"
	"sync"
	"time"

	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/metrics"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
)

// trackedVolume holds per-volume CAS sync state.
type trackedVolume struct {
	volumeID      string
	templateName  string // template used to create this volume
	templateHash  string // base blob hash from template
	lastLayerHash string // hash of most recent layer (parent for next send)
	lastSnapPath  string // local path of last layer snapshot (for -p parent)
	lastSyncAt    time.Time
}

// Daemon periodically snapshots tracked volumes, uploads incremental layers
// to the CAS store, and maintains volume manifests.
type Daemon struct {
	btrfs    *btrfs.Manager
	cas      *cas.Store
	tmplMgr  *template.Manager
	interval time.Duration
	mu       sync.Mutex
	tracked  map[string]*trackedVolume
	syncLocks   sync.Mutex                  // guards volLocks
	volLocks    map[string]*sync.Mutex       // per-volume sync serialization
	stopCh   chan struct{}
	wg       sync.WaitGroup
}

// NewDaemon creates a sync Daemon that uses the CAS store for all storage.
func NewDaemon(btrfs *btrfs.Manager, casStore *cas.Store, tmplMgr *template.Manager, interval time.Duration) *Daemon {
	return &Daemon{
		btrfs:     btrfs,
		cas:       casStore,
		tmplMgr:   tmplMgr,
		interval:  interval,
		tracked:   make(map[string]*trackedVolume),
		volLocks:  make(map[string]*sync.Mutex),
		stopCh:    make(chan struct{}),
	}
}

// Start begins the periodic sync loop. It blocks until Stop is called or the
// provided context is cancelled.
func (d *Daemon) Start(ctx context.Context) {
	klog.Info("Sync daemon starting (CAS mode)")
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
	default:
		close(d.stopCh)
	}
	d.wg.Wait()
	klog.Info("Sync daemon stopped")
}

// DrainAll performs a final CAS sync for all tracked volumes, then stops
// the daemon. Used during node drain to persist unsaved data before
// DaemonSet pod termination. Volumes are synced sequentially to avoid
// contending on disk I/O and S3 bandwidth.
func (d *Daemon) DrainAll(ctx context.Context) error {
	d.mu.Lock()
	type drainItem struct {
		volumeID     string
		templateName string
		templateHash string
	}
	items := make([]drainItem, 0, len(d.tracked))
	for _, tv := range d.tracked {
		items = append(items, drainItem{
			volumeID:     tv.volumeID,
			templateName: tv.templateName,
			templateHash: tv.templateHash,
		})
	}
	d.mu.Unlock()

	total := len(items)
	klog.Infof("Drain: starting final sync for %d volumes", total)

	for i, item := range items {
		select {
		case <-ctx.Done():
			klog.Warningf("Drain: context cancelled after syncing %d/%d volumes", i, total)
			return ctx.Err()
		default:
		}

		if err := d.SyncVolume(ctx, item.volumeID); err != nil {
			klog.Errorf("Drain: failed to sync volume %d/%d %s: %v", i+1, total, item.volumeID, err)
			// Continue draining remaining volumes — partial drain > no drain.
			continue
		}
		d.UntrackVolume(item.volumeID)
		klog.Infof("Drain: synced volume %d/%d: %s", i+1, total, item.volumeID)
	}

	d.Stop()
	klog.Info("Drain: complete")
	return nil
}

// TrackVolume registers a volume for periodic CAS sync with its template context.
func (d *Daemon) TrackVolume(volumeID, templateName, templateHash string) {
	d.mu.Lock()
	defer d.mu.Unlock()

	if _, exists := d.tracked[volumeID]; exists {
		return
	}
	d.tracked[volumeID] = &trackedVolume{
		volumeID:     volumeID,
		templateName: templateName,
		templateHash: templateHash,
	}
	klog.V(2).Infof("Tracking volume %s for CAS sync (template=%s, base=%s)",
		volumeID, templateName, cas.ShortHash(templateHash))
}

// UntrackVolume removes a volume from sync tracking and cleans up the last
// layer snapshot if one exists.
func (d *Daemon) UntrackVolume(volumeID string) {
	d.mu.Lock()
	tv, exists := d.tracked[volumeID]
	if !exists {
		d.mu.Unlock()
		return
	}
	lastSnapPath := tv.lastSnapPath
	delete(d.tracked, volumeID)
	d.mu.Unlock()

	if lastSnapPath != "" {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if d.btrfs.SubvolumeExists(ctx, lastSnapPath) {
			if err := d.btrfs.DeleteSubvolume(ctx, lastSnapPath); err != nil {
				klog.Warningf("Failed to cleanup layer snapshot %s: %v", lastSnapPath, err)
			}
		}
	}
	klog.V(2).Infof("Untracked volume %s from CAS sync", volumeID)
}

// TrackedVolumeState reports the sync state for a tracked volume.
type TrackedVolumeState struct {
	VolumeID     string `json:"volume_id"`
	TemplateHash string `json:"template_hash,omitempty"`
	LastSyncAt   string `json:"last_sync_at,omitempty"`
}

// GetTrackedState returns the current sync state for all tracked volumes.
// Used by the Hub to rebuild its registry on startup.
func (d *Daemon) GetTrackedState() []TrackedVolumeState {
	d.mu.Lock()
	defer d.mu.Unlock()

	states := make([]TrackedVolumeState, 0, len(d.tracked))
	for _, tv := range d.tracked {
		s := TrackedVolumeState{
			VolumeID:     tv.volumeID,
			TemplateHash: tv.templateHash,
		}
		if !tv.lastSyncAt.IsZero() {
			s.LastSyncAt = tv.lastSyncAt.UTC().Format(time.RFC3339)
		}
		states = append(states, s)
	}
	return states
}

// volumeLock returns the per-volume mutex, creating it if needed.
// This serializes sync/snapshot operations on the same volume to prevent
// manifest read-modify-write races.
func (d *Daemon) volumeLock(volumeID string) *sync.Mutex {
	d.syncLocks.Lock()
	defer d.syncLocks.Unlock()
	lk, ok := d.volLocks[volumeID]
	if !ok {
		lk = &sync.Mutex{}
		d.volLocks[volumeID] = lk
	}
	return lk
}

// SyncVolume performs an immediate sync of a single volume to CAS.
func (d *Daemon) SyncVolume(ctx context.Context, volumeID string) error {
	// Per-volume lock serializes with concurrent CreateSnapshot/RestoreToSnapshot.
	vl := d.volumeLock(volumeID)
	vl.Lock()
	defer vl.Unlock()

	d.mu.Lock()
	tv, exists := d.tracked[volumeID]
	if !exists {
		d.mu.Unlock()
		return fmt.Errorf("volume %q is not tracked for sync", volumeID)
	}
	tvCopy := *tv
	d.mu.Unlock()

	hash, newSnapPath, err := d.syncOne(ctx, &tvCopy, "sync", "")
	if err != nil {
		return err
	}

	d.mu.Lock()
	if tv, ok := d.tracked[volumeID]; ok {
		tv.lastLayerHash = hash
		tv.lastSnapPath = newSnapPath
		tv.lastSyncAt = time.Now()
	}
	d.mu.Unlock()
	return nil
}

// CreateSnapshot creates a labeled snapshot layer and returns the blob hash.
func (d *Daemon) CreateSnapshot(ctx context.Context, volumeID, label string) (string, error) {
	// Per-volume lock serializes with concurrent SyncVolume/RestoreToSnapshot.
	vl := d.volumeLock(volumeID)
	vl.Lock()
	defer vl.Unlock()

	d.mu.Lock()
	tv, exists := d.tracked[volumeID]
	if !exists {
		d.mu.Unlock()
		return "", fmt.Errorf("volume %q is not tracked for sync", volumeID)
	}
	tvCopy := *tv
	d.mu.Unlock()

	hash, newSnapPath, err := d.syncOne(ctx, &tvCopy, "snapshot", label)
	if err != nil {
		return "", err
	}

	d.mu.Lock()
	if tv, ok := d.tracked[volumeID]; ok {
		tv.lastLayerHash = hash
		tv.lastSnapPath = newSnapPath
		tv.lastSyncAt = time.Now()
	}
	d.mu.Unlock()
	return hash, nil
}

// RestoreVolume restores a volume from CAS by downloading the latest layer
// from the manifest and applying it on top of the base template. Each layer
// is a full diff from the template (not incremental from the previous layer),
// so only one layer download is needed regardless of manifest history.
func (d *Daemon) RestoreVolume(ctx context.Context, volumeID string) error {
	if d.cas == nil {
		return fmt.Errorf("CAS store not configured, cannot restore volume %q", volumeID)
	}

	// Acquire per-volume lock to serialize with concurrent SyncVolume/CreateSnapshot.
	vl := d.volumeLock(volumeID)
	vl.Lock()
	defer vl.Unlock()

	manifest, err := d.cas.GetManifest(ctx, volumeID)
	if err != nil {
		return fmt.Errorf("get manifest for %s: %w", volumeID, err)
	}

	// Ensure base template exists locally.
	if manifest.Base != "" && manifest.TemplateName != "" {
		if err := d.tmplMgr.EnsureTemplateByHash(ctx, manifest.TemplateName, manifest.Base); err != nil {
			return fmt.Errorf("ensure base template %s: %w", manifest.TemplateName, err)
		}
	}

	// Determine source for writable volume: latest layer or base template.
	var sourcePath string
	if len(manifest.Layers) > 0 {
		latest := manifest.Layers[len(manifest.Layers)-1]
		targetPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(latest.Hash))

		if !d.btrfs.SubvolumeExists(ctx, targetPath) {
			reader, err := d.cas.GetBlob(ctx, latest.Hash)
			if err != nil {
				return fmt.Errorf("download layer %s: %w", latest.Hash, err)
			}

			if err := d.btrfs.Receive(ctx, "layers", reader); err != nil {
				reader.Close()
				return fmt.Errorf("receive layer %s: %w", latest.Hash, err)
			}
			reader.Close()

			// Rename received subvolume to content-addressed name.
			receivedPath := fmt.Sprintf("layers/%s@pending", volumeID)
			if d.btrfs.SubvolumeExists(ctx, receivedPath) {
				if d.btrfs.SubvolumeExists(ctx, targetPath) {
					_ = d.btrfs.DeleteSubvolume(ctx, targetPath)
				}
				if err := d.btrfs.RenameSubvolume(ctx, receivedPath, targetPath); err != nil {
					return fmt.Errorf("rename layer to %s: %w", targetPath, err)
				}
			}
		}
		sourcePath = targetPath
	} else if manifest.TemplateName != "" {
		sourcePath = fmt.Sprintf("templates/%s", manifest.TemplateName)
	}

	if sourcePath == "" {
		return fmt.Errorf("no layers and no base template for volume %s", volumeID)
	}

	// Create writable volume from source.
	volumePath := fmt.Sprintf("volumes/%s", volumeID)
	if d.btrfs.SubvolumeExists(ctx, volumePath) {
		if err := d.btrfs.DeleteSubvolume(ctx, volumePath); err != nil {
			return fmt.Errorf("delete existing volume %s: %w", volumeID, err)
		}
	}

	if err := d.btrfs.SnapshotSubvolume(ctx, sourcePath, volumePath, false); err != nil {
		return fmt.Errorf("snapshot to volume %s: %w", volumeID, err)
	}

	// Update tracked state.
	latestHash := manifest.LatestHash()
	d.mu.Lock()
	if tv, ok := d.tracked[volumeID]; ok {
		tv.lastLayerHash = latestHash
		tv.lastSnapPath = sourcePath
	}
	d.mu.Unlock()

	klog.Infof("Restored volume %s from CAS (latest layer)", volumeID)
	return nil
}

// RestoreToSnapshot restores a volume to a specific snapshot hash. The current
// state is saved as a "pre-restore" layer first as an undo point.
func (d *Daemon) RestoreToSnapshot(ctx context.Context, volumeID, targetHash string) error {
	// Per-volume lock serializes with concurrent SyncVolume/CreateSnapshot.
	vl := d.volumeLock(volumeID)
	vl.Lock()
	defer vl.Unlock()

	// Save current state as an undo point before restoring.
	// Call syncOne directly (not CreateSnapshot) since we already hold the lock.
	d.mu.Lock()
	tv, exists := d.tracked[volumeID]
	if !exists {
		d.mu.Unlock()
		return fmt.Errorf("volume %q is not tracked for sync", volumeID)
	}
	tvCopy := *tv
	d.mu.Unlock()

	if hash, newSnapPath, syncErr := d.syncOne(ctx, &tvCopy, "snapshot", "pre-restore"); syncErr != nil {
		klog.Warningf("RestoreToSnapshot: failed to save undo point for %s: %v", volumeID, syncErr)
	} else {
		d.mu.Lock()
		if tv, ok := d.tracked[volumeID]; ok {
			tv.lastLayerHash = hash
			tv.lastSnapPath = newSnapPath
			tv.lastSyncAt = time.Now()
		}
		d.mu.Unlock()
	}

	// Re-read manifest (may have been modified by the undo-point sync above).
	manifest, err := d.cas.GetManifest(ctx, volumeID)
	if err != nil {
		return fmt.Errorf("get manifest for %s: %w", volumeID, err)
	}

	// Find the target layer path.
	var targetLayerPath string
	if targetHash == manifest.Base {
		// Restore to base template.
		if manifest.TemplateName != "" {
			if err := d.tmplMgr.EnsureTemplateByHash(ctx, manifest.TemplateName, manifest.Base); err != nil {
				return fmt.Errorf("ensure base template: %w", err)
			}
			targetLayerPath = fmt.Sprintf("templates/%s", manifest.TemplateName)
		}
	} else {
		// Each layer is independently restorable (full diff from template),
		// so download only the target layer directly.
		var targetLayer *cas.Layer
		for i := range manifest.Layers {
			if manifest.Layers[i].Hash == targetHash {
				targetLayer = &manifest.Layers[i]
				break
			}
		}
		if targetLayer == nil {
			return fmt.Errorf("target hash %s not found in manifest for volume %s", targetHash, volumeID)
		}

		layerPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(targetLayer.Hash))
		if !d.btrfs.SubvolumeExists(ctx, layerPath) {
			reader, err := d.cas.GetBlob(ctx, targetLayer.Hash)
			if err != nil {
				return fmt.Errorf("download layer %s: %w", targetLayer.Hash, err)
			}
			if err := d.btrfs.Receive(ctx, "layers", reader); err != nil {
				reader.Close()
				return fmt.Errorf("receive layer %s: %w", targetLayer.Hash, err)
			}
			reader.Close()

			// Rename received snapshot.
			receivedPath := fmt.Sprintf("layers/%s@pending", volumeID)
			if d.btrfs.SubvolumeExists(ctx, receivedPath) {
				if d.btrfs.SubvolumeExists(ctx, layerPath) {
					_ = d.btrfs.DeleteSubvolume(ctx, layerPath)
				}
				if err := d.btrfs.RenameSubvolume(ctx, receivedPath, layerPath); err != nil {
					return fmt.Errorf("rename layer to %s: %w", layerPath, err)
				}
			}
		}
		targetLayerPath = layerPath
	}

	if targetLayerPath == "" {
		return fmt.Errorf("target hash %s not found in manifest for volume %s", targetHash, volumeID)
	}

	// Replace the volume with a writable snapshot of the target layer.
	volumePath := fmt.Sprintf("volumes/%s", volumeID)
	if d.btrfs.SubvolumeExists(ctx, volumePath) {
		if err := d.btrfs.DeleteSubvolume(ctx, volumePath); err != nil {
			return fmt.Errorf("delete volume for restore: %w", err)
		}
	}
	if err := d.btrfs.SnapshotSubvolume(ctx, targetLayerPath, volumePath, false); err != nil {
		return fmt.Errorf("snapshot target layer to volume: %w", err)
	}

	// Truncate manifest to target.
	manifest.TruncateAfter(targetHash)
	if err := d.cas.PutManifest(ctx, manifest); err != nil {
		return fmt.Errorf("save truncated manifest: %w", err)
	}

	// Update tracked state.
	d.mu.Lock()
	if tv, ok := d.tracked[volumeID]; ok {
		tv.lastLayerHash = targetHash
		tv.lastSnapPath = targetLayerPath
	}
	d.mu.Unlock()

	klog.Infof("Restored volume %s to snapshot %s", volumeID, cas.ShortHash(targetHash))
	return nil
}

// DeleteVolume cleans up the manifest and local layer snapshots for a volume.
// Blob cleanup happens via GC (blobs may be shared across volumes).
func (d *Daemon) DeleteVolume(ctx context.Context, volumeID string) error {
	// Delete manifest from CAS.
	if err := d.cas.DeleteManifest(ctx, volumeID); err != nil {
		klog.Warningf("DeleteVolume: failed to delete manifest for %s: %v", volumeID, err)
	}

	// Delete all local layer snapshots for this volume.
	layers, err := d.btrfs.ListSubvolumes(ctx, fmt.Sprintf("layers/%s@", volumeID))
	if err != nil {
		klog.Warningf("DeleteVolume: failed to list layer snapshots for %s: %v", volumeID, err)
	} else {
		for _, sub := range layers {
			if delErr := d.btrfs.DeleteSubvolume(ctx, sub.Path); delErr != nil {
				klog.Warningf("DeleteVolume: failed to delete layer %s: %v", sub.Path, delErr)
			}
		}
	}

	klog.V(2).Infof("Cleaned up CAS data for volume %s", volumeID)
	return nil
}

// GetManifest returns the CAS manifest for a volume. Convenience accessor
// for callers that need manifest data (e.g., Hub for ListSnapshots).
func (d *Daemon) GetManifest(ctx context.Context, volumeID string) (*cas.Manifest, error) {
	return d.cas.GetManifest(ctx, volumeID)
}

// syncAll iterates over all tracked volumes and syncs each one.
func (d *Daemon) syncAll(ctx context.Context) error {
	d.mu.Lock()
	type syncItem struct {
		tv trackedVolume // copy
	}
	items := make([]syncItem, 0, len(d.tracked))
	for _, tv := range d.tracked {
		items = append(items, syncItem{tv: *tv})
	}
	d.mu.Unlock()

	if len(items) == 0 {
		klog.V(5).Info("No volumes to sync")
		return nil
	}

	klog.V(4).Infof("Starting CAS sync cycle for %d volumes", len(items))
	var firstErr error
	for _, item := range items {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		hash, newSnapPath, err := d.syncOne(ctx, &item.tv, "sync", "")
		if err != nil {
			klog.Errorf("CAS sync failed for volume %s: %v", item.tv.volumeID, err)
			metrics.SyncFailures.Inc()
			if firstErr == nil {
				firstErr = err
			}
			continue
		}

		d.mu.Lock()
		if tv, ok := d.tracked[item.tv.volumeID]; ok {
			tv.lastLayerHash = hash
			tv.lastSnapPath = newSnapPath
			tv.lastSyncAt = time.Now()
		}
		d.mu.Unlock()
		metrics.SyncLag.WithLabelValues(item.tv.volumeID).Set(0)

		// Update qgroup metrics if quotas are enabled.
		if excl, limit, qErr := d.btrfs.GetQgroupUsage(ctx, "volumes/"+item.tv.volumeID); qErr == nil {
			metrics.QgroupUsageBytes.WithLabelValues(item.tv.volumeID).Set(float64(excl))
			metrics.QgroupLimitBytes.WithLabelValues(item.tv.volumeID).Set(float64(limit))
		}
	}

	return firstErr
}

// syncOne performs the CAS sync algorithm for a single volume:
//  1. Create read-only snapshot: layers/{volumeID}@pending
//  2. Determine parent snapshot path for incremental send
//  3. btrfs send → cas.PutBlob() → get hash
//  4. Update manifest with new layer
//  5. Rotate layer snapshot to layers/{volumeID}@{shortHash}
func (d *Daemon) syncOne(ctx context.Context, tv *trackedVolume, layerType, label string) (string, string, error) {
	if d.cas == nil {
		return "", "", fmt.Errorf("CAS store not configured")
	}
	start := time.Now()

	volumePath := fmt.Sprintf("volumes/%s", tv.volumeID)
	pendingPath := fmt.Sprintf("layers/%s@pending", tv.volumeID)

	if !d.btrfs.SubvolumeExists(ctx, volumePath) {
		return "", "", fmt.Errorf("volume subvolume %q does not exist", volumePath)
	}

	// Clean up stale pending snapshot from a previous failed run.
	if d.btrfs.SubvolumeExists(ctx, pendingPath) {
		if err := d.btrfs.DeleteSubvolume(ctx, pendingPath); err != nil {
			klog.Warningf("stale pending snapshot %q undeletable, using unique suffix: %v", pendingPath, err)
			pendingPath = fmt.Sprintf("layers/%s@pending-%d", tv.volumeID, time.Now().UnixNano())
		}
	}

	// 1. Create a read-only snapshot.
	if err := d.btrfs.SnapshotSubvolume(ctx, volumePath, pendingPath, true); err != nil {
		return "", "", fmt.Errorf("create pending snapshot: %w", err)
	}

	// 2. Determine parent for incremental send. Always use the template so
	// every layer is independently restorable (no chain dependency).
	var parentPath string
	if tv.templateName != "" {
		tmplPath := fmt.Sprintf("templates/%s", tv.templateName)
		if d.btrfs.SubvolumeExists(ctx, tmplPath) {
			parentPath = tmplPath
		}
	}
	// If no template, full send (blank project or template not locally cached).

	// 3. btrfs send → CAS PutBlob.
	sendReader, err := d.btrfs.Send(ctx, pendingPath, parentPath)
	if err != nil {
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		return "", "", fmt.Errorf("btrfs send: %w", err)
	}

	hash, err := d.cas.PutBlob(ctx, sendReader)
	_ = sendReader.Close()
	if err != nil {
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		return "", "", fmt.Errorf("put blob: %w", err)
	}

	// 4. Update manifest.
	manifest, manErr := d.cas.GetManifest(ctx, tv.volumeID)
	if manErr != nil {
		// Manifest doesn't exist yet — create it.
		manifest = &cas.Manifest{
			VolumeID:     tv.volumeID,
			Base:         tv.templateHash,
			TemplateName: tv.templateName,
		}
	}

	parentHash := tv.templateHash
	manifest.AppendLayer(cas.Layer{
		Hash:   hash,
		Parent: parentHash,
		Type:   layerType,
		Label:  label,
		TS:     time.Now().UTC().Format(time.RFC3339),
	})

	if err := d.cas.PutManifest(ctx, manifest); err != nil {
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		return "", "", fmt.Errorf("put manifest: %w", err)
	}

	// 5. Rotate layer snapshots: delete old, rename pending to final.
	shortHash := cas.ShortHash(hash)
	newSnapPath := fmt.Sprintf("layers/%s@%s", tv.volumeID, shortHash)

	if tv.lastSnapPath != "" && d.btrfs.SubvolumeExists(ctx, tv.lastSnapPath) {
		if delErr := d.btrfs.DeleteSubvolume(ctx, tv.lastSnapPath); delErr != nil {
			klog.Warningf("Failed to delete old layer snapshot %s: %v", tv.lastSnapPath, delErr)
		}
	}

	// Rename pending snapshot to content-addressed name. os.Rename preserves
	// UUID and received_uuid, critical for cross-node incremental restore.
	if d.btrfs.SubvolumeExists(ctx, newSnapPath) {
		_ = d.btrfs.DeleteSubvolume(ctx, newSnapPath)
	}
	if err := d.btrfs.RenameSubvolume(ctx, pendingPath, newSnapPath); err != nil {
		klog.Warningf("Failed to rename pending to %s: %v", newSnapPath, err)
		newSnapPath = pendingPath // Keep using pending path as fallback.
	}

	metrics.SyncDuration.Observe(time.Since(start).Seconds())
	klog.V(2).Infof("CAS synced volume %s → blob %s (type=%s)",
		tv.volumeID, cas.ShortHash(hash), layerType)

	return hash, newSnapPath, nil
}
