package sync

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
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

// ---------------------------------------------------------------------------
// Per-volume actor model
// ---------------------------------------------------------------------------

// opType distinguishes the kind of work submitted to a volume actor.
type opType int

const (
	opSync            opType = iota // background periodic sync (from syncAll)
	opSyncUser                      // user-initiated sync (SyncVolume RPC)
	opCreateSnapshot                // CreateSnapshot RPC
	opRestoreVolume                 // RestoreVolume RPC
	opRestoreToSnapshot             // RestoreToSnapshot RPC
	opUntrack                       // UntrackVolume lifecycle event
	opDrain                         // DrainAll final sync
	opSendVolumeTo                  // peer transfer (sync + snapshot + send)
	opNoop                          // no-op for testing/barrier
)

// opPriority controls queue ordering inside the actor.
type opPriority int

const (
	priorityUser       opPriority = iota // user-initiated ops
	priorityDrain                        // drain (above background, below user in buffer)
	priorityBackground                   // periodic syncAll
)

// opRequest is a unit of work submitted to a volume actor.
type opRequest struct {
	op         opType
	priority   opPriority
	ctx        context.Context
	label      string         // for opCreateSnapshot
	targetHash string         // for opRestoreToSnapshot
	targetAddr string         // for opSendVolumeTo
	resultCh   chan<- opResult // actor sends exactly once
}

// opResult is the outcome of a single operation.
type opResult struct {
	hash string // blob hash (meaningful for opCreateSnapshot)
	err  error
}

// volumeActor owns serialized operations for one volume. All operations
// on a volume flow through the actor's channels — the single goroutine
// IS the serialization, replacing per-volume mutexes.
type volumeActor struct {
	volumeID string
	daemon   *Daemon

	// Two channels: user-initiated ops have priority over background syncs.
	userCh chan opRequest // buffered(8): user-initiated + drain ops
	bgCh   chan opRequest // buffered(1): background sync (coalesced)

	// Lifecycle
	stopCh chan struct{} // closed on shutdown
	doneCh chan struct{} // closed when run() exits

	// Dirty tracking — written by MarkDirty (any goroutine), read by syncAll.
	dirty atomic.Bool
}

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
	hub      HubOps // Hub client for manifest writes + volume leases
	tmplMgr  templateOps
	nodeID   string        // node identity for lease holder naming
	interval time.Duration // safety-net periodic sync interval
	mu       sync.Mutex
	tracked  map[string]*trackedVolume
	actors   map[string]*volumeActor // per-volume actor goroutines
	discoverCycle atomic.Int32               // counts syncAll cycles for periodic discovery
	stopCh   chan struct{}
	wg       sync.WaitGroup

	// SendVolumeFn is the callback for peer transfer networking. Set by the
	// nodeops server after construction. The daemon handles sync + snapshot
	// serialization; this function handles the actual gRPC streaming send.
	// Signature: func(ctx, snapshotPath, volumeID, targetAddr) error
	sendVolumeFn func(ctx context.Context, snapPath, volumeID, targetAddr string) error

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

	// Hub is the HubOps implementation for manifest writes and volume leases.
	// In node mode: volumehub.NewHubClient (gRPC to Hub pod).
	// In all mode: NewLocalHubOps (direct CAS writes, same process).
	// Created by the driver, not the daemon.
	Hub HubOps

	// NodeID identifies this node for lease holder naming. Typically the
	// Kubernetes node name. Used to generate lease holders like
	// "{nodeID}:{operation}:{nonce}".
	NodeID string
}

// DefaultDaemonConfig returns sensible defaults for production.
func DefaultDaemonConfig() DaemonConfig {
	return DaemonConfig{
		SafetyInterval:         5 * time.Minute,
		ConsolidationInterval:  10,
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
		nodeID:                 cfg.NodeID,
		tracked:                make(map[string]*trackedVolume),
		actors:                 make(map[string]*volumeActor),
		stopCh:                 make(chan struct{}),
	}
	if bm != nil {
		d.btrfs = bm
	}
	if casStore != nil {
		d.cas = casStore
	}
	if cfg.Hub != nil {
		d.hub = cfg.Hub
	}
	if tmplMgr != nil {
		d.tmplMgr = tmplMgr
	}
	return d
}

