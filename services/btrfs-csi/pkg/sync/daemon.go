package sync

import (
	"context"
	"errors"
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
	volumeID              string
	templateName          string // template used to create this volume
	templateHash          string // base blob hash from template
	lastLayerHash         string // hash of most recent layer (parent for next send)
	lastSnapPath          string // local path of last layer snapshot (for -p parent)
	lastConsolidationPath string // local path of latest consolidation snapshot
	lastConsolidationHash string // hash of latest consolidation
	lastSyncAt            time.Time
	dirty                 bool // true = volume has changed since last successful sync
}

// errVolumeGone is returned by syncOne when the volume subvolume no longer
// exists on disk. syncAll uses this to auto-untrack the volume instead of
// retrying every cycle.
var errVolumeGone = errors.New("volume subvolume gone")

// discoverInterval is the number of syncAll cycles between periodic
// discoverVolumes runs. With a 15s sync interval this means re-discovery
// every ~75s — fast enough to catch service volumes created by the Hub.
const discoverInterval = 5

// Daemon snapshots tracked volumes on demand (event-driven) and via a
// periodic safety-net timer, uploads incremental layers to the CAS store,
// and maintains volume manifests with automatic consolidation.
type Daemon struct {
	btrfs    btrfsOps
	cas      casOps
	tmplMgr  templateOps
	interval time.Duration // safety-net periodic sync interval
	mu       sync.Mutex
	tracked  map[string]*trackedVolume
	syncLocks   sync.Mutex                  // guards volLocks
	volLocks    map[string]*sync.Mutex       // per-volume sync serialization
	discoverCycle atomic.Int32               // counts syncAll cycles for periodic discovery
	stopCh   chan struct{}
	wg       sync.WaitGroup

	// Consolidation config.
	consolidationInterval  int // create consolidation every N snapshots (0 = disabled)
	consolidationRetention int // keep last K consolidation blobs (0 = keep all)
}

// DaemonConfig holds configuration for the sync Daemon.
type DaemonConfig struct {
	// SafetyInterval is the periodic safety-net sync interval. Volumes that
	// haven't been synced by an explicit event within this window will be
	// synced automatically. Default: 5 minutes.
	SafetyInterval time.Duration

	// ConsolidationInterval is the number of snapshots between automatic
	// consolidation points. 0 disables consolidation.
	ConsolidationInterval int

	// ConsolidationRetention is the number of consolidation blobs to keep.
	// Older consolidations have their blobs pruned from CAS. 0 = keep all.
	ConsolidationRetention int
}

// DefaultDaemonConfig returns sensible defaults for production.
func DefaultDaemonConfig() DaemonConfig {
	return DaemonConfig{
		SafetyInterval:         5 * time.Minute,
		ConsolidationInterval:  50,
		ConsolidationRetention: 3,
	}
}

// NewDaemon creates a sync Daemon that uses the CAS store for all storage.
func NewDaemon(bm *btrfs.Manager, casStore *cas.Store, tmplMgr *template.Manager, interval time.Duration) *Daemon {
	cfg := DefaultDaemonConfig()
	cfg.SafetyInterval = interval
	return NewDaemonWithConfig(bm, casStore, tmplMgr, cfg)
}

