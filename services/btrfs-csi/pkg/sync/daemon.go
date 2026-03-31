package sync

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/sync/errgroup"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/ioutil"
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
	dirty         bool // true = volume has changed since last successful sync
}

// discoverInterval is the number of syncAll cycles between periodic
// discoverVolumes runs. With a 15s sync interval this means re-discovery
// every ~75s — fast enough to catch service volumes created by the Hub.
const discoverInterval = 5

// Daemon periodically snapshots tracked volumes, uploads incremental layers
// to the CAS store, and maintains volume manifests.
type Daemon struct {
	btrfs    btrfsOps
	cas      casOps
	tmplMgr  templateOps
	interval time.Duration
	mu       sync.Mutex
	tracked  map[string]*trackedVolume
	syncLocks   sync.Mutex                  // guards volLocks
	volLocks    map[string]*sync.Mutex       // per-volume sync serialization
	discoverCycle atomic.Int32               // counts syncAll cycles for periodic discovery
	stopCh   chan struct{}
	wg       sync.WaitGroup
}

// NewDaemon creates a sync Daemon that uses the CAS store for all storage.
func NewDaemon(bm *btrfs.Manager, casStore *cas.Store, tmplMgr *template.Manager, interval time.Duration) *Daemon {
	d := &Daemon{
		interval:  interval,
		tracked:   make(map[string]*trackedVolume),
		volLocks:  make(map[string]*sync.Mutex),
		stopCh:    make(chan struct{}),
	}
	// Store concrete types as interfaces for testability.
	// nil checks preserve backward compatibility with callers that pass nil.
	if bm != nil {
		d.btrfs = bm
	}
	if casStore != nil {
		d.cas = casStore
	}
	if tmplMgr != nil {
		d.tmplMgr = tmplMgr
	}
	return d
}

// newDaemonWithInterfaces creates a Daemon with pre-built interface
// implementations. Used by tests to inject fakes.
func newDaemonWithInterfaces(b btrfsOps, c casOps, t templateOps, interval time.Duration) *Daemon {
	return &Daemon{
		btrfs:    b,
		cas:      c,
		tmplMgr:  t,
		interval: interval,
		tracked:  make(map[string]*trackedVolume),
		volLocks: make(map[string]*sync.Mutex),
		stopCh:   make(chan struct{}),
	}
}