// newDaemonWithInterfaces creates a Daemon with pre-built interface
// implementations. Used by tests to inject fakes.
func newDaemonWithInterfaces(b btrfsOps, c casOps, h HubOps, t templateOps, interval time.Duration) *Daemon {
	return &Daemon{
		btrfs:                  b,
		cas:                    c,
		hub:                    h,
		tmplMgr:                t,
		interval:               interval,
		consolidationInterval:  50,
		consolidationRetention: 3,
		tracked:                make(map[string]*trackedVolume),
		actors:                 make(map[string]*volumeActor),
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
		templateName      string
		templateHash      string
		latestHash        string // hash of latest snapshot (for lastLayerHash recovery)
		latestConsolHash  string // hash of latest consolidation snapshot (empty if none)
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
					info := manifestInfo{
						templateName: m.TemplateName,
						templateHash: m.Base,
						latestHash:   m.LatestHash(),
					}
					if consol := m.LatestConsolidation(); consol != nil {
						info.latestConsolHash = consol.Hash
					}
					mu.Lock()
					manifestMap[vid] = info
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
		if d.hub != nil {
			if err := d.hub.DeleteTombstone(cleanupCtx, vid); err != nil {
				klog.Warningf("discoverVolumes: failed to remove tombstone for %s: %v", vid, err)
			}
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

		d.mu.Lock()
		if tv, ok := d.tracked[volID]; ok {
			// Recover lastLayerHash from manifest HEAD. Without this,
			// syncOne records Parent="" despite using an on-disk parent.
			if mi.latestHash != "" && tv.lastLayerHash == "" {
				tv.lastLayerHash = mi.latestHash
			}
			// Recover lastSnapPath from on-disk layer (always, not just clean).
			if hasSnap && tv.lastSnapPath == "" {
				tv.lastSnapPath = snapPath
			}
			if !isDirty {
				tv.dirty = false
				clean++
			} else {
				dirty++
			}
			// Recover consolidation state from manifest + disk.
			if mi.latestConsolHash != "" && tv.lastConsolidationHash == "" {
				tv.lastConsolidationHash = mi.latestConsolHash
				consolShort := cas.ShortHash(mi.latestConsolHash)
				consolPath := fmt.Sprintf("layers/%s@consol-%s", volID, consolShort)
				consolPathAlt := fmt.Sprintf("layers/%s@%s", volID, consolShort)
				if d.btrfs.SubvolumeExists(ctx, consolPath) {
					tv.lastConsolidationPath = consolPath
				} else if d.btrfs.SubvolumeExists(ctx, consolPathAlt) {
					tv.lastConsolidationPath = consolPathAlt
				}
			}
		}
		d.mu.Unlock()
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

// Stop signals the daemon to stop and waits for the sync loop and all
// volume actors to finish.
func (d *Daemon) Stop() {
	select {
	case <-d.stopCh:
	default:
		close(d.stopCh)
	}

	// Stop all actors.
	d.mu.Lock()
	actors := make([]*volumeActor, 0, len(d.actors))
	for _, a := range d.actors {
		actors = append(actors, a)
	}
	d.mu.Unlock()

	for _, a := range actors {
		select {
		case <-a.stopCh:
		default:
			close(a.stopCh)
		}
	}
	for _, a := range actors {
		<-a.doneCh
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
	d.discoverVolumes(ctx)

	d.mu.Lock()
	var dirtyActors []*volumeActor
	skipped := 0
	for vid, actor := range d.actors {
		if actor.dirty.Load() {
			dirtyActors = append(dirtyActors, actor)
		} else {
			// Also check canonical dirty flag in tracked state.
			if tv, ok := d.tracked[vid]; ok && tv.dirty {
				dirtyActors = append(dirtyActors, actor)
			} else {
				skipped++
			}
		}
	}
	total := len(d.actors)
	d.mu.Unlock()

	klog.Infof("Drain: %d dirty volumes to sync in parallel (max 3), %d clean (skipped), %d total",
		len(dirtyActors), skipped, total)

	if ctx.Err() != nil {
		return ctx.Err()
	}

	// Submit drain ops to all dirty actors via errgroup.
	g, gctx := errgroup.WithContext(ctx)
	g.SetLimit(3) // concurrency cap
	var synced atomic.Int32

	for _, actor := range dirtyActors {
		actor := actor
		g.Go(func() error {
			resultCh := make(chan opResult, 1)
			req := opRequest{
				op:       opDrain,
				priority: priorityDrain,
				ctx:      gctx,
				resultCh: resultCh,
			}
			select {
			case actor.userCh <- req:
			case <-gctx.Done():
				return gctx.Err()
			}
			select {
			case res := <-resultCh:
				if res.err != nil {
					if gctx.Err() != nil {
						return gctx.Err()
					}
					klog.Errorf("Drain: failed to sync %s: %v", actor.volumeID, res.err)
					return nil // non-cancel error: continue draining others
				}
				// Remove from tracked map but KEEP the layer snapshot on disk.
				d.mu.Lock()
				delete(d.tracked, actor.volumeID)
				d.mu.Unlock()
				synced.Add(1)
				return nil
			case <-gctx.Done():
				return gctx.Err()
			}
		})
	}

	err := g.Wait()
	klog.Infof("Drain: synced %d/%d dirty volumes (syncer remains active for late RPCs)",
		synced.Load(), len(dirtyActors))

	if ctx.Err() != nil {
		return ctx.Err()
	}
	return err
}

// TrackVolume registers a volume for periodic CAS sync with its template context.
// Creates a per-volume actor goroutine that serializes all operations.
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

	actor := &volumeActor{
		volumeID: volumeID,
		daemon:   d,
		userCh:   make(chan opRequest, 8),
		bgCh:     make(chan opRequest, 1),
		stopCh:   make(chan struct{}),
		doneCh:   make(chan struct{}),
	}
	actor.dirty.Store(true)
	d.actors[volumeID] = actor
	go actor.run()

	klog.V(2).Infof("Tracking volume %s for CAS sync (template=%s, base=%s)",
		volumeID, templateName, cas.ShortHash(templateHash))
}

// autoTrackWithManifest ensures a volume is tracked with full state recovery
// from the CAS manifest. This is the correct way to start tracking a volume
// that already has history (e.g., after migration or CSI restart). It recovers:
//   - templateName / templateHash from the manifest
//   - lastLayerHash from manifest HEAD (so syncOne records correct Parent)
//   - lastSnapPath from the on-disk layer matching HEAD
//   - lastConsolidationPath / lastConsolidationHash from manifest
//
// Without this, syncOne records Parent="" in the manifest despite using the
// on-disk layer as btrfs send parent, creating incremental blobs that claim
// to be full sends — breaking all future restores.
func (d *Daemon) autoTrackWithManifest(ctx context.Context, volumeID string) {
	d.mu.Lock()
	if _, exists := d.tracked[volumeID]; exists {
		d.mu.Unlock()
		return // already tracked
	}
	d.mu.Unlock()

	// Fetch manifest from CAS to recover template context and HEAD.
	var templateName, templateHash, latestHash, consolHash, consolPath string
	if d.cas != nil {
		if m, err := d.cas.GetManifest(ctx, volumeID); err == nil {
			templateName = m.TemplateName
			templateHash = m.Base
			latestHash = m.LatestHash()
			if lc := m.LatestConsolidation(); lc != nil {
				consolHash = lc.Hash
				// Check both naming conventions on disk.
				cp := fmt.Sprintf("layers/%s@consol-%s", volumeID, cas.ShortHash(consolHash))
				cpAlt := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(consolHash))
				if d.btrfs.SubvolumeExists(ctx, cp) {
					consolPath = cp
				} else if d.btrfs.SubvolumeExists(ctx, cpAlt) {
					consolPath = cpAlt
				}
			}
		}
	}

	d.TrackVolume(volumeID, templateName, templateHash)

	d.mu.Lock()
	if tv, ok := d.tracked[volumeID]; ok {
		if latestHash != "" {
			tv.lastLayerHash = latestHash
			// Find the layer snapshot on disk matching HEAD.
			snapPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(latestHash))
			if d.btrfs.SubvolumeExists(ctx, snapPath) {
				tv.lastSnapPath = snapPath
			}
		}
		if consolHash != "" {
			tv.lastConsolidationHash = consolHash
			tv.lastConsolidationPath = consolPath
		}
	}
	d.mu.Unlock()

	klog.Infof("autoTrackWithManifest: %s (head=%s, template=%s)",
		volumeID, cas.ShortHash(latestHash), templateName)
}

// MarkDirty flags a tracked volume as needing sync. Safe to call from any
// goroutine; no-op if the volume isn't tracked.
func (d *Daemon) MarkDirty(volumeID string) {
	d.mu.Lock()
	if tv, ok := d.tracked[volumeID]; ok {
		tv.dirty = true
	}
	actor := d.actors[volumeID]
	d.mu.Unlock()
	if actor != nil {
		actor.dirty.Store(true)
	}
}

// UntrackVolume removes a volume from sync tracking and cleans up the last
// layer snapshot if one exists. The untrack operation is submitted to the
// volume's actor to wait for any inflight operations to finish first.
func (d *Daemon) UntrackVolume(volumeID string) {
	d.mu.Lock()
	actor, ok := d.actors[volumeID]
	d.mu.Unlock()
	if !ok {
		// No actor — maybe never tracked or already untracked.
		d.mu.Lock()
		delete(d.tracked, volumeID)
		d.mu.Unlock()
		return
	}

	// Submit untrack op through the actor to wait for inflight ops.
	resultCh := make(chan opResult, 1)
	req := opRequest{
		op:       opUntrack,
		priority: priorityUser,
		ctx:      context.Background(),
		resultCh: resultCh,
	}

	select {
	case actor.userCh <- req:
	case <-actor.stopCh:
		// Already stopping — do inline cleanup.
	}

	// Wait for untrack to complete.
	select {
	case <-resultCh:
	case <-actor.doneCh:
	}

	// Remove actor from map.
	d.mu.Lock()
	delete(d.actors, volumeID)
	d.mu.Unlock()

	klog.V(2).Infof("Untracked volume %s from CAS sync", volumeID)
}

// ---------------------------------------------------------------------------
// Volume actor goroutine and dispatch
// ---------------------------------------------------------------------------

// run is the actor's main loop. It processes operations one at a time,
// always preferring user-initiated ops over background syncs.
func (a *volumeActor) run() {
	defer close(a.doneCh)
	for {
		// Priority drain: always prefer userCh over bgCh.
		select {
		case req := <-a.userCh:
			a.dispatch(req)
			continue
		default:
		}
		// No user ops pending — wait for any event.
		select {
		case req := <-a.userCh:
			a.dispatch(req)
		case req := <-a.bgCh:
			a.dispatch(req)
		case <-a.stopCh:
			a.drainRemaining()
			return
		}
	}
}

// drainRemaining processes any pending user ops before the actor exits.
func (a *volumeActor) drainRemaining() {
	for {
		select {
		case req := <-a.userCh:
			a.dispatch(req)
		default:
			return
		}
	}
}

// dispatch routes an operation to the appropriate handler and sends the result.
func (a *volumeActor) dispatch(req opRequest) {
	// Check if caller already gave up.
	if req.ctx.Err() != nil {
		select {
		case req.resultCh <- opResult{err: req.ctx.Err()}:
		default:
		}
		return
	}

	var result opResult
	switch req.op {
	case opSync:
		result.err = a.doSync(req.ctx, false) // background: fail-fast lease
		// Self-heal: if the subvolume vanished, untrack so we stop retrying
		// every cycle. Spawn a goroutine — UntrackVolume submits an opUntrack
		// to this same actor and would deadlock if invoked synchronously.
		if errors.Is(result.err, errVolumeGone) {
			klog.Infof("background sync: subvolume volumes/%s gone, auto-untracking", a.volumeID)
			go a.daemon.UntrackVolume(a.volumeID)
		}
	case opSyncUser:
		result.err = a.doSync(req.ctx, true) // user: wait for lease
	case opDrain:
		result.err = a.doSync(req.ctx, true) // drain: wait for lease
	case opCreateSnapshot:
		result.hash, result.err = a.doCreateSnapshot(req.ctx, req.label)
	case opRestoreVolume:
		result.err = a.doRestoreVolume(req.ctx)
	case opRestoreToSnapshot:
		result.err = a.doRestoreToSnapshot(req.ctx, req.targetHash)
	case opUntrack:
		result.err = a.doUntrack(req.ctx)
	case opSendVolumeTo:
		result.err = a.doSendVolumeTo(req.ctx, req.targetAddr)
	case opNoop:
		// No-op — used as a barrier to wait for prior ops to complete.
	}

	select {
	case req.resultCh <- result:
	default:
	}
}

// doSync performs a CAS sync within the actor goroutine.
func (a *volumeActor) doSync(ctx context.Context, waitLease bool) error {
	release, err := a.daemon.doAcquireHubLease(ctx, a.volumeID, "sync", waitLease)
	if err != nil {
		return fmt.Errorf("acquire lease: %w", err)
	}
	defer release()

	a.daemon.mu.Lock()
	tv, exists := a.daemon.tracked[a.volumeID]
	if !exists {
		a.daemon.mu.Unlock()
		// Auto-track if volume exists on disk.
		volPath := fmt.Sprintf("volumes/%s", a.volumeID)
		if !a.daemon.btrfs.SubvolumeExists(ctx, volPath) {
			return fmt.Errorf("volume %q is not tracked and subvolume missing", a.volumeID)
		}
		a.daemon.autoTrackWithManifest(ctx, a.volumeID)
		a.daemon.mu.Lock()
		tv = a.daemon.tracked[a.volumeID]
		if tv == nil {
			a.daemon.mu.Unlock()
			return fmt.Errorf("volume %q failed to auto-track", a.volumeID)
		}
	}
	tvCopy := *tv
	a.daemon.mu.Unlock()

	hash, newSnapPath, err := a.daemon.syncOne(ctx, &tvCopy, "sync", "")
	if err != nil {
		return err
	}

	a.daemon.mu.Lock()
	if tv, ok := a.daemon.tracked[a.volumeID]; ok {
		tv.lastLayerHash = hash
		tv.lastSnapPath = newSnapPath
		tv.lastSyncAt = time.Now()
		tv.templateName = tvCopy.templateName
		tv.templateHash = tvCopy.templateHash
		tv.lastConsolidationPath = tvCopy.lastConsolidationPath
		tv.lastConsolidationHash = tvCopy.lastConsolidationHash
		tv.dirty = false
	}
	a.daemon.mu.Unlock()

	a.dirty.Store(false)
	return nil
}

// doCreateSnapshot creates a labeled checkpoint within the actor goroutine.
func (a *volumeActor) doCreateSnapshot(ctx context.Context, label string) (string, error) {
	release, err := a.daemon.doAcquireHubLease(ctx, a.volumeID, "checkpoint", true)
	if err != nil {
		return "", fmt.Errorf("acquire lease: %w", err)
	}
	defer release()

	a.daemon.mu.Lock()
	tv, exists := a.daemon.tracked[a.volumeID]
	if !exists {
		a.daemon.mu.Unlock()
		return "", fmt.Errorf("volume %q is not tracked for sync", a.volumeID)
	}
	tvCopy := *tv
	a.daemon.mu.Unlock()

	hash, newSnapPath, err := a.daemon.syncOne(ctx, &tvCopy, "checkpoint", label)
	if err != nil {
		return "", err
	}

	a.daemon.mu.Lock()
	if tv, ok := a.daemon.tracked[a.volumeID]; ok {
		tv.lastLayerHash = hash
		tv.lastSnapPath = newSnapPath
		tv.lastSyncAt = time.Now()
		tv.templateName = tvCopy.templateName
		tv.templateHash = tvCopy.templateHash
		tv.lastConsolidationPath = tvCopy.lastConsolidationPath
		tv.lastConsolidationHash = tvCopy.lastConsolidationHash
	}
	a.daemon.mu.Unlock()
	return hash, nil
}

// doRestoreVolume restores a volume from CAS within the actor goroutine.
func (a *volumeActor) doRestoreVolume(ctx context.Context) error {
	d := a.daemon
	volumeID := a.volumeID

	if d.cas == nil {
		return fmt.Errorf("CAS store not configured, cannot restore volume %q", volumeID)
	}

	release, err := d.doAcquireHubLease(ctx, volumeID, "restore", true)
	if err != nil {
		return fmt.Errorf("acquire lease: %w", err)
	}
	defer release()

	manifest, err := d.cas.GetManifest(ctx, volumeID)
	if err != nil {
		return fmt.Errorf("get manifest for %s: %w", volumeID, err)
	}

	if manifest.Base != "" && manifest.TemplateName != "" {
		if err := d.tmplMgr.EnsureTemplateByHash(ctx, manifest.TemplateName, manifest.Base); err != nil {
			return fmt.Errorf("ensure base template %s: %w", manifest.TemplateName, err)
		}
	}

	volumePath := fmt.Sprintf("volumes/%s", volumeID)

	if len(manifest.Snapshots) == 0 {
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

	chain := manifest.BuildRestoreChain(manifest.Head)

	prefetched, pfErr := d.prefetchBlobs(ctx, manifest, chain, volumeID)
	if pfErr != nil {
		return fmt.Errorf("prefetch blobs for %s: %w", volumeID, pfErr)
	}
	defer cleanupPrefetch(prefetched)

	var lastReceivedPath string
	for _, snapHash := range chain {
		snap := manifest.Snapshots[snapHash]
		layerPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(snapHash))
		if !d.btrfs.SubvolumeExists(ctx, layerPath) {
			parentPath, pErr := d.ensureParentLayer(ctx, manifest, chain, snapHash, volumeID)
			if pErr != nil {
				return fmt.Errorf("ensure parent for snapshot %s: %w", cas.ShortHash(snapHash), pErr)
			}
			if localPath, ok := prefetched[snap.Hash]; ok {
				if err := d.downloadLayerFromLocal(ctx, volumeID, snap.Hash, layerPath, parentPath, localPath); err != nil {
					return fmt.Errorf("restore snapshot %s: %w", cas.ShortHash(snapHash), err)
				}
			} else {
				if err := d.downloadLayerWithRetry(ctx, volumeID, snap.Hash, layerPath, parentPath); err != nil {
					return fmt.Errorf("restore snapshot %s: %w", cas.ShortHash(snapHash), err)
				}
			}
		}
		lastReceivedPath = layerPath
	}

	if lastReceivedPath == "" {
		return fmt.Errorf("empty restore chain for volume %s", volumeID)
	}

	if d.btrfs.SubvolumeExists(ctx, volumePath) {
		if err := d.btrfs.DeleteSubvolume(ctx, volumePath); err != nil {
			return fmt.Errorf("delete existing volume %s: %w", volumeID, err)
		}
	}
	if err := d.btrfs.SnapshotSubvolume(ctx, lastReceivedPath, volumePath, false); err != nil {
		return fmt.Errorf("snapshot to volume %s: %w", volumeID, err)
	}

	latestSnap := manifest.Snapshots[manifest.Head]
	latestConsolHash := ""
	if consol := manifest.LatestConsolidation(); consol != nil {
		latestConsolHash = consol.Hash
	}

	d.TrackVolume(volumeID, manifest.TemplateName, manifest.Base)

	latestHash := manifest.LatestHash()
	latestSnapPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(latestSnap.Hash))
	d.mu.Lock()
	if tv, ok := d.tracked[volumeID]; ok {
		tv.lastLayerHash = latestHash
		tv.lastSnapPath = latestSnapPath
		tv.dirty = false
		if latestConsolHash != "" {
			consolPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(latestConsolHash))
			tv.lastConsolidationPath = consolPath
			tv.lastConsolidationHash = latestConsolHash
		}
	}
	d.mu.Unlock()

	a.dirty.Store(false)
	klog.Infof("Restored volume %s from CAS (%d snapshots in chain)", volumeID, len(chain))
	return nil
}