// NewDaemonWithConfig creates a sync Daemon with explicit configuration.
func NewDaemonWithConfig(bm *btrfs.Manager, casStore *cas.Store, tmplMgr *template.Manager, cfg DaemonConfig) *Daemon {
	d := &Daemon{
		interval:               cfg.SafetyInterval,
		consolidationInterval:  cfg.ConsolidationInterval,
		consolidationRetention: cfg.ConsolidationRetention,
		tracked:                make(map[string]*trackedVolume),
		volLocks:               make(map[string]*sync.Mutex),
		stopCh:                 make(chan struct{}),
	}
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
		btrfs:                  b,
		cas:                    c,
		tmplMgr:                t,
		interval:               interval,
		consolidationInterval:  50,
		consolidationRetention: 3,
		tracked:                make(map[string]*trackedVolume),
		volLocks:               make(map[string]*sync.Mutex),
		stopCh:                 make(chan struct{}),
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

	// --- Pass 2: Fetch manifests + check tombstones from S3 in parallel. ---
	// GetManifest is a pure read — safe to call concurrently. Cap at 10
	// concurrent S3 reads. Tombstoned volumes are collected for local
	// cleanup instead of being tracked.
	type manifestInfo struct {
		templateName string
		templateHash string
	}
	manifestMap := make(map[string]manifestInfo, len(volIDs))
	var tombstoned []string
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

				// Check tombstone BEFORE fetching manifest. If tombstoned,
				// skip manifest fetch — the volume is deleted.
				if isTombstoned, err := d.cas.HasTombstone(ctx, vid); err == nil && isTombstoned {
					mu.Lock()
					tombstoned = append(tombstoned, vid)
					mu.Unlock()
					return
				}

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

	// --- Self-healing: clean up tombstoned volumes found on disk. ---
	// The volume was deleted (tombstone written) but the subvolume persists
	// on this node (e.g., the node was offline when delete was issued).
	// Delete local resources and remove the tombstone.
	for _, vid := range tombstoned {
		klog.Infof("discoverVolumes: volume %s is tombstoned, cleaning up local resources", vid)
		cleanupCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
		volPath := "volumes/" + vid
		if d.btrfs.SubvolumeExists(cleanupCtx, volPath) {
			if err := d.btrfs.DeleteSubvolume(cleanupCtx, volPath); err != nil {
				klog.Warningf("discoverVolumes: failed to delete tombstoned subvolume %s: %v", volPath, err)
			}
		}
		// Clean up layer snapshots.
		if layerSubs, err := d.btrfs.ListSubvolumes(cleanupCtx, fmt.Sprintf("layers/%s@", vid)); err == nil {
			for _, sub := range layerSubs {
				_ = d.btrfs.DeleteSubvolume(cleanupCtx, sub.Path)
			}
		}
		// Clean up synthetic template.
		synthPath := "templates/_vol_" + vid
		if d.btrfs.SubvolumeExists(cleanupCtx, synthPath) {
			_ = d.btrfs.DeleteSubvolume(cleanupCtx, synthPath)
		}
		// Remove the tombstone now that local cleanup is done.
		if err := d.cas.DeleteTombstone(cleanupCtx, vid); err != nil {
			klog.Warningf("discoverVolumes: failed to remove tombstone for %s: %v", vid, err)
		}
		cancel()
	}

	// Filter tombstoned volumes from the tracking list.
	if len(tombstoned) > 0 {
		tombSet := make(map[string]bool, len(tombstoned))
		for _, vid := range tombstoned {
			tombSet[vid] = true
		}
		filtered := volIDs[:0]
		for _, vid := range volIDs {
			if !tombSet[vid] {
				filtered = append(filtered, vid)
			}
		}
		volIDs = filtered
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
// layer snapshot if one exists. Acquires the per-volume lock first to wait
// for any inflight SyncVolume/CreateSnapshot/RestoreToSnapshot to finish,
// preventing a race where the layer snapshot is deleted while syncOne is
// using it as a btrfs send parent.
func (d *Daemon) UntrackVolume(volumeID string) {
	// Lock ordering: per-volume lock → d.mu (same as SyncVolume, syncAll).
	vl := d.volumeLock(volumeID)
	vl.Lock()
	defer vl.Unlock()

	d.mu.Lock()
	tv, exists := d.tracked[volumeID]
	if !exists {
		d.mu.Unlock()
		return
	}
	lastSnapPath := tv.lastSnapPath
	delete(d.tracked, volumeID)
	d.mu.Unlock()

	// Safe to delete — no sync is running on this volume.
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
		tv.lastConsolidationPath = tvCopy.lastConsolidationPath
		tv.lastConsolidationHash = tvCopy.lastConsolidationHash
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

	hash, newSnapPath, err := d.syncOne(ctx, &tvCopy, "checkpoint", label)
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
		tv.lastConsolidationPath = tvCopy.lastConsolidationPath
		tv.lastConsolidationHash = tvCopy.lastConsolidationHash
	}
	d.mu.Unlock()
	return hash, nil
}

// RestoreVolume restores a volume from CAS by replaying the incremental
// snapshot chain. The chain is: template → consolidations → incrementals.
// Only the minimum set of snapshots needed to reconstruct the latest state
// is downloaded.
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

	// Ensure base template exists locally (if volume was created from a template).
	if manifest.Base != "" && manifest.TemplateName != "" {
		if err := d.tmplMgr.EnsureTemplateByHash(ctx, manifest.TemplateName, manifest.Base); err != nil {
			return fmt.Errorf("ensure base template %s: %w", manifest.TemplateName, err)
		}
	}

	volumePath := fmt.Sprintf("volumes/%s", volumeID)

	if len(manifest.Snapshots) == 0 {
		// No snapshots — restore from template directly.
		if manifest.TemplateName == "" {
			return fmt.Errorf("no layers and no base template for volume %s", volumeID)
		}
		tmplPath := fmt.Sprintf("templates/%s", manifest.TemplateName)
		if d.btrfs.SubvolumeExists(ctx, volumePath) {
			if err := d.btrfs.DeleteSubvolume(ctx, volumePath); err != nil {
				return fmt.Errorf("delete existing volume %s: %w", volumeID, err)
			}
		}
		if err := d.btrfs.SnapshotSubvolume(ctx, tmplPath, volumePath, false); err != nil {
			return fmt.Errorf("snapshot template to volume %s: %w", volumeID, err)
		}
		klog.Infof("Restored volume %s from template (no snapshots)", volumeID)
		return nil
	}

	// Build the restore chain for the latest snapshot.
	targetIdx := len(manifest.Snapshots) - 1
	chain := manifest.BuildRestoreChain(targetIdx)

	// Download and receive each layer in the chain in order.
	// btrfs receive creates subvolumes that serve as parents for the next receive.
	var lastReceivedPath string
	for _, idx := range chain {
		snap := manifest.Snapshots[idx]
		layerPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(snap.Hash))

		if !d.btrfs.SubvolumeExists(ctx, layerPath) {
			if err := d.downloadLayer(ctx, volumeID, snap.Hash, layerPath); err != nil {
				return fmt.Errorf("restore snapshot %d (%s): %w", idx, cas.ShortHash(snap.Hash), err)
			}
		}
		lastReceivedPath = layerPath
	}

	if lastReceivedPath == "" {
		return fmt.Errorf("empty restore chain for volume %s", volumeID)
	}

	// Create writable volume from the final received snapshot.
	if d.btrfs.SubvolumeExists(ctx, volumePath) {
		if err := d.btrfs.DeleteSubvolume(ctx, volumePath); err != nil {
			return fmt.Errorf("delete existing volume %s: %w", volumeID, err)
		}
	}
	if err := d.btrfs.SnapshotSubvolume(ctx, lastReceivedPath, volumePath, false); err != nil {
		return fmt.Errorf("snapshot to volume %s: %w", volumeID, err)
	}

	// Clean up intermediate layer snapshots (keep only the latest + latest consolidation).
	latestSnap := manifest.Snapshots[targetIdx]
	latestConsolHash := ""
	if consol := manifest.LatestConsolidation(); consol != nil {
		latestConsolHash = consol.Hash
	}
	for _, idx := range chain {
		snap := manifest.Snapshots[idx]
		if snap.Hash == latestSnap.Hash || snap.Hash == latestConsolHash {
			continue // keep these
		}
		layerPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(snap.Hash))
		if d.btrfs.SubvolumeExists(ctx, layerPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, layerPath)
		}
	}

	// Update tracked state.
	latestHash := manifest.LatestHash()
	latestSnapPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(latestSnap.Hash))
	d.mu.Lock()
	if tv, ok := d.tracked[volumeID]; ok {
		tv.lastLayerHash = latestHash
		tv.lastSnapPath = latestSnapPath
		if latestConsolHash != "" {
			consolPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(latestConsolHash))
			tv.lastConsolidationPath = consolPath
			tv.lastConsolidationHash = latestConsolHash
		}
	}
	d.mu.Unlock()

	klog.Infof("Restored volume %s from CAS (%d snapshots in chain)", volumeID, len(chain))
	return nil
}