// Start begins the periodic sync loop. It blocks until Stop is called or the
// provided context is cancelled.
func (d *Daemon) Start(ctx context.Context) {
	klog.Info("Sync daemon starting (CAS mode)")
	d.wg.Add(1)
	defer d.wg.Done()

	// Auto-discover volumes on disk that aren't tracked yet.
	d.discoverVolumes(ctx)

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

// discoverVolumes scans volumes/ subvolumes on disk and tracks any that
// aren't already tracked. This recovers sync tracking after a pod restart.
// Template context is recovered from the CAS manifest if available.
//
// Smart dirty detection: for each volume, finds the corresponding layer
// snapshot (layers/{volID}@*) and compares btrfs generations. If the
// volume's generation matches the snapshot's, the volume hasn't changed
// since the last sync and starts as clean. This prevents a thundering
// herd re-sync of all volumes after every rolling restart.
func (d *Daemon) discoverVolumes(ctx context.Context) {
	if d.btrfs == nil {
		return
	}

	subs, err := d.btrfs.ListSubvolumes(ctx, "volumes/")
	if err != nil {
		klog.Warningf("discoverVolumes: failed to list subvolumes: %v", err)
		return
	}

	// Build a map of layer snapshots for generation comparison.
	// Layer snapshots are at layers/{volID}@{shortHash}.
	layerSnaps := make(map[string]string) // volID → snapshot path
	layers, _ := d.btrfs.ListSubvolumes(ctx, "layers/")
	for _, layer := range layers {
		name := strings.TrimPrefix(layer.Path, "layers/")
		if atIdx := strings.Index(name, "@"); atIdx > 0 {
			volID := name[:atIdx]
			// Keep the latest snapshot (lexicographically last — they're
			// content-addressed hashes, so any is fine; we just need one).
			layerSnaps[volID] = layer.Path
		}
	}

	// --- Pass 1: Collect volume IDs to discover (local, fast). ---
	var volIDs []string
	for _, sub := range subs {
		volID := strings.TrimPrefix(sub.Path, "volumes/")
		if volID == "" || volID == sub.Path {
			continue
		}
		d.mu.Lock()
		_, alreadyTracked := d.tracked[volID]
		d.mu.Unlock()
		if alreadyTracked {
			continue
		}
		volIDs = append(volIDs, volID)
	}
	if len(volIDs) == 0 {
		return
	}

	// --- Pass 2: Fetch manifests from S3 in parallel (the slow part). ---
	// GetManifest is a pure read — safe to call concurrently. Results are
	// collected into a map and consumed serially in pass 3. Cap at 10
	// concurrent S3 reads to avoid overwhelming the connection.
	type manifestInfo struct {
		templateName string
		templateHash string
	}
	manifestMap := make(map[string]manifestInfo, len(volIDs))
	if d.cas != nil {
		var mu sync.Mutex
		var wg sync.WaitGroup
		sem := make(chan struct{}, 10)

		for _, volID := range volIDs {
			wg.Add(1)
			go func(vid string) {
				defer wg.Done()
				sem <- struct{}{}
				defer func() { <-sem }()

				if m, err := d.cas.GetManifest(ctx, vid); err == nil {
					mu.Lock()
					manifestMap[vid] = manifestInfo{
						templateName: m.TemplateName,
						templateHash: m.Base,
					}
					mu.Unlock()
				}
			}(volID)
		}
		wg.Wait()
	}

	// --- Pass 3: Track volumes with generation-based dirty detection. ---
	discovered := 0
	clean := 0
	dirty := 0
	for _, volID := range volIDs {
		mi := manifestMap[volID] // zero-value if manifest not found

		isDirty := true // default: dirty (safe — will sync if unsure)
		snapPath, hasSnap := layerSnaps[volID]
		if hasSnap {
			volGen, volErr := d.btrfs.GetGeneration(ctx, "volumes/"+volID)
			snapGen, snapErr := d.btrfs.GetGeneration(ctx, snapPath)
			if volErr == nil && snapErr == nil {
				if volGen <= snapGen {
					isDirty = false
				} else {
					klog.V(2).Infof("discoverVolumes: %s dirty (vol gen %d > snap gen %d)",
						volID, volGen, snapGen)
				}
			} else {
				klog.V(2).Infof("discoverVolumes: %s dirty (generation check failed: vol=%v snap=%v)",
					volID, volErr, snapErr)
			}
		}

		d.TrackVolume(volID, mi.templateName, mi.templateHash)

		if !isDirty {
			d.mu.Lock()
			if tv, ok := d.tracked[volID]; ok {
				tv.dirty = false
				tv.lastSnapPath = snapPath
			}
			d.mu.Unlock()
			clean++
		} else {
			dirty++
		}
		discovered++
	}

	if discovered > 0 {
		klog.Infof("discoverVolumes: auto-tracked %d volume(s) from disk (%d clean, %d dirty)",
			discovered, clean, dirty)
	}
}

// cleanupStaging deletes orphaned S3 staging keys left by crashed uploads.
// Called alongside periodic discoverVolumes as housekeeping.
func (d *Daemon) cleanupStaging(ctx context.Context) {
	if d.cas == nil {
		return
	}
	if _, err := d.cas.CleanupStaging(ctx); err != nil {
		klog.Warningf("cleanupStaging: %v", err)
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

// DrainAll performs a final CAS sync for dirty tracked volumes, then stops
// the daemon. Used during node drain to persist unsaved data before
// DaemonSet pod termination. Clean volumes are skipped — their data is
// already in S3 from the last successful sync.
func (d *Daemon) DrainAll(ctx context.Context) error {
	// Re-discover volumes from disk before snapshotting the tracked map.
	// This catches service volumes and any volumes created after the last
	// periodic discovery but before the drain signal arrived.
	d.discoverVolumes(ctx)

	d.mu.Lock()
	type drainItem struct {
		volumeID     string
		templateName string
		templateHash string
	}
	var items []drainItem
	skipped := 0
	for _, tv := range d.tracked {
		if !tv.dirty {
			skipped++
			continue
		}
		items = append(items, drainItem{
			volumeID:     tv.volumeID,
			templateName: tv.templateName,
			templateHash: tv.templateHash,
		})
	}
	total := len(d.tracked)
	d.mu.Unlock()

	klog.Infof("Drain: %d dirty volumes to sync in parallel (max 3), %d clean (skipped), %d total", len(items), skipped, total)

	// Early exit if already cancelled.
	if ctx.Err() != nil {
		return ctx.Err()
	}

	// Parallel drain: sync up to 3 dirty volumes concurrently.
	// Per-volume locking inside SyncVolume prevents two goroutines from
	// syncing the same volume. Different volumes are fully independent.
	g, gctx := errgroup.WithContext(ctx)
	sem := make(chan struct{}, 3) // concurrency cap
	var synced sync.Map

	for _, item := range items {
		item := item // capture loop var
		g.Go(func() error {
			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-gctx.Done():
				return gctx.Err()
			}

			if err := d.SyncVolume(gctx, item.volumeID); err != nil {
				if gctx.Err() != nil {
					return gctx.Err() // propagate cancellation
				}
				klog.Errorf("Drain: failed to sync %s: %v", item.volumeID, err)
				return nil // non-cancel error: continue draining others
			}
			// Remove from tracked map but KEEP the layer snapshot on disk.
			// The next pod's discoverVolumes needs the snapshot to compare
			// generations and detect clean volumes (avoids thundering herd
			// re-sync of all volumes after every rolling restart).
			d.mu.Lock()
			delete(d.tracked, item.volumeID)
			d.mu.Unlock()
			synced.Store(item.volumeID, true)
			return nil
		})
	}

	err := g.Wait()

	syncedCount := 0
	synced.Range(func(_, _ interface{}) bool { syncedCount++; return true })
	klog.Infof("Drain: synced %d/%d dirty volumes (syncer remains active for late RPCs)", syncedCount, len(items))

	// If context was cancelled, surface the cancellation error.
	if ctx.Err() != nil {
		return ctx.Err()
	}
	return err
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
		dirty:        true, // new volumes always need initial sync
	}
	klog.V(2).Infof("Tracking volume %s for CAS sync (template=%s, base=%s)",
		volumeID, templateName, cas.ShortHash(templateHash))
}

// MarkDirty flags a tracked volume as needing sync. Safe to call from any
// goroutine; no-op if the volume isn't tracked.
func (d *Daemon) MarkDirty(volumeID string) {
	d.mu.Lock()
	defer d.mu.Unlock()
	if tv, ok := d.tracked[volumeID]; ok {
		tv.dirty = true
	}
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
	Dirty        bool   `json:"dirty"`
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
			Dirty:        tv.dirty,
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
		tv.templateName = tvCopy.templateName
		tv.templateHash = tvCopy.templateHash
		tv.dirty = false
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
		tv.templateName = tvCopy.templateName
		tv.templateHash = tvCopy.templateHash
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

	// Ensure base template exists locally. If manifest.Base is empty but
	// layers have a parent hash (auto-promoted volumes with stale manifest),
	// use the layer parent as the effective base.
	effectiveBase := manifest.Base
	effectiveTmpl := manifest.TemplateName
	if effectiveBase == "" && len(manifest.Layers) > 0 && manifest.Layers[0].Parent != "" {
		effectiveBase = manifest.Layers[0].Parent
		effectiveTmpl = "_vol_" + volumeID
		klog.Infof("RestoreVolume: manifest.Base empty, using layer parent %s as base for %s",
			cas.ShortHash(effectiveBase), volumeID)
	}
	if effectiveBase != "" && effectiveTmpl != "" {
		if err := d.tmplMgr.EnsureTemplateByHash(ctx, effectiveTmpl, effectiveBase); err != nil {
			return fmt.Errorf("ensure base template %s: %w", effectiveTmpl, err)
		}
	}

	// Determine source for writable volume: latest layer or base template.
	var sourcePath string
	if len(manifest.Layers) > 0 {
		latest := manifest.Layers[len(manifest.Layers)-1]
		targetPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(latest.Hash))

		if !d.btrfs.SubvolumeExists(ctx, targetPath) {
			if err := d.downloadLayer(ctx, volumeID, latest.Hash, targetPath); err != nil {
				return fmt.Errorf("restore layer %s: %w", latest.Hash, err)
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
			if err := d.downloadLayer(ctx, volumeID, targetLayer.Hash, layerPath); err != nil {
				return fmt.Errorf("restore layer %s: %w", targetLayer.Hash, err)
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

	// Clean up synthetic per-volume template if present.
	syntheticTmpl := "templates/_vol_" + volumeID
	if d.btrfs.SubvolumeExists(ctx, syntheticTmpl) {
		if delErr := d.btrfs.DeleteSubvolume(ctx, syntheticTmpl); delErr != nil {
			klog.Warningf("DeleteVolume: failed to delete synthetic template %s: %v", syntheticTmpl, delErr)
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

// SyncAll runs a single CAS sync cycle. Exported for integration tests
// that need to trigger cycles without waiting for the ticker.
func (d *Daemon) SyncAll(ctx context.Context) error {
	return d.syncAll(ctx)
}

// syncAll iterates over all tracked volumes and syncs dirty ones.
// Volumes marked clean are verified via btrfs generation comparison —
// if the volume's generation advanced past its layer snapshot, it was
// modified by a process outside FileOps (e.g. compute pod) and needs
// syncing despite the dirty flag being false.
func (d *Daemon) syncAll(ctx context.Context) error {
	// Periodic re-discovery: scan disk for untracked volumes every Nth cycle.
	// This catches service volumes created by the Hub and any volumes that
	// appeared after the initial startup discovery. Atomic counter because
	// SyncAll is exported and could be called concurrently with the ticker.
	if d.discoverCycle.Add(1) >= int32(discoverInterval) {
		d.discoverCycle.Store(0)
		d.discoverVolumes(ctx)
		d.cleanupStaging(ctx)
	}

	// Snapshot tracked state under lock (fast).
	type candidate struct {
		tv           trackedVolume
		needGenCheck bool // clean volume with a layer snapshot — verify via generation
	}
	d.mu.Lock()
	candidates := make([]candidate, 0, len(d.tracked))
	for _, tv := range d.tracked {
		c := candidate{tv: *tv}
		if !tv.dirty && tv.lastSnapPath != "" {
			c.needGenCheck = true
		}
		candidates = append(candidates, c)
	}
	d.mu.Unlock()

	// Generation check for clean volumes — outside the lock since
	// GetGeneration runs a btrfs subprocess (~1ms each).
	for i := range candidates {
		c := &candidates[i]
		if !c.needGenCheck {
			continue
		}
		volGen, volErr := d.btrfs.GetGeneration(ctx, "volumes/"+c.tv.volumeID)
		snapGen, snapErr := d.btrfs.GetGeneration(ctx, c.tv.lastSnapPath)
		if volErr == nil && snapErr == nil && volGen > snapGen {
			klog.V(2).Infof("syncAll: %s promoted to dirty (vol gen %d > snap gen %d, direct write detected)",
				c.tv.volumeID, volGen, snapGen)
			c.tv.dirty = true
			// Also update the tracked map so DrainAll sees it.
			d.mu.Lock()
			if tv, ok := d.tracked[c.tv.volumeID]; ok {
				tv.dirty = true
			}
			d.mu.Unlock()
		}
	}

	// Build final sync list.
	type syncItem struct {
		tv trackedVolume
	}
	items := make([]syncItem, 0, len(candidates))
	skipped := 0
	for _, c := range candidates {
		if !c.tv.dirty {
			skipped++
			continue
		}
		items = append(items, syncItem{tv: c.tv})
	}


	if len(items) == 0 {
		if skipped > 0 {
			klog.V(5).Infof("No dirty volumes to sync (%d clean, skipped)", skipped)
		} else {
			klog.V(5).Info("No volumes to sync")
		}
		return nil
	}

	klog.V(4).Infof("Starting CAS sync cycle for %d dirty volumes (%d clean, skipped)", len(items), skipped)
	var firstErr error
	for _, item := range items {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		// Per-volume lock serializes with concurrent SyncVolume/CreateSnapshot RPCs.
		vl := d.volumeLock(item.tv.volumeID)
		vl.Lock()
		hash, newSnapPath, err := d.syncOne(ctx, &item.tv, "sync", "")
		vl.Unlock()

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
			tv.templateName = item.tv.templateName
			tv.templateHash = item.tv.templateHash
			tv.dirty = false
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

	// 3. btrfs send → CAS PutBlob with stall detection.
	sendReader, err := d.btrfs.Send(ctx, pendingPath, parentPath)
	if err != nil {
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		return "", "", fmt.Errorf("btrfs send: %w", err)
	}

	// Wrap with stall detection: if no bytes flow for 30s, the sync is stuck
	// (S3 hang, network partition, dead rclone). Cancel to unblock.
	stallCtx, stallCancel := context.WithCancelCause(ctx)
	stallR := ioutil.NewStallReader(sendReader, stallCtx, stallCancel, ioutil.StallTimeout)

	hash, err := d.cas.PutBlob(stallCtx, stallR)
	stallR.Close() // stops timer + closes underlying sendReader
	if err != nil {
		// Annotate with stall cause if the stall timer (not parent ctx) caused cancellation.
		if cause := context.Cause(stallCtx); cause != nil {
			err = fmt.Errorf("%w (cause: %v)", err, cause)
		}
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		return "", "", fmt.Errorf("put blob: %w", err)
	}

	// Auto-promote: template-less volumes get a synthetic per-volume template
	// after their first successful sync. This converts the full send into a
	// base layer so all future syncs are incremental diffs — same as
	// template-based volumes.
	if tv.templateName == "" {
		syntheticName := "_vol_" + tv.volumeID
		tmplPath := "templates/" + syntheticName

		if d.btrfs.SubvolumeExists(ctx, tmplPath) {
			// Template already exists on disk (e.g. from a previous run before
			// pod restart). Re-upload to get the hash and adopt it.
			if uploadHash, uploadErr := d.tmplMgr.UploadTemplate(ctx, syntheticName); uploadErr != nil {
				klog.Warningf("Auto-promote: failed to upload existing template for %s: %v (syncs will remain full sends)", tv.volumeID, uploadErr)
			} else {
				klog.Infof("Auto-promote: volume %s adopted existing synthetic template %s (future syncs incremental)", tv.volumeID, syntheticName)
				tv.templateName = syntheticName
				tv.templateHash = uploadHash
			}
		} else if snapErr := d.btrfs.SnapshotSubvolume(ctx, pendingPath, tmplPath, true); snapErr != nil {
			klog.Warningf("Auto-promote: failed to create synthetic template for %s: %v (syncs will remain full sends)", tv.volumeID, snapErr)
		} else if uploadHash, uploadErr := d.tmplMgr.UploadTemplate(ctx, syntheticName); uploadErr != nil {
			klog.Warningf("Auto-promote: failed to upload synthetic template for %s: %v (syncs will remain full sends)", tv.volumeID, uploadErr)
			_ = d.btrfs.DeleteSubvolume(ctx, tmplPath)
		} else {
			klog.Infof("Auto-promote: volume %s now has synthetic template %s (future syncs incremental)", tv.volumeID, syntheticName)
			tv.templateName = syntheticName
			tv.templateHash = uploadHash
		}
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
	} else if manifest.Base == "" && tv.templateHash != "" {
		// Auto-promote adopted or created a synthetic template but the
		// manifest was created before the template existed (e.g. pod restart).
		// Backfill Base/TemplateName so RestoreVolume can download the
		// template for cross-node restores.
		manifest.Base = tv.templateHash
		manifest.TemplateName = tv.templateName
		klog.Infof("Backfilled manifest Base for %s: template=%s hash=%s",
			tv.volumeID, tv.templateName, cas.ShortHash(tv.templateHash))
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

// downloadLayer downloads a CAS blob and receives it as a layer snapshot.
// Includes idempotent @pending cleanup (prevents permanent bricking after a
// failed receive) and stall detection (cancels on 30s of zero I/O progress).
func (d *Daemon) downloadLayer(ctx context.Context, volumeID, blobHash, targetPath string) error {
	pendingPath := fmt.Sprintf("layers/%s@pending", volumeID)

	// Idempotent cleanup: remove stale @pending from a previous failed run.
	if d.btrfs.SubvolumeExists(ctx, pendingPath) {
		if err := d.btrfs.DeleteSubvolume(ctx, pendingPath); err != nil {
			klog.Warningf("stale pending snapshot %q undeletable, using unique suffix: %v", pendingPath, err)
			pendingPath = fmt.Sprintf("layers/%s@pending-%d", volumeID, time.Now().UnixNano())
		}
	}

	reader, err := d.cas.GetBlob(ctx, blobHash)
	if err != nil {
		return fmt.Errorf("download blob %s: %w", blobHash, err)
	}

	stallCtx, stallCancel := context.WithCancelCause(ctx)
	stallR := ioutil.NewStallReader(reader, stallCtx, stallCancel, ioutil.StallTimeout)

	if err := d.btrfs.Receive(stallCtx, "layers", stallR); err != nil {
		stallR.Close()
		// Clean up partial @pending from the failed receive.
		if d.btrfs.SubvolumeExists(ctx, pendingPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		}
		if cause := context.Cause(stallCtx); cause != nil {
			err = fmt.Errorf("%w (cause: %v)", err, cause)
		}
		return fmt.Errorf("btrfs receive blob %s: %w", blobHash, err)
	}
	stallR.Close()

	// Rename received subvolume to content-addressed name.
	if d.btrfs.SubvolumeExists(ctx, pendingPath) {
		if d.btrfs.SubvolumeExists(ctx, targetPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, targetPath)
		}
		if err := d.btrfs.RenameSubvolume(ctx, pendingPath, targetPath); err != nil {
			return fmt.Errorf("rename layer to %s: %w", targetPath, err)
		}
	}
	return nil
}