// doRestoreToSnapshot restores a volume to a specific snapshot within the actor.
func (a *volumeActor) doRestoreToSnapshot(ctx context.Context, targetHash string) error {
	d := a.daemon
	volumeID := a.volumeID

	release, err := d.doAcquireHubLease(ctx, volumeID, "restore-snapshot", true)
	if err != nil {
		return fmt.Errorf("acquire lease: %w", err)
	}
	defer release()

	// Save current state as an undo point before restoring.
	d.mu.Lock()
	tv, exists := d.tracked[volumeID]
	if !exists {
		d.mu.Unlock()
		volPath := fmt.Sprintf("volumes/%s", volumeID)
		if !d.btrfs.SubvolumeExists(ctx, volPath) {
			return fmt.Errorf("volume %q is not tracked and subvolume missing", volumeID)
		}
		d.autoTrackWithManifest(ctx, volumeID)
		d.mu.Lock()
		tv = d.tracked[volumeID]
		if tv == nil {
			d.mu.Unlock()
			return fmt.Errorf("volume %q failed to auto-track", volumeID)
		}
	}
	tvCopy := *tv
	d.mu.Unlock()

	needUndo := tvCopy.dirty
	if !needUndo && tvCopy.lastSnapPath != "" {
		volGen, volErr := d.btrfs.GetGeneration(ctx, "volumes/"+volumeID)
		snapGen, snapErr := d.btrfs.GetGeneration(ctx, tvCopy.lastSnapPath)
		if volErr == nil && snapErr == nil && volGen > snapGen {
			needUndo = true
		}
	}

	if needUndo {
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
	} else {
		klog.V(2).Infof("RestoreToSnapshot: skipping undo point for %s (volume clean)", volumeID)
	}

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
		branchName := ""
		if manifest.Head != "" && manifest.Head != targetHash {
			branchName = fmt.Sprintf("pre-restore-%s", time.Now().UTC().Format("20060102-150405"))
		}
		if d.hub != nil {
			if _, _, err := d.hub.SetManifestHead(ctx, volumeID, targetHash, branchName); err != nil {
				klog.Warningf("RestoreToSnapshot: hub SetManifestHead: %v", err)
			}
		}
		d.mu.Lock()
		if tv, ok := d.tracked[volumeID]; ok {
			tv.lastLayerHash = targetHash
			tv.lastSnapPath = tmplPath
		}
		d.mu.Unlock()
		klog.Infof("Restored volume %s to template base", volumeID)
		return nil
	}

	if _, ok := manifest.Snapshots[targetHash]; !ok {
		return fmt.Errorf("target hash %s not found in manifest for volume %s", targetHash, volumeID)
	}

	if manifest.Base != "" && manifest.TemplateName != "" {
		if err := d.tmplMgr.EnsureTemplateByHash(ctx, manifest.TemplateName, manifest.Base); err != nil {
			return fmt.Errorf("ensure base template: %w", err)
		}
	}

	chain := manifest.BuildRestoreChain(targetHash)

	prefetched, pfErr := d.prefetchBlobs(ctx, manifest, chain, volumeID)
	if pfErr != nil {
		return fmt.Errorf("prefetch blobs for %s: %w", volumeID, pfErr)
	}
	defer cleanupPrefetch(prefetched)

	var lastReceivedPath string
	for _, snapHash := range chain {
		snap := manifest.Snapshots[snapHash]
		layerPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(snapHash))
		if !d.btrfs.SubvolumeExists(ctx, layerPath) {
			parentPath, pErr := d.ensureParentLayer(ctx, manifest, chain, snapHash, volumeID)
			if pErr != nil {
				return fmt.Errorf("ensure parent for snapshot %s: %w", cas.ShortHash(snapHash), pErr)
			}
			if localPath, ok := prefetched[snap.Hash]; ok {
				if err := d.downloadLayerFromLocal(ctx, volumeID, snap.Hash, layerPath, parentPath, localPath); err != nil {
					return fmt.Errorf("restore snapshot %s: %w", cas.ShortHash(snapHash), err)
				}
			} else {
				if err := d.downloadLayerWithRetry(ctx, volumeID, snap.Hash, layerPath, parentPath); err != nil {
					return fmt.Errorf("restore snapshot %s: %w", cas.ShortHash(snapHash), err)
				}
			}
		}
		lastReceivedPath = layerPath
	}

	if lastReceivedPath == "" {
		return fmt.Errorf("empty restore chain for volume %s target %s", volumeID, targetHash)
	}

	if d.btrfs.SubvolumeExists(ctx, volumePath) {
		_ = d.btrfs.DeleteSubvolume(ctx, volumePath)
	}
	if err := d.btrfs.SnapshotSubvolume(ctx, lastReceivedPath, volumePath, false); err != nil {
		return fmt.Errorf("snapshot target to volume: %w", err)
	}

	branchName := ""
	if manifest.Head != "" && manifest.Head != targetHash {
		branchName = fmt.Sprintf("pre-restore-%s", time.Now().UTC().Format("20060102-150405"))
	}
	if d.hub != nil {
		if _, _, err := d.hub.SetManifestHead(ctx, volumeID, targetHash, branchName); err != nil {
			return fmt.Errorf("hub set manifest head: %w", err)
		}
	}

	latestConsolHash := ""
	if consol := manifest.LatestConsolidation(); consol != nil {
		latestConsolHash = consol.Hash
	}

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