// RestoreToSnapshot restores a volume to a specific snapshot hash. The current
// state is saved as a "pre-restore" layer first as an undo point. The
// incremental chain is replayed from the nearest consolidation/template.
func (d *Daemon) RestoreToSnapshot(ctx context.Context, volumeID, targetHash string) error {
	// Per-volume lock serializes with concurrent SyncVolume/CreateSnapshot.
	vl := d.volumeLock(volumeID)
	vl.Lock()
	defer vl.Unlock()

	// Save current state as an undo point before restoring.
	d.mu.Lock()
	tv, exists := d.tracked[volumeID]
	if !exists {
		d.mu.Unlock()
		return fmt.Errorf("volume %q is not tracked for sync", volumeID)
	}
	tvCopy := *tv
	d.mu.Unlock()

	if hash, newSnapPath, syncErr := d.syncOne(ctx, &tvCopy, "checkpoint", "pre-restore"); syncErr != nil {
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

	volumePath := fmt.Sprintf("volumes/%s", volumeID)

	// Restore to base template.
	if targetHash == manifest.Base {
		if manifest.TemplateName == "" {
			return fmt.Errorf("target hash %s is template base but no template name set", targetHash)
		}
		if err := d.tmplMgr.EnsureTemplateByHash(ctx, manifest.TemplateName, manifest.Base); err != nil {
			return fmt.Errorf("ensure base template: %w", err)
		}
		tmplPath := fmt.Sprintf("templates/%s", manifest.TemplateName)
		if d.btrfs.SubvolumeExists(ctx, volumePath) {
			_ = d.btrfs.DeleteSubvolume(ctx, volumePath)
		}
		if err := d.btrfs.SnapshotSubvolume(ctx, tmplPath, volumePath, false); err != nil {
			return fmt.Errorf("snapshot template to volume: %w", err)
		}
		manifest.TruncateAfter(targetHash)
		_ = d.cas.PutManifest(ctx, manifest)

		d.mu.Lock()
		if tv, ok := d.tracked[volumeID]; ok {
			tv.lastLayerHash = targetHash
			tv.lastSnapPath = tmplPath
		}
		d.mu.Unlock()

		klog.Infof("Restored volume %s to template base", volumeID)
		return nil
	}

	// Find target index in manifest.
	targetIdx := -1
	for i := range manifest.Snapshots {
		if manifest.Snapshots[i].Hash == targetHash {
			targetIdx = i
			break
		}
	}
	if targetIdx < 0 {
		return fmt.Errorf("target hash %s not found in manifest for volume %s", targetHash, volumeID)
	}

	// Ensure template exists for chain replay.
	if manifest.Base != "" && manifest.TemplateName != "" {
		if err := d.tmplMgr.EnsureTemplateByHash(ctx, manifest.TemplateName, manifest.Base); err != nil {
			return fmt.Errorf("ensure base template: %w", err)
		}
	}

	// Build and replay the restore chain.
	chain := manifest.BuildRestoreChain(targetIdx)
	var lastReceivedPath string
	for _, idx := range chain {
		snap := manifest.Snapshots[idx]
		layerPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(snap.Hash))
		if !d.btrfs.SubvolumeExists(ctx, layerPath) {
			if err := d.downloadLayer(ctx, volumeID, snap.Hash, layerPath); err != nil {
				return fmt.Errorf("restore snapshot %d (%s): %w", idx, cas.ShortHash(snap.Hash), err)
			}
		}
		lastReceivedPath = layerPath
	}

	if lastReceivedPath == "" {
		return fmt.Errorf("empty restore chain for volume %s target %s", volumeID, targetHash)
	}

	// Replace volume with writable snapshot of the target.
	if d.btrfs.SubvolumeExists(ctx, volumePath) {
		_ = d.btrfs.DeleteSubvolume(ctx, volumePath)
	}
	if err := d.btrfs.SnapshotSubvolume(ctx, lastReceivedPath, volumePath, false); err != nil {
		return fmt.Errorf("snapshot target to volume: %w", err)
	}

	// Truncate manifest to target.
	manifest.TruncateAfter(targetHash)
	if err := d.cas.PutManifest(ctx, manifest); err != nil {
		return fmt.Errorf("save truncated manifest: %w", err)
	}

	// Clean up intermediate layers (keep target + latest consolidation).
	latestConsolHash := ""
	if consol := manifest.LatestConsolidation(); consol != nil {
		latestConsolHash = consol.Hash
	}
	for _, idx := range chain {
		snap := manifest.Snapshots[idx]
		if snap.Hash == targetHash || snap.Hash == latestConsolHash {
			continue
		}
		layerPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(snap.Hash))
		if d.btrfs.SubvolumeExists(ctx, layerPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, layerPath)
		}
	}

	// Update tracked state.
	d.mu.Lock()
	if tv, ok := d.tracked[volumeID]; ok {
		tv.lastLayerHash = targetHash
		tv.lastSnapPath = lastReceivedPath
		if latestConsolHash != "" {
			consolPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(latestConsolHash))
			tv.lastConsolidationPath = consolPath
			tv.lastConsolidationHash = latestConsolHash
		}
	}
	d.mu.Unlock()

	klog.Infof("Restored volume %s to snapshot %s (%d in chain)", volumeID, cas.ShortHash(targetHash), len(chain))
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
			if errors.Is(err, errVolumeGone) {
				// Volume was deleted externally (e.g. Hub DeleteVolumeFromNode
				// on a different node, or manual btrfs subvolume delete).
				// Untrack it so we stop retrying every cycle. The per-volume
				// lock is already released, so UntrackVolume can acquire it.
				klog.Warningf("Volume %s subvolume gone — auto-untracking", item.tv.volumeID)
				d.UntrackVolume(item.tv.volumeID)
				continue
			}
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
			tv.lastConsolidationPath = item.tv.lastConsolidationPath
			tv.lastConsolidationHash = item.tv.lastConsolidationHash
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
//  2. Determine parent: previous snapshot (incremental) or previous
//     consolidation/template (consolidation point)
//  3. btrfs send → cas.PutBlob() → get hash
//  4. Update manifest with new snapshot, run consolidation retention
//  5. Rotate layer snapshots on disk
func (d *Daemon) syncOne(ctx context.Context, tv *trackedVolume, role, label string) (string, string, error) {
	if d.cas == nil {
		return "", "", fmt.Errorf("CAS store not configured")
	}
	start := time.Now()

	volumePath := fmt.Sprintf("volumes/%s", tv.volumeID)
	pendingPath := fmt.Sprintf("layers/%s@pending", tv.volumeID)

	if !d.btrfs.SubvolumeExists(ctx, volumePath) {
		return "", "", fmt.Errorf("%w: %s", errVolumeGone, volumePath)
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

	// 2. Check manifest to decide if this snapshot should be a consolidation.
	manifest, manErr := d.cas.GetManifest(ctx, tv.volumeID)
	if manErr != nil {
		manifest = &cas.Manifest{
			VolumeID:     tv.volumeID,
			Base:         tv.templateHash,
			TemplateName: tv.templateName,
		}
	}

	isConsolidation := false
	if d.consolidationInterval > 0 {
		sinceLastConsol := manifest.SnapshotsSinceLastConsolidation()
		// The snapshot we're about to create will be the (sinceLastConsol+1)th.
		// Trigger consolidation when that count reaches the interval.
		if sinceLastConsol+1 >= d.consolidationInterval {
			isConsolidation = true
		}
	}

	// 2b. Determine parent for btrfs send.
	var parentPath string
	var parentHash string

	if isConsolidation {
		// Consolidation: diff from previous consolidation snapshot (or template).
		if tv.lastConsolidationPath != "" && d.btrfs.SubvolumeExists(ctx, tv.lastConsolidationPath) {
			parentPath = tv.lastConsolidationPath
			parentHash = tv.lastConsolidationHash
		} else if tv.templateName != "" {
			tmplPath := fmt.Sprintf("templates/%s", tv.templateName)
			if d.btrfs.SubvolumeExists(ctx, tmplPath) {
				parentPath = tmplPath
			}
			parentHash = tv.templateHash
		}
	} else {
		// Incremental: diff from previous snapshot.
		if tv.lastSnapPath != "" && d.btrfs.SubvolumeExists(ctx, tv.lastSnapPath) {
			parentPath = tv.lastSnapPath
			parentHash = tv.lastLayerHash
		} else if tv.templateName != "" {
			// First sync or previous snapshot lost — fall back to template.
			tmplPath := fmt.Sprintf("templates/%s", tv.templateName)
			if d.btrfs.SubvolumeExists(ctx, tmplPath) {
				parentPath = tmplPath
			}
			parentHash = tv.templateHash
		}
	}
	// If no parent found, parentPath="" → full send (no template, no previous).
	if parentHash == "" {
		parentHash = tv.templateHash // may also be "" for template-less volumes
	}

	// 3. btrfs send → CAS PutBlob with stall detection.
	sendReader, err := d.btrfs.Send(ctx, pendingPath, parentPath)
	if err != nil {
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		return "", "", fmt.Errorf("btrfs send: %w", err)
	}

	stallCtx, stallCancel := context.WithCancelCause(ctx)
	stallR := ioutil.NewStallReader(sendReader, stallCtx, stallCancel, ioutil.StallTimeout)

	hash, err := d.cas.PutBlob(stallCtx, stallR)
	stallR.Close()
	if err != nil {
		if cause := context.Cause(stallCtx); cause != nil {
			err = fmt.Errorf("%w (cause: %v)", err, cause)
		}
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		return "", "", fmt.Errorf("put blob: %w", err)
	}

	// 4. Update manifest with new snapshot.
	manifest.AppendSnapshot(cas.Snapshot{
		Hash:          hash,
		Parent:        parentHash,
		Role:          role,
		Label:         label,
		Consolidation: isConsolidation,
		TS:            time.Now().UTC().Format(time.RFC3339),
	})

	// Prune old consolidation blobs if retention is configured.
	if isConsolidation && d.consolidationRetention > 0 {
		pruned := manifest.PruneConsolidations(d.consolidationRetention)
		for _, prunedHash := range pruned {
			if delErr := d.cas.DeleteBlob(ctx, prunedHash); delErr != nil {
				klog.Warningf("Failed to prune consolidation blob %s: %v", cas.ShortHash(prunedHash), delErr)
			} else {
				klog.V(2).Infof("Pruned consolidation blob %s for volume %s", cas.ShortHash(prunedHash), tv.volumeID)
			}
		}
	}

	if err := d.cas.PutManifest(ctx, manifest); err != nil {
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		return "", "", fmt.Errorf("put manifest: %w", err)
	}

	// 5. Rotate layer snapshots on disk.
	shortHash := cas.ShortHash(hash)
	var newSnapPath string

	if isConsolidation {
		newSnapPath = fmt.Sprintf("layers/%s@consol-%s", tv.volumeID, shortHash)

		// Delete old incremental if it's different from the consolidation.
		if tv.lastSnapPath != "" && tv.lastSnapPath != tv.lastConsolidationPath &&
			d.btrfs.SubvolumeExists(ctx, tv.lastSnapPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, tv.lastSnapPath)
		}
		// Delete old consolidation snapshot.
		if tv.lastConsolidationPath != "" && d.btrfs.SubvolumeExists(ctx, tv.lastConsolidationPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, tv.lastConsolidationPath)
		}

		if d.btrfs.SubvolumeExists(ctx, newSnapPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, newSnapPath)
		}
		if err := d.btrfs.RenameSubvolume(ctx, pendingPath, newSnapPath); err != nil {
			klog.Warningf("Failed to rename pending to %s: %v", newSnapPath, err)
			newSnapPath = pendingPath
		}
		tv.lastConsolidationPath = newSnapPath
		tv.lastConsolidationHash = hash
	} else {
		newSnapPath = fmt.Sprintf("layers/%s@%s", tv.volumeID, shortHash)

		// Delete old incremental, but NOT the consolidation snapshot.
		if tv.lastSnapPath != "" && tv.lastSnapPath != tv.lastConsolidationPath &&
			d.btrfs.SubvolumeExists(ctx, tv.lastSnapPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, tv.lastSnapPath)
		}

		if d.btrfs.SubvolumeExists(ctx, newSnapPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, newSnapPath)
		}
		if err := d.btrfs.RenameSubvolume(ctx, pendingPath, newSnapPath); err != nil {
			klog.Warningf("Failed to rename pending to %s: %v", newSnapPath, err)
			newSnapPath = pendingPath
		}
	}

	metrics.SyncDuration.Observe(time.Since(start).Seconds())
	klog.V(2).Infof("CAS synced volume %s → blob %s (role=%s, consolidation=%v)",
		tv.volumeID, cas.ShortHash(hash), role, isConsolidation)

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