// doUntrack removes the volume from tracking and cleans up layer snapshots.
func (a *volumeActor) doUntrack(ctx context.Context) error {
	a.daemon.mu.Lock()
	tv, exists := a.daemon.tracked[a.volumeID]
	if !exists {
		a.daemon.mu.Unlock()
		return nil
	}
	lastSnapPath := tv.lastSnapPath
	delete(a.daemon.tracked, a.volumeID)
	a.daemon.mu.Unlock()

	if lastSnapPath != "" {
		cleanCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
		defer cancel()
		if a.daemon.btrfs.SubvolumeExists(cleanCtx, lastSnapPath) {
			if err := a.daemon.btrfs.DeleteSubvolume(cleanCtx, lastSnapPath); err != nil {
				klog.Warningf("Failed to cleanup layer snapshot %s: %v", lastSnapPath, err)
			}
		}
	}

	// Signal actor to stop after this op completes.
	select {
	case <-a.stopCh:
	default:
		close(a.stopCh)
	}
	return nil
}

// doSendVolumeTo syncs and transfers a volume within the actor goroutine.
// The actor serializes this with all other operations (including FileOps
// dirty-mark checks via syncOne). The flow:
//  1. syncOne() — captures ALL current writes into a CAS snapshot + layer
//  2. Snapshot the live volume for transfer (after sync, this is consistent)
//  3. btrfs send the snapshot to the target via the sendFn callback
//
// Because the actor processes ops sequentially, no FileOps writes can land
// between the sync and the transfer snapshot — they queue behind this op.
// The sendFn callback is provided by the nodeops server (which has the gRPC
// streaming infrastructure to send to the target).
func (a *volumeActor) doSendVolumeTo(ctx context.Context, targetAddr string) error {
	d := a.daemon
	volumeID := a.volumeID

	// Step 1: Sync to CAS first (captures latest FileOps writes).
	// This goes through the normal sync path — hub lease, syncOne, etc.
	release, err := d.doAcquireHubLease(ctx, volumeID, "peer-transfer", true)
	if err != nil {
		return fmt.Errorf("acquire lease for peer transfer: %w", err)
	}
	defer release()

	d.mu.Lock()
	tv, exists := d.tracked[volumeID]
	if !exists {
		d.mu.Unlock()
		volPath := fmt.Sprintf("volumes/%s", volumeID)
		if !d.btrfs.SubvolumeExists(ctx, volPath) {
			return fmt.Errorf("volume %q not tracked and subvolume missing", volumeID)
		}
		d.autoTrackWithManifest(ctx, volumeID)
		d.mu.Lock()
		tv = d.tracked[volumeID]
		if tv == nil {
			d.mu.Unlock()
			return fmt.Errorf("volume %q failed to auto-track", volumeID)
		}
	}
	tvCopy := *tv
	d.mu.Unlock()

	if tvCopy.dirty {
		hash, newSnapPath, syncErr := d.syncOne(ctx, &tvCopy, "sync", "")
		if syncErr != nil {
			klog.Warningf("doSendVolumeTo: pre-transfer sync failed for %s: %v (continuing with current state)", volumeID, syncErr)
		} else {
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
			a.dirty.Store(false)
		}
	}

	// Step 2: Snapshot the live volume for transfer. At this point the
	// actor is holding the operation slot — no other sync/snapshot/restore
	// can run, and any FileOps writes that landed after our sync will be
	// captured in this snapshot.
	volumePath := fmt.Sprintf("volumes/%s", volumeID)
	snapPath := fmt.Sprintf("snapshots/%s@transfer", volumeID)

	if d.btrfs.SubvolumeExists(ctx, snapPath) {
		_ = d.btrfs.DeleteSubvolume(ctx, snapPath)
	}
	if err := d.btrfs.SnapshotSubvolume(ctx, volumePath, snapPath, true); err != nil {
		return fmt.Errorf("snapshot for transfer: %w", err)
	}
	defer func() {
		_ = d.btrfs.DeleteSubvolume(context.Background(), snapPath)
	}()

	// Step 3: Send to target. We call sendVolumeFn which is set by the
	// nodeops server — it has the gRPC streaming infrastructure.
	if d.sendVolumeFn == nil {
		return fmt.Errorf("sendVolumeFn not configured — cannot peer transfer")
	}
	if err := d.sendVolumeFn(ctx, snapPath, volumeID, targetAddr); err != nil {
		return fmt.Errorf("send volume to %s: %w", targetAddr, err)
	}

	klog.Infof("SendVolumeTo (via actor): volume %s sent to %s", volumeID, targetAddr)
	return nil
}

// ---------------------------------------------------------------------------
// Daemon submit helpers
// ---------------------------------------------------------------------------

// submit sends an op to the volume actor and blocks until completion or ctx cancellation.
type submitOpts struct {
	label      string
	targetHash string
	targetAddr string
}

func (d *Daemon) submit(ctx context.Context, volumeID string, op opType, prio opPriority, opts submitOpts) (string, error) {
	d.mu.Lock()
	actor, ok := d.actors[volumeID]
	d.mu.Unlock()
	if !ok {
		return "", fmt.Errorf("volume %q has no actor (not tracked)", volumeID)
	}

	resultCh := make(chan opResult, 1)
	req := opRequest{
		op:         op,
		priority:   prio,
		ctx:        ctx,
		label:      opts.label,
		targetHash: opts.targetHash,
		targetAddr: opts.targetAddr,
		resultCh:   resultCh,
	}

	ch := actor.userCh
	if prio == priorityBackground {
		ch = actor.bgCh
	}

	select {
	case ch <- req:
	case <-ctx.Done():
		return "", ctx.Err()
	case <-actor.stopCh:
		return "", fmt.Errorf("volume %q actor stopped", volumeID)
	}

	select {
	case res := <-resultCh:
		return res.hash, res.err
	case <-ctx.Done():
		return "", ctx.Err()
	}
}

// submitBackground sends a background sync to the volume actor. Non-blocking:
// if the background channel is already full, the sync is coalesced.
func (d *Daemon) submitBackground(volumeID string) {
	d.mu.Lock()
	actor, ok := d.actors[volumeID]
	d.mu.Unlock()
	if !ok {
		return
	}
	req := opRequest{
		op:       opSync,
		priority: priorityBackground,
		ctx:      context.Background(),
		resultCh: make(chan opResult, 1), // nobody reads — prevents actor block
	}
	select {
	case actor.bgCh <- req: // queued
	default: // coalesced — sync already pending
	}
}

// TrackedVolumeState reports the sync state for a tracked volume.
type TrackedVolumeState struct {
	VolumeID     string `json:"volume_id"`
	TemplateHash string `json:"template_hash,omitempty"`
	LastSyncAt   string `json:"last_sync_at,omitempty"`
	Dirty        bool   `json:"dirty"`
	HeadHash     string `json:"head_hash,omitempty"` // CAS manifest HEAD — last synced layer hash
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
			HeadHash:     tv.lastLayerHash,
		}
		if !tv.lastSyncAt.IsZero() {
			s.LastSyncAt = tv.lastSyncAt.UTC().Format(time.RFC3339)
		}
		states = append(states, s)
	}
	return states
}

// leaseBaseTTL is the initial and renewal TTL for Hub volume leases.
// The actual lease lifetime is unbounded — the renewal goroutine extends
// it every leaseRenewInterval while the operation is running.
const leaseBaseTTL = 30 * time.Second

// leaseRenewInterval is how often the lease renewal goroutine extends the TTL.
const leaseRenewInterval = 10 * time.Second

// leaseRetryInterval is the polling interval when waiting for a held lease
// to become available. Used by doAcquireHubLease with wait=true.
const leaseRetryInterval = 500 * time.Millisecond

func (d *Daemon) doAcquireHubLease(ctx context.Context, volumeID, operation string, wait bool) (func(), error) {
	if d.hub == nil {
		return func() {}, nil
	}

	nodeID := d.nodeID
	if nodeID == "" {
		nodeID = "unknown"
	}
	holder := fmt.Sprintf("%s:%s:%d", nodeID, operation, time.Now().UnixNano())

	acquired, current, err := d.hub.AcquireVolumeLease(ctx, volumeID, holder, leaseBaseTTL)
	if err != nil {
		return nil, fmt.Errorf("lease RPC for %s: %w", volumeID, err)
	}

	// Hub returns (false, "") when the volume is not registered. Retrying can
	// never succeed — bail out immediately so the outer RPC surfaces the real
	// error instead of hanging until the deadline expires.
	if !acquired && current == "" {
		return nil, fmt.Errorf("volume %s is not registered in Hub", volumeID)
	}

	if !acquired && wait {
		// Retry until available or context cancelled. The holder's lease
		// will either be released normally, expire via TTL, or be reaped
		// by the Hub's dead-node detector.
		klog.V(2).Infof("acquireHubLease: volume %s held by %s, waiting (op=%s)", volumeID, current, operation)
		ticker := time.NewTicker(leaseRetryInterval)
		defer ticker.Stop()
		for !acquired {
			select {
			case <-ctx.Done():
				return nil, fmt.Errorf("lease wait for %s cancelled: %w", volumeID, ctx.Err())
			case <-ticker.C:
				acquired, current, err = d.hub.AcquireVolumeLease(ctx, volumeID, holder, leaseBaseTTL)
				if err != nil {
					return nil, fmt.Errorf("lease RPC for %s: %w", volumeID, err)
				}
				if !acquired && current == "" {
					return nil, fmt.Errorf("volume %s is not registered in Hub", volumeID)
				}
			}
		}
	} else if !acquired {
		return nil, fmt.Errorf("volume %s is leased by %s", volumeID, current)
	}

	// Background renewal goroutine — extends lease every 10s.
	renewCtx, renewCancel := context.WithCancel(context.Background())
	go func() {
		ticker := time.NewTicker(leaseRenewInterval)
		defer ticker.Stop()
		for {
			select {
			case <-renewCtx.Done():
				return
			case <-ticker.C:
				renewed, revoked, rErr := d.hub.RenewVolumeLease(renewCtx, volumeID, holder, leaseBaseTTL)
				if rErr != nil || !renewed || revoked {
					return
				}
			}
		}
	}()

	release := func() {
		renewCancel()
		rctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = d.hub.ReleaseVolumeLease(rctx, volumeID, holder)
	}
	return release, nil
}

// SyncVolume performs an immediate sync of a single volume to CAS.
// The operation is submitted to the volume's actor for serialization.
// If the volume isn't tracked yet, the actor's doSync will auto-track it.
func (d *Daemon) SyncVolume(ctx context.Context, volumeID string) error {
	d.mu.Lock()
	_, hasActor := d.actors[volumeID]
	d.mu.Unlock()
	if !hasActor {
		// Volume exists on disk but isn't tracked (e.g. cross-node migration).
		// Auto-track so the actor exists; doSync will do full auto-track from manifest.
		d.TrackVolume(volumeID, "", "")
	}
	_, err := d.submit(ctx, volumeID, opSyncUser, priorityUser, submitOpts{})
	return err
}

// CreateSnapshot creates a labeled snapshot layer and returns the blob hash.
// The operation is submitted to the volume's actor for serialization.
func (d *Daemon) CreateSnapshot(ctx context.Context, volumeID, label string) (string, error) {
	return d.submit(ctx, volumeID, opCreateSnapshot, priorityUser, submitOpts{label: label})
}

// RestoreVolume restores a volume from CAS by replaying the incremental
// snapshot chain. The operation is submitted to the volume's actor.
// If the volume isn't tracked yet, it is auto-tracked first.
func (d *Daemon) RestoreVolume(ctx context.Context, volumeID string) error {
	d.mu.Lock()
	_, hasActor := d.actors[volumeID]
	d.mu.Unlock()
	if !hasActor {
		// Volume not tracked — auto-track so the actor exists.
		d.TrackVolume(volumeID, "", "")
	}
	_, err := d.submit(ctx, volumeID, opRestoreVolume, priorityUser, submitOpts{})
	return err
}

// RestoreToSnapshot restores a volume to a specific snapshot hash.
// The operation is submitted to the volume's actor for serialization.
// If the volume isn't tracked yet, the actor's doRestoreToSnapshot will auto-track it.
func (d *Daemon) RestoreToSnapshot(ctx context.Context, volumeID, targetHash string) error {
	d.mu.Lock()
	_, hasActor := d.actors[volumeID]
	d.mu.Unlock()
	if !hasActor {
		d.TrackVolume(volumeID, "", "")
	}
	_, err := d.submit(ctx, volumeID, opRestoreToSnapshot, priorityUser, submitOpts{targetHash: targetHash})
	return err
}

// SendVolumeTo performs a peer transfer through the volume's actor. The actor
// syncs any dirty data, snapshots the volume, and sends it to the target node.
// Because the operation runs inside the actor, no FileOps writes can interleave
// with the snapshot — preventing data loss during migration.
func (d *Daemon) SendVolumeTo(ctx context.Context, volumeID, targetAddr string) error {
	d.mu.Lock()
	_, hasActor := d.actors[volumeID]
	d.mu.Unlock()
	if !hasActor {
		d.TrackVolume(volumeID, "", "")
	}
	_, err := d.submit(ctx, volumeID, opSendVolumeTo, priorityUser, submitOpts{targetAddr: targetAddr})
	return err
}

// SetSendVolumeFn sets the callback for peer transfer networking. Called by
// the driver after the nodeops server is created to wire the two together.
func (d *Daemon) SetSendVolumeFn(fn func(ctx context.Context, snapPath, volumeID, targetAddr string) error) {
	d.sendVolumeFn = fn
}

// DeleteVolume cleans up the manifest and local layer snapshots for a volume.
// Blob cleanup happens via GC (blobs may be shared across volumes).
func (d *Daemon) DeleteVolume(ctx context.Context, volumeID string) error {
	// Delete manifest via Hub.
	if d.hub != nil {
		if err := d.hub.DeleteVolumeManifest(ctx, volumeID); err != nil {
			klog.Warningf("DeleteVolume: hub delete manifest for %s: %v", volumeID, err)
		}
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

// syncAll iterates over all tracked volumes and submits background syncs
// for dirty ones to their respective actors. Volumes marked clean are
// verified via btrfs generation comparison — if the volume's generation
// advanced past its layer snapshot, it was modified by a process outside
// FileOps (e.g. compute pod) and needs syncing.
func (d *Daemon) syncAll(ctx context.Context) error {
	// Periodic re-discovery: scan disk for untracked volumes every Nth cycle.
	if d.discoverCycle.Add(1) >= int32(discoverInterval) {
		d.discoverCycle.Store(0)
		d.discoverVolumes(ctx)
		d.cleanupStaging(ctx)
	}

	// Collect dirty actors (lock-free read of atomic dirty flag).
	// Also collect clean volumes with layer snapshots for generation check.
	type genCheckInfo struct {
		volumeID     string
		lastSnapPath string
	}
	var dirtyVols []string
	var genChecks []genCheckInfo

	d.mu.Lock()
	for vid, actor := range d.actors {
		if actor.dirty.Load() {
			dirtyVols = append(dirtyVols, vid)
		} else if tv, ok := d.tracked[vid]; ok && tv.lastSnapPath != "" {
			genChecks = append(genChecks, genCheckInfo{vid, tv.lastSnapPath})
		}
	}
	d.mu.Unlock()

	// Generation check for clean volumes — outside the lock since
	// GetGeneration runs a btrfs subprocess (~1ms each).
	// staleVols collects tracked volumes whose subvolume vanished from disk
	// (e.g. cross-node migration left a stale tracked entry behind). Untracked
	// outside the loop to avoid re-entrant locking.
	var staleVols []string
	for _, gc := range genChecks {
		volGen, volErr := d.btrfs.GetGeneration(ctx, "volumes/"+gc.volumeID)
		if volErr != nil {
			// Distinguish "subvolume gone" from transient I/O errors. Only
			// untrack on confirmed absence — SubvolumeExists does its own
			// safe stat() and avoids spamming the log on flakes.
			if !d.btrfs.SubvolumeExists(ctx, "volumes/"+gc.volumeID) {
				staleVols = append(staleVols, gc.volumeID)
			}
			continue
		}
		snapGen, snapErr := d.btrfs.GetGeneration(ctx, gc.lastSnapPath)
		if snapErr == nil && volGen > snapGen {
			klog.V(2).Infof("syncAll: %s promoted to dirty (vol gen %d > snap gen %d, direct write detected)",
				gc.volumeID, volGen, snapGen)
			d.mu.Lock()
			if actor, ok := d.actors[gc.volumeID]; ok {
				actor.dirty.Store(true)
			}
			if tv, ok := d.tracked[gc.volumeID]; ok {
				tv.dirty = true
			}
			d.mu.Unlock()
			dirtyVols = append(dirtyVols, gc.volumeID)
		}
	}

	// Auto-untrack stale entries. Done in a goroutine so syncAll doesn't
	// block on per-actor drain (UntrackVolume submits an op and waits).
	for _, vid := range staleVols {
		klog.Infof("syncAll: subvolume volumes/%s gone from disk, auto-untracking", vid)
		go d.UntrackVolume(vid)
	}

	if len(dirtyVols) == 0 {
		total := len(genChecks)
		if total > 0 {
			klog.V(5).Infof("No dirty volumes to sync (%d clean, skipped)", total)
		} else {
			klog.V(5).Info("No volumes to sync")
		}
		return nil
	}

	klog.V(4).Infof("Starting CAS sync cycle: submitting %d dirty volumes to actors", len(dirtyVols))

	// Submit background sync to each dirty actor. Non-blocking, coalesced.
	for _, vid := range dirtyVols {
		d.submitBackground(vid)
	}

	return nil
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
		} else if tv.lastConsolidationHash != "" && d.cas != nil {
			// Consolidation layer GC'd — recover from CAS.
			recoveredPath := fmt.Sprintf("layers/%s@consol-%s", tv.volumeID, cas.ShortHash(tv.lastConsolidationHash))
			if recoverErr := d.recoverParentFromCAS(ctx, tv, recoveredPath); recoverErr != nil {
				klog.Warningf("syncOne %s: failed to recover consolidation %s from CAS: %v",
					tv.volumeID, cas.ShortHash(tv.lastConsolidationHash), recoverErr)
			} else {
				parentPath = recoveredPath
				parentHash = tv.lastConsolidationHash
			}
		}
		// Fall back to template.
		if parentPath == "" && tv.templateName != "" {
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
		} else if tv.lastLayerHash != "" && d.cas != nil {
			// Parent layer was GC'd but we know its hash — recover from CAS.
			recoveredPath := fmt.Sprintf("layers/%s@%s", tv.volumeID, cas.ShortHash(tv.lastLayerHash))
			if recoverErr := d.recoverParentFromCAS(ctx, tv, recoveredPath); recoverErr != nil {
				klog.Warningf("syncOne %s: failed to recover parent %s from CAS: %v",
					tv.volumeID, cas.ShortHash(tv.lastLayerHash), recoverErr)
			} else {
				parentPath = recoveredPath
				parentHash = tv.lastLayerHash
			}
		}
		// Fall back to template if no parent recovered.
		if parentPath == "" && tv.templateName != "" {
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
	// Close the stall reader AND the underlying btrfs send process.
	// cmdReadCloser.Close() waits for btrfs send to exit and returns its
	// error. If btrfs send failed (e.g., parent deleted mid-send), PutBlob
	// may have read 0 bytes and returned an empty hash without error —
	// the send failure only surfaces here.
	closeErr := stallR.Close()
	if err != nil {
		if cause := context.Cause(stallCtx); cause != nil {
			err = errors.Join(err, cause)
		}
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		return "", "", fmt.Errorf("put blob: %w", err)
	}
	if closeErr != nil {
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		return "", "", fmt.Errorf("btrfs send exited with error (blob %s discarded): %w", cas.ShortHash(hash), closeErr)
	}

	// Defense-in-depth: skip empty blobs. A valid btrfs send always
	// produces at least a stream header + SNAPSHOT command. An empty
	// hash means btrfs send wrote nothing (should be caught by closeErr
	// above, but guard against edge cases).
	const emptyBlobHash = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
	if hash == emptyBlobHash {
		_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		klog.Warningf("syncOne %s: btrfs send produced empty stream (parent=%s), skipping",
			tv.volumeID, cas.ShortHash(parentHash))
		return "", "", nil
	}

	// 4. Update manifest with new snapshot via Hub.
	// Prev always points to the chronologically previous snapshot (for timeline
	// display). Parent may skip intermediates for consolidation snapshots.
	// For non-consolidation snapshots, Prev == Parent.
	prevHash := tv.lastLayerHash
	if prevHash == "" {
		prevHash = tv.templateHash
	}
	snapshot := cas.Snapshot{
		Hash:          hash,
		Parent:        parentHash,
		Prev:          prevHash,
		Role:          role,
		Label:         label,
		Consolidation: isConsolidation,
		TS:            time.Now().UTC().Format(time.RFC3339),
	}

	if d.hub != nil {
		if _, hubErr := d.hub.AppendSnapshot(ctx, tv.volumeID, snapshot); hubErr != nil {
			_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
			return "", "", fmt.Errorf("hub append snapshot: %w", hubErr)
		}
	} else {
		// Fallback: no Hub configured (should not happen in production).
		klog.Warningf("syncOne %s: no Hub configured, snapshot %s not recorded in manifest", tv.volumeID, cas.ShortHash(hash))
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

// recoverParentFromCAS downloads the parent layer blob from CAS and receives
// it so that syncOne can use it as the btrfs send parent. This is called when
// the parent layer was GC'd (by RestoreToSnapshot or RestoreVolume cleanup)
// but we still know its hash via tv.lastLayerHash / tv.lastConsolidationHash.
//
// The layer's own parent is resolved recursively via ensureParentLayer using
// the manifest from CAS.
func (d *Daemon) recoverParentFromCAS(ctx context.Context, tv *trackedVolume, targetPath string) error {
	if d.btrfs.SubvolumeExists(ctx, targetPath) {
		return nil // already on disk
	}

	hash := tv.lastLayerHash
	if strings.Contains(targetPath, "@consol-") {
		hash = tv.lastConsolidationHash
	}
	if hash == "" {
		return fmt.Errorf("no hash to recover")
	}

	// Load manifest to resolve the parent chain for this layer.
	manifest, err := d.cas.GetManifest(ctx, tv.volumeID)
	if err != nil {
		return fmt.Errorf("get manifest: %w", err)
	}

	snap, ok := manifest.Snapshots[hash]
	if !ok {
		return fmt.Errorf("hash %s not in manifest", cas.ShortHash(hash))
	}

	// Ensure the parent of THIS layer exists (recursive).
	var grandparentPath string
	if snap.Parent != "" && snap.Parent != manifest.Base {
		gp, gpErr := d.ensureParentLayer(ctx, manifest, nil, hash, tv.volumeID)
		if gpErr != nil {
			return fmt.Errorf("ensure grandparent: %w", gpErr)
		}
		grandparentPath = gp
	} else if snap.Parent == manifest.Base && manifest.TemplateName != "" {
		grandparentPath = fmt.Sprintf("templates/%s", manifest.TemplateName)
	}

	klog.Infof("recoverParentFromCAS: downloading %s for volume %s", cas.ShortHash(hash), tv.volumeID)
	return d.downloadLayerWithRetry(ctx, tv.volumeID, hash, targetPath, grandparentPath)
}

// ensureParentLayer ensures the parent subvolume for the given snapshot hash
// exists on disk and returns its path. It uses the snapshot's Parent hash from
// the manifest to find the actual parent — NOT the previous entry in the
// restore chain, which may differ (e.g., after a restore that moved HEAD, or
// orphaned full-send layers).
//
// If the parent layer is not on disk (GC'd), it is downloaded from CAS.
// The parent's own parent is resolved recursively so that the full dependency
// chain is satisfied before btrfs receive runs.
func (d *Daemon) ensureParentLayer(ctx context.Context, manifest *cas.Manifest, chain []string, snapHash string, volumeID string) (string, error) {
	snap, ok := manifest.Snapshots[snapHash]
	if !ok {
		return "", fmt.Errorf("snapshot %s not found in manifest", cas.ShortHash(snapHash))
	}

	// No parent → full send, no rewrite needed.
	if snap.Parent == "" {
		return "", nil
	}

	// Parent is the template base.
	if snap.Parent == manifest.Base && manifest.TemplateName != "" {
		return fmt.Sprintf("templates/%s", manifest.TemplateName), nil
	}

	// Verify the parent exists in the manifest map.
	if _, exists := manifest.Snapshots[snap.Parent]; !exists {
		// Parent hash not in manifest at all — treat as full send.
		klog.Warningf("ensureParentLayer: parent %s for snapshot %s not found in manifest, treating as full send",
			cas.ShortHash(snap.Parent), cas.ShortHash(snapHash))
		return "", nil
	}

	parentPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(snap.Parent))

	// If parent already on disk, we're done.
	if d.btrfs.SubvolumeExists(ctx, parentPath) {
		return parentPath, nil
	}

	// Parent not on disk — download it. First ensure ITS parent exists
	// (recursive, but chains are shallow: max depth = consolidation interval).
	grandparentPath, err := d.ensureParentLayer(ctx, manifest, chain, snap.Parent, volumeID)
	if err != nil {
		return "", fmt.Errorf("ensure grandparent for snapshot %s: %w", cas.ShortHash(snap.Parent), err)
	}

	klog.Infof("ensureParentLayer: downloading missing parent %s for snapshot %s of volume %s",
		cas.ShortHash(snap.Parent), cas.ShortHash(snapHash), volumeID)

	if err := d.downloadLayerWithRetry(ctx, volumeID, snap.Parent, parentPath, grandparentPath); err != nil {
		return "", fmt.Errorf("download missing parent %s: %w", cas.ShortHash(snap.Parent), err)
	}

	return parentPath, nil
}

// downloadLayer downloads a CAS blob and receives it as a layer snapshot.
// Includes idempotent @pending cleanup (prevents permanent bricking after a
// failed receive) and stall detection (cancels on 30s of zero I/O progress).
//
// parentSubvolPath is the local path of the parent subvolume that this
// incremental layer was sent relative to. The send stream's parent UUID is
// rewritten to match the local parent's native UUID so that btrfs receive
// succeeds regardless of UUID lineage. For full sends (no parent), pass "".
func (d *Daemon) downloadLayer(ctx context.Context, volumeID, blobHash, targetPath, parentSubvolPath string) error {
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

	// Wrap with UUID rewriter if this is an incremental layer (has a parent).
	var recvReader io.Reader = stallR
	if parentSubvolPath != "" {
		parentID, idErr := d.btrfs.GetSubvolumeIdentity(ctx, parentSubvolPath)
		if idErr != nil {
			stallR.Close()
			return fmt.Errorf("get parent identity %s: %w", parentSubvolPath, idErr)
		}
		recvReader = btrfs.RewriteParentUUID(stallR, parentID)
	}

	if err := d.btrfs.Receive(stallCtx, "layers", recvReader); err != nil {
		stallR.Close()
		// Clean up partial @pending from the failed receive.
		if d.btrfs.SubvolumeExists(ctx, pendingPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		}
		if cause := context.Cause(stallCtx); cause != nil {
			return fmt.Errorf("btrfs receive blob %s: %w", blobHash, errors.Join(err, cause))
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

// maxLayerRetries is the number of attempts for downloading a single layer
// before giving up. Retries are only attempted for transient errors (stalls,
// connection resets, timeouts).
const maxLayerRetries = 3

// downloadLayerWithRetry wraps downloadLayer with per-layer retry logic.
// When a stall or transient error occurs, only the failed layer is retried —
// not the entire restore chain. The existing downloadLayer already cleans up
// partial @pending subvolumes, making retries idempotent.
func (d *Daemon) downloadLayerWithRetry(ctx context.Context, volumeID, blobHash, targetPath, parentSubvolPath string) error {
	var lastErr error
	for attempt := range maxLayerRetries {
		if attempt > 0 {
			klog.Warningf("downloadLayer %s attempt %d/%d (previous: %v)",
				cas.ShortHash(blobHash), attempt+1, maxLayerRetries, lastErr)
		}
		err := d.downloadLayer(ctx, volumeID, blobHash, targetPath, parentSubvolPath)
		if err == nil {
			return nil
		}
		lastErr = err
		// Parent context cancelled — don't retry.
		if ctx.Err() != nil {
			return err
		}
		if !isRetryableError(err) {
			return err
		}
	}
	return fmt.Errorf("download layer %s failed after %d attempts: %w",
		cas.ShortHash(blobHash), maxLayerRetries, lastErr)
}

// isRetryableError returns true for transient errors that warrant a retry.
// Uses errors.Is and syscall error checks — no string matching.
func isRetryableError(err error) bool {
	if err == nil {
		return false
	}

	// Stall detection (our own sentinel).
	if errors.Is(err, ioutil.ErrStall) {
		return true
	}

	// Context deadline exceeded (gRPC timeout, S3 timeout).
	if errors.Is(err, context.DeadlineExceeded) {
		return true
	}

	// Unexpected EOF (connection dropped mid-stream).
	if errors.Is(err, io.ErrUnexpectedEOF) {
		return true
	}

	// Syscall-level transient errors (connection reset, broken pipe, refused).
	var syscallErr *os.SyscallError
	if errors.As(err, &syscallErr) {
		switch syscallErr.Err {
		case syscall.ECONNRESET, syscall.ECONNREFUSED, syscall.EPIPE, syscall.ETIMEDOUT:
			return true
		}
	}

	// net.OpError wraps transient network failures.
	var netErr *net.OpError
	if errors.As(err, &netErr) {
		return netErr.Temporary() || netErr.Timeout()
	}

	return false
}

// maxPrefetchWorkers is the concurrency limit for parallel blob prefetch.
const maxPrefetchWorkers = 4

// prefetchBlobs downloads chain blobs concurrently to local temp files.
// Returns a map[blobHash] → *os.File (open for reading). The caller must
// close and remove all files when done (use cleanupPrefetch).
// Only blobs for layers not already on disk are prefetched.
func (d *Daemon) prefetchBlobs(ctx context.Context, manifest *cas.Manifest, chain []string, volumeID string) (map[string]string, error) {
	// Collect blobs that need downloading (skip layers already on disk).
	var needed []string
	for _, snapHash := range chain {
		layerPath := fmt.Sprintf("layers/%s@%s", volumeID, cas.ShortHash(snapHash))
		if !d.btrfs.SubvolumeExists(ctx, layerPath) {
			snap := manifest.Snapshots[snapHash]
			needed = append(needed, snap.Hash)
		}
	}

	if len(needed) == 0 {
		return nil, nil
	}

	klog.V(2).Infof("prefetchBlobs: %d blobs to download for volume %s", len(needed), volumeID)

	result := make(map[string]string, len(needed))
	var mu sync.Mutex

	g, gctx := errgroup.WithContext(ctx)
	g.SetLimit(maxPrefetchWorkers)

	for _, blobHash := range needed {
		g.Go(func() error {
			tmpFile, err := os.CreateTemp("", "prefetch-*.blob")
			if err != nil {
				return fmt.Errorf("create temp file for blob %s: %w", cas.ShortHash(blobHash), err)
			}
			tmpPath := tmpFile.Name()

			// Download with retry on stall.
			var lastErr error
			for attempt := range maxLayerRetries {
				if attempt > 0 {
					klog.Warningf("prefetch blob %s attempt %d/%d (previous: %v)",
						cas.ShortHash(blobHash), attempt+1, maxLayerRetries, lastErr)
					// Reset file for retry.
					if _, err := tmpFile.Seek(0, io.SeekStart); err != nil {
						break
					}
					if err := tmpFile.Truncate(0); err != nil {
						break
					}
				}

				reader, err := d.cas.GetBlob(gctx, blobHash)
				if err != nil {
					lastErr = fmt.Errorf("download blob %s: %w", cas.ShortHash(blobHash), err)
					if gctx.Err() != nil || !isRetryableError(lastErr) {
						break
					}
					continue
				}

				stallCtx, stallCancel := context.WithCancelCause(gctx)
				stallR := ioutil.NewStallReader(reader, stallCtx, stallCancel, ioutil.StallTimeout)

				_, copyErr := io.Copy(tmpFile, stallR)
				stallR.Close()
				stallCancel(nil) // prevent context leak

				if copyErr != nil {
					lastErr = fmt.Errorf("prefetch blob %s: %w", cas.ShortHash(blobHash), copyErr)
					if gctx.Err() != nil || !isRetryableError(lastErr) {
						break
					}
					continue
				}

				// Success — rewind file for reading.
				if _, err := tmpFile.Seek(0, io.SeekStart); err != nil {
					tmpFile.Close()
					os.Remove(tmpPath)
					return fmt.Errorf("rewind prefetched blob %s: %w", cas.ShortHash(blobHash), err)
				}
				tmpFile.Close()

				mu.Lock()
				result[blobHash] = tmpPath
				mu.Unlock()

				klog.V(3).Infof("prefetched blob %s → %s", cas.ShortHash(blobHash), tmpPath)
				return nil
			}

			// All retries exhausted.
			tmpFile.Close()
			os.Remove(tmpPath)
			if lastErr != nil {
				return lastErr
			}
			return fmt.Errorf("prefetch blob %s: all retries exhausted", cas.ShortHash(blobHash))
		})
	}

	if err := g.Wait(); err != nil {
		// Clean up any successfully prefetched files on failure.
		mu.Lock()
		for _, path := range result {
			os.Remove(path)
		}
		mu.Unlock()
		return nil, fmt.Errorf("prefetch blobs: %w", err)
	}

	return result, nil
}

// cleanupPrefetch removes all temp files from a prefetch map.
func cleanupPrefetch(prefetched map[string]string) {
	for _, path := range prefetched {
		os.Remove(path)
	}
}

// downloadLayerFromLocal is like downloadLayer but reads the blob from a local
// file instead of S3. Used after prefetchBlobs to apply pre-downloaded blobs.
func (d *Daemon) downloadLayerFromLocal(ctx context.Context, volumeID, blobHash, targetPath, parentSubvolPath, localPath string) error {
	pendingPath := fmt.Sprintf("layers/%s@pending", volumeID)

	if d.btrfs.SubvolumeExists(ctx, pendingPath) {
		if err := d.btrfs.DeleteSubvolume(ctx, pendingPath); err != nil {
			klog.Warningf("stale pending snapshot %q undeletable, using unique suffix: %v", pendingPath, err)
			pendingPath = fmt.Sprintf("layers/%s@pending-%d", volumeID, time.Now().UnixNano())
		}
	}

	file, err := os.Open(localPath)
	if err != nil {
		return fmt.Errorf("open prefetched blob %s: %w", cas.ShortHash(blobHash), err)
	}
	defer file.Close()

	var recvReader io.Reader = file
	if parentSubvolPath != "" {
		parentID, idErr := d.btrfs.GetSubvolumeIdentity(ctx, parentSubvolPath)
		if idErr != nil {
			return fmt.Errorf("get parent identity %s: %w", parentSubvolPath, idErr)
		}
		recvReader = btrfs.RewriteParentUUID(file, parentID)
	}

	if err := d.btrfs.Receive(ctx, "layers", recvReader); err != nil {
		if d.btrfs.SubvolumeExists(ctx, pendingPath) {
			_ = d.btrfs.DeleteSubvolume(ctx, pendingPath)
		}
		return fmt.Errorf("btrfs receive blob %s: %w", blobHash, err)
	}

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
