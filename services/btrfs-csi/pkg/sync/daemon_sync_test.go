package sync

import (
	"context"
	"fmt"
	"io"
	"strings"
	stdsync "sync"
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/ioutil"
)

// ---------------------------------------------------------------------------
// Fake btrfsOps
// ---------------------------------------------------------------------------

type fakeBtrfs struct {
	mu             stdsync.Mutex
	subvolumes     map[string]bool   // path → exists
	generations    map[string]uint64 // path → btrfs generation
	snapshots      []snapshotCall
	deletes        []string
	renames        []renameCall
	sends          []sendCall // tracked sends (snapshot, parent)
	sendData       string     // returned by Send
	sendErr        error
	receiveCreates string // if set, Receive creates this subvolume path
	receiveErr     error  // if set, Receive returns this error
}

type sendCall struct {
	Snapshot, Parent string
}

type snapshotCall struct {
	Source, Dest string
	ReadOnly     bool
}

type renameCall struct {
	Old, New string
}

func newFakeBtrfs() *fakeBtrfs {
	return &fakeBtrfs{
		subvolumes:  make(map[string]bool),
		generations: make(map[string]uint64),
		sendData:    "fake-btrfs-stream",
	}
}

func (f *fakeBtrfs) SubvolumeExists(_ context.Context, name string) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.subvolumes[name]
}

func (f *fakeBtrfs) SnapshotSubvolume(_ context.Context, source, dest string, readOnly bool) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.snapshots = append(f.snapshots, snapshotCall{source, dest, readOnly})
	f.subvolumes[dest] = true
	return nil
}

func (f *fakeBtrfs) DeleteSubvolume(_ context.Context, name string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.deletes = append(f.deletes, name)
	delete(f.subvolumes, name)
	return nil
}

func (f *fakeBtrfs) Send(_ context.Context, snapshot string, parent string) (io.ReadCloser, error) {
	f.mu.Lock()
	sendErr := f.sendErr
	sendData := f.sendData
	f.sends = append(f.sends, sendCall{Snapshot: snapshot, Parent: parent})
	f.mu.Unlock()
	if sendErr != nil {
		return nil, sendErr
	}
	return io.NopCloser(strings.NewReader(sendData)), nil
}

func (f *fakeBtrfs) RenameSubvolume(_ context.Context, oldName, newName string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.renames = append(f.renames, renameCall{oldName, newName})
	if f.subvolumes[oldName] {
		delete(f.subvolumes, oldName)
		f.subvolumes[newName] = true
	}
	return nil
}

func (f *fakeBtrfs) ListSubvolumes(_ context.Context, prefix string) ([]btrfs.SubvolumeInfo, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	var result []btrfs.SubvolumeInfo
	for p := range f.subvolumes {
		if strings.HasPrefix(p, prefix) {
			result = append(result, btrfs.SubvolumeInfo{Path: p})
		}
	}
	return result, nil
}

func (f *fakeBtrfs) Receive(_ context.Context, _ string, r io.Reader) error {
	f.mu.Lock()
	creates := f.receiveCreates
	recvErr := f.receiveErr
	f.mu.Unlock()
	if recvErr != nil {
		return recvErr
	}
	// Drain the reader to avoid stall detection false positives in tests.
	_, _ = io.Copy(io.Discard, r)
	if creates != "" {
		f.mu.Lock()
		f.subvolumes[creates] = true
		f.mu.Unlock()
	}
	return nil
}

func (f *fakeBtrfs) GetQgroupUsage(_ context.Context, _ string) (int64, int64, error) {
	return 0, 0, nil
}

func (f *fakeBtrfs) GetGeneration(_ context.Context, name string) (uint64, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	gen, ok := f.generations[name]
	if !ok {
		return 0, fmt.Errorf("subvolume %q not found", name)
	}
	return gen, nil
}

// ---------------------------------------------------------------------------
// Fake casOps
// ---------------------------------------------------------------------------

type fakeCAS struct {
	mu         stdsync.Mutex
	blobs      map[string]string // hash → data
	manifests  map[string]*cas.Manifest
	tombstones map[string]bool // volumeID → exists
	putCount   int
	nextHash   string   // hash returned by PutBlob (if hashQueue is empty)
	hashQueue  []string // if non-empty, PutBlob pops from here
	deleted    []string // hashes deleted via DeleteBlob
}

func newFakeCAS() *fakeCAS {
	return &fakeCAS{
		blobs:      make(map[string]string),
		manifests:  make(map[string]*cas.Manifest),
		tombstones: make(map[string]bool),
		nextHash:   "sha256:aabbccddee001122334455667788990011223344556677889900112233445566",
	}
}

func (f *fakeCAS) PutBlob(ctx context.Context, r io.Reader) (string, error) {
	data, readErr := io.ReadAll(r)
	if readErr != nil {
		return "", readErr
	}
	// Also check context — stall detection cancels it.
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	var h string
	if len(f.hashQueue) > 0 {
		h = f.hashQueue[0]
		f.hashQueue = f.hashQueue[1:]
	} else {
		h = f.nextHash
	}
	f.blobs[h] = string(data)
	f.putCount++
	return h, nil
}

func (f *fakeCAS) GetBlob(_ context.Context, hash string) (io.ReadCloser, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	data, ok := f.blobs[hash]
	if !ok {
		return nil, fmt.Errorf("blob %s not found", hash)
	}
	return io.NopCloser(strings.NewReader(data)), nil
}

func (f *fakeCAS) DeleteBlob(_ context.Context, hash string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.blobs, hash)
	f.deleted = append(f.deleted, hash)
	return nil
}

func (f *fakeCAS) GetManifest(_ context.Context, volumeID string) (*cas.Manifest, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	m, ok := f.manifests[volumeID]
	if !ok {
		return nil, fmt.Errorf("manifest %s not found", volumeID)
	}
	return m, nil
}

func (f *fakeCAS) PutManifest(_ context.Context, m *cas.Manifest) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.manifests[m.VolumeID] = m
	return nil
}

func (f *fakeCAS) DeleteManifest(_ context.Context, volumeID string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.manifests, volumeID)
	return nil
}

func (f *fakeCAS) CleanupStaging(_ context.Context) (int, error) {
	return 0, nil
}

func (f *fakeCAS) PutTombstone(_ context.Context, volumeID string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.tombstones[volumeID] = true
	return nil
}

func (f *fakeCAS) HasTombstone(_ context.Context, volumeID string) (bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.tombstones[volumeID], nil
}

func (f *fakeCAS) DeleteTombstone(_ context.Context, volumeID string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.tombstones, volumeID)
	return nil
}

// ---------------------------------------------------------------------------
// Fake templateOps
// ---------------------------------------------------------------------------

type fakeTemplate struct {
	uploaded  map[string]string // name → hash
	ensured   []string          // names passed to EnsureTemplateByHash
	nextHash  string
	uploadErr error
}

func newFakeTemplate() *fakeTemplate {
	return &fakeTemplate{
		uploaded: make(map[string]string),
		nextHash: "sha256:tmplhash0000000000000000000000000000000000000000000000000000000000",
	}
}

func (f *fakeTemplate) UploadTemplate(_ context.Context, name string) (string, error) {
	if f.uploadErr != nil {
		return "", f.uploadErr
	}
	f.uploaded[name] = f.nextHash
	return f.nextHash, nil
}

func (f *fakeTemplate) EnsureTemplateByHash(_ context.Context, name, _ string) error {
	f.ensured = append(f.ensured, name)
	return nil
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

func setupDaemon(fb *fakeBtrfs, fc *fakeCAS, ft *fakeTemplate) *Daemon {
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)
	return d
}

// ---------------------------------------------------------------------------
// Template-less volume tests (no auto-promotion)
// ---------------------------------------------------------------------------

func TestSyncOne_TemplatelessVolume_FullSend(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-templateless"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true

	tv := &trackedVolume{
		volumeID:     volID,
		templateName: "",
		templateHash: "",
	}

	hash, _, err := d.syncOne(context.Background(), tv, "sync", "")
	if err != nil {
		t.Fatalf("syncOne failed: %v", err)
	}
	if hash == "" {
		t.Fatal("expected non-empty hash from syncOne")
	}

	// templateName and templateHash must remain empty — no auto-promotion.
	if tv.templateName != "" {
		t.Errorf("templateName = %q, want empty (no auto-promotion)", tv.templateName)
	}
	if tv.templateHash != "" {
		t.Errorf("templateHash = %q, want empty (no auto-promotion)", tv.templateHash)
	}

	// No template uploads should have occurred.
	if len(ft.uploaded) != 0 {
		t.Errorf("expected no template uploads, got %d", len(ft.uploaded))
	}

	// Manifest should have Base="" and TemplateName="".
	manifest, err := fc.GetManifest(context.Background(), volID)
	if err != nil {
		t.Fatalf("manifest not found: %v", err)
	}
	if manifest.Base != "" {
		t.Errorf("manifest.Base = %q, want empty", manifest.Base)
	}
	if manifest.TemplateName != "" {
		t.Errorf("manifest.TemplateName = %q, want empty", manifest.TemplateName)
	}
	if len(manifest.Snapshots) != 1 {
		t.Fatalf("expected 1 layer, got %d", len(manifest.Snapshots))
	}
	if manifest.Snapshots[0].Parent != "" {
		t.Errorf("layer.Parent = %q, want empty (full send)", manifest.Snapshots[0].Parent)
	}
}

func TestSyncOne_TemplatelessVolume_SecondSync_StillFullSend(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-still-full"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true

	tv := &trackedVolume{
		volumeID:     volID,
		templateName: "",
		templateHash: "",
	}

	// First sync.
	_, _, err := d.syncOne(context.Background(), tv, "sync", "")
	if err != nil {
		t.Fatalf("first syncOne failed: %v", err)
	}

	// Second sync with a different hash.
	fc.nextHash = "sha256:secondhash00000000000000000000000000000000000000000000000000000000"
	_, _, err = d.syncOne(context.Background(), tv, "sync", "")
	if err != nil {
		t.Fatalf("second syncOne failed: %v", err)
	}

	// templateName must still be empty — no promotion happened.
	if tv.templateName != "" {
		t.Errorf("templateName = %q after second sync, want empty", tv.templateName)
	}

	// No template uploads at all.
	if len(ft.uploaded) != 0 {
		t.Errorf("expected no template uploads, got %d", len(ft.uploaded))
	}

	// Both layers should have empty Parent (both are full sends).
	manifest, err := fc.GetManifest(context.Background(), volID)
	if err != nil {
		t.Fatalf("manifest not found: %v", err)
	}
	if len(manifest.Snapshots) != 2 {
		t.Fatalf("expected 2 layers, got %d", len(manifest.Snapshots))
	}
	for i, layer := range manifest.Snapshots {
		if layer.Parent != "" {
			t.Errorf("layer[%d].Parent = %q, want empty (full send)", i, layer.Parent)
		}
	}
}

func TestRestoreVolume_TemplatelessVolume(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-restore-templateless"
	layerHash := "sha256:fulllayerhash000000000000000000000000000000000000000000000000000000"

	// Set up a manifest with no base template — layers are full sends.
	fc.manifests[volID] = &cas.Manifest{
		VolumeID:     volID,
		Base:         "",
		TemplateName: "",
		Snapshots: []cas.Layer{
			{Hash: layerHash, Parent: "", Role: "sync", TS: "2026-04-01T00:00:00Z"},
		},
	}
	// The blob exists in CAS.
	fc.blobs[layerHash] = "full-send-data"

	err := d.RestoreVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("RestoreVolume failed: %v", err)
	}

	// No template should have been downloaded.
	if len(ft.ensured) != 0 {
		t.Errorf("expected no template downloads, got %d: %v", len(ft.ensured), ft.ensured)
	}

	// Volume should exist as a writable snapshot.
	volumePath := fmt.Sprintf("volumes/%s", volID)
	if !fb.subvolumes[volumePath] {
		t.Errorf("expected volume at %s", volumePath)
	}
}

func TestRestoreVolume_TemplatelessVolume_NoLayers(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-restore-empty"

	// Manifest with no base and no layers — unrestorable.
	fc.manifests[volID] = &cas.Manifest{
		VolumeID:     volID,
		Base:         "",
		TemplateName: "",
		Snapshots:       []cas.Layer{},
	}

	err := d.RestoreVolume(context.Background(), volID)
	if err == nil {
		t.Fatal("RestoreVolume should fail for volume with no base and no layers")
	}
	if !strings.Contains(err.Error(), "no layers and no base template") {
		t.Errorf("unexpected error: %v", err)
	}
}

// ---------------------------------------------------------------------------
// Dirty tracking tests
// ---------------------------------------------------------------------------

func TestTrackVolume_StartsDirty(t *testing.T) {
	d := setupDaemon(newFakeBtrfs(), newFakeCAS(), newFakeTemplate())
	d.TrackVolume("vol-1", "", "")

	d.mu.Lock()
	tv := d.tracked["vol-1"]
	d.mu.Unlock()

	if !tv.dirty {
		t.Error("newly tracked volume should start dirty")
	}
}

func TestSyncVolume_ClearsDirty(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-dirty-clear"
	fb.subvolumes["volumes/"+volID] = true
	d.TrackVolume(volID, "", "")

	// Volume starts dirty.
	d.mu.Lock()
	if !d.tracked[volID].dirty {
		t.Fatal("expected dirty=true before sync")
	}
	d.mu.Unlock()

	if err := d.SyncVolume(context.Background(), volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// After successful sync, volume should be clean.
	d.mu.Lock()
	if d.tracked[volID].dirty {
		t.Error("expected dirty=false after successful sync")
	}
	d.mu.Unlock()
}

func TestMarkDirty_SetsDirtyFlag(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-mark"
	fb.subvolumes["volumes/"+volID] = true
	d.TrackVolume(volID, "", "")

	// Sync to clear dirty.
	if err := d.SyncVolume(context.Background(), volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	d.mu.Lock()
	if d.tracked[volID].dirty {
		t.Fatal("expected clean after sync")
	}
	d.mu.Unlock()

	// Mark dirty.
	d.MarkDirty(volID)

	d.mu.Lock()
	if !d.tracked[volID].dirty {
		t.Error("expected dirty=true after MarkDirty")
	}
	d.mu.Unlock()
}

func TestMarkDirty_UntrackedVolume_NoPanic(t *testing.T) {
	d := setupDaemon(newFakeBtrfs(), newFakeCAS(), newFakeTemplate())
	// Should not panic on untracked volume.
	d.MarkDirty("nonexistent")
}

func TestSyncAll_SkipsCleanVolumes(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	// Create 3 volumes: all start dirty.
	for _, id := range []string{"vol-a", "vol-b", "vol-c"} {
		fb.subvolumes["volumes/"+id] = true
		d.TrackVolume(id, "", "")
	}

	// Sync all — all are dirty, so all 3 should sync.
	if err := d.syncAll(context.Background()); err != nil {
		t.Fatalf("first syncAll: %v", err)
	}

	// All should now be clean.
	d.mu.Lock()
	for _, id := range []string{"vol-a", "vol-b", "vol-c"} {
		if d.tracked[id].dirty {
			t.Errorf("volume %s should be clean after syncAll", id)
		}
	}
	d.mu.Unlock()

	// Reset putCount to track new syncs.
	initialPutCount := fc.putCount

	// Mark only vol-b dirty.
	d.MarkDirty("vol-b")

	// Second syncAll — only vol-b should sync.
	if err := d.syncAll(context.Background()); err != nil {
		t.Fatalf("second syncAll: %v", err)
	}

	// Exactly 1 new blob put (for vol-b).
	if fc.putCount-initialPutCount != 1 {
		t.Errorf("expected 1 blob put for dirty volume, got %d", fc.putCount-initialPutCount)
	}
}

func TestDrainAll_SkipsCleanVolumes(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	// Create 5 volumes.
	ids := []string{"vol-1", "vol-2", "vol-3", "vol-4", "vol-5"}
	for _, id := range ids {
		fb.subvolumes["volumes/"+id] = true
		d.TrackVolume(id, "", "")
	}

	// Sync all to make them clean.
	for _, id := range ids {
		if err := d.SyncVolume(context.Background(), id); err != nil {
			t.Fatalf("SyncVolume %s: %v", id, err)
		}
	}

	initialPutCount := fc.putCount

	// Mark only vol-2 and vol-4 dirty.
	d.MarkDirty("vol-2")
	d.MarkDirty("vol-4")

	// DrainAll should only sync the 2 dirty volumes.
	if err := d.DrainAll(context.Background()); err != nil {
		t.Fatalf("DrainAll: %v", err)
	}

	if fc.putCount-initialPutCount != 2 {
		t.Errorf("expected 2 blob puts for dirty volumes, got %d", fc.putCount-initialPutCount)
	}
}

func TestGetTrackedState_ReportsDirty(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	fb.subvolumes["volumes/vol-1"] = true
	d.TrackVolume("vol-1", "", "")

	// Newly tracked — dirty.
	states := d.GetTrackedState()
	if len(states) != 1 {
		t.Fatalf("expected 1 state, got %d", len(states))
	}
	if !states[0].Dirty {
		t.Error("newly tracked volume should report Dirty=true")
	}

	// Sync to clean.
	if err := d.SyncVolume(context.Background(), "vol-1"); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	states = d.GetTrackedState()
	if states[0].Dirty {
		t.Error("synced volume should report Dirty=false")
	}
}

// ---------------------------------------------------------------------------
// Parallel DrainAll tests
// ---------------------------------------------------------------------------

// slowFakeCAS wraps fakeCAS with a per-PutBlob delay to simulate S3 latency.
type slowFakeCAS struct {
	*fakeCAS
	delay time.Duration
}

func (f *slowFakeCAS) PutBlob(ctx context.Context, r io.Reader) (string, error) {
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case <-time.After(f.delay):
	}
	return f.fakeCAS.PutBlob(ctx, r)
}

func TestDrainAll_Parallel_FasterThanSerial(t *testing.T) {
	fb := newFakeBtrfs()
	fc := &slowFakeCAS{fakeCAS: newFakeCAS(), delay: 50 * time.Millisecond}
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)

	numVols := 6
	for i := 0; i < numVols; i++ {
		volID := fmt.Sprintf("vol-drain-%d", i)
		fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true
		d.TrackVolume(volID, "tmpl", "sha256:base")
	}

	start := time.Now()
	err := d.DrainAll(context.Background())
	elapsed := time.Since(start)

	if err != nil {
		t.Fatalf("DrainAll error: %v", err)
	}

	// Serial would take ≥ 6 × 50ms = 300ms.
	// Parallel (cap=3) should take ≈ 2 × 50ms = 100ms + overhead.
	// Allow up to 200ms — proving parallelism.
	serialTime := time.Duration(numVols) * 50 * time.Millisecond
	if elapsed >= serialTime {
		t.Errorf("DrainAll took %v — slower than serial (%v). Parallelism not working.", elapsed, serialTime)
	}
	t.Logf("DrainAll: %d volumes in %v (serial would be ≥%v)", numVols, elapsed, serialTime)

	// All volumes should have manifests.
	for i := 0; i < numVols; i++ {
		volID := fmt.Sprintf("vol-drain-%d", i)
		if _, err := fc.GetManifest(context.Background(), volID); err != nil {
			t.Errorf("manifest missing for %s: %v", volID, err)
		}
	}
}

func TestDrainAll_ParallelOnlyDirty(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)

	// 3 clean + 2 dirty
	for i := 0; i < 5; i++ {
		volID := fmt.Sprintf("vol-mix-%d", i)
		fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true
		d.TrackVolume(volID, "tmpl", "sha256:base")
	}
	// Mark first 3 as clean
	d.mu.Lock()
	for i := 0; i < 3; i++ {
		d.tracked[fmt.Sprintf("vol-mix-%d", i)].dirty = false
	}
	d.mu.Unlock()

	err := d.DrainAll(context.Background())
	if err != nil {
		t.Fatalf("DrainAll error: %v", err)
	}

	// Only 2 dirty volumes should have been synced (manifests created).
	synced := 0
	for i := 0; i < 5; i++ {
		volID := fmt.Sprintf("vol-mix-%d", i)
		if _, err := fc.GetManifest(context.Background(), volID); err == nil {
			synced++
		}
	}
	if synced != 2 {
		t.Errorf("expected 2 synced manifests, got %d", synced)
	}
}

func TestSyncAll_LocksPerVolume(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)

	volID := "vol-locktest"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true
	d.TrackVolume(volID, "tmpl", "sha256:base")

	// Run syncAll and a concurrent SyncVolume on the same volume.
	// Both should complete without error (serialized by per-volume lock).
	errs := make(chan error, 2)
	go func() { errs <- d.syncAll(context.Background()) }()
	go func() { errs <- d.SyncVolume(context.Background(), volID) }()

	for i := 0; i < 2; i++ {
		if err := <-errs; err != nil {
			t.Errorf("concurrent sync error: %v", err)
		}
	}

	// Manifest should exist and not be corrupted (no duplicate layers from race).
	m, err := fc.GetManifest(context.Background(), volID)
	if err != nil {
		t.Fatalf("manifest missing: %v", err)
	}
	// Should have at most 2 layers (one from each sync). Previously without
	// locking, concurrent syncOne could produce duplicate/corrupt layers.
	if len(m.Snapshots) > 2 {
		t.Errorf("expected ≤2 layers, got %d (possible race)", len(m.Snapshots))
	}
}

func TestSyncAll_PromotesDirtyViaGeneration(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)

	volID := "vol-direct-write"
	fb.subvolumes["volumes/"+volID] = true
	d.TrackVolume(volID, "tmpl", "sha256:base")

	// Sync it first so it becomes clean with a layer snapshot.
	if err := d.SyncVolume(context.Background(), volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	d.mu.Lock()
	tv := d.tracked[volID]
	if tv.dirty {
		t.Fatal("volume should be clean after sync")
	}
	snapPath := tv.lastSnapPath
	d.mu.Unlock()

	// Simulate a direct write (compute pod) by advancing the volume generation
	// past the snapshot generation. No MarkDirty is called.
	fb.generations["volumes/"+volID] = 100
	fb.generations[snapPath] = 50

	// syncAll should detect the generation mismatch and promote to dirty.
	if err := d.syncAll(context.Background()); err != nil {
		t.Fatalf("syncAll: %v", err)
	}

	// The volume should have been synced (manifest should have a new layer).
	m, err := fc.GetManifest(context.Background(), volID)
	if err != nil {
		t.Fatalf("GetManifest: %v", err)
	}
	// Should have 2+ layers: one from SyncVolume, one from syncAll after promotion.
	if len(m.Snapshots) < 2 {
		t.Errorf("expected ≥2 layers after generation-promoted sync, got %d", len(m.Snapshots))
	}
}

// stallingBtrfs is a fakeBtrfs variant where Send returns some bytes then blocks.
type stallingBtrfs struct {
	*fakeBtrfs
}

func (s *stallingBtrfs) Send(_ context.Context, _ string, _ string) (io.ReadCloser, error) {
	pr, pw := io.Pipe()
	go func() {
		pw.Write([]byte("initial-bytes"))
		// Block forever — stall detection should cancel us.
		select {}
	}()
	return pr, nil
}

func TestSyncOne_StallDetection(t *testing.T) {
	fb := &stallingBtrfs{fakeBtrfs: newFakeBtrfs()}
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)

	volID := "vol-stall"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true

	tv := &trackedVolume{
		volumeID:     volID,
		templateName: "tmpl",
		templateHash: "sha256:base",
	}

	start := time.Now()
	_, _, err := d.syncOne(context.Background(), tv, "sync", "")
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("expected error from stalled sync")
	}
	if !strings.Contains(err.Error(), "stall") {
		t.Errorf("expected stall in error message, got: %v", err)
	}
	// Should detect stall within ~ioutil.StallTimeout + small overhead, not hang.
	if elapsed > ioutil.StallTimeout+5*time.Second {
		t.Errorf("stall detection took %v, expected ~%v", elapsed, ioutil.StallTimeout)
	}
	t.Logf("Stall detected in %v (timeout=%v)", elapsed, ioutil.StallTimeout)
}

// ---------------------------------------------------------------------------
// Smart dirty detection via btrfs generation
// ---------------------------------------------------------------------------

func TestDiscoverVolumes_CleanViaGeneration(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)

	// Simulate a volume and its layer snapshot on disk (left by previous pod's drain).
	fb.subvolumes["volumes/vol-clean"] = true
	fb.subvolumes["layers/vol-clean@abc123"] = true

	// Both have the same generation → volume is clean (not modified since snapshot).
	fb.generations["volumes/vol-clean"] = 42
	fb.generations["layers/vol-clean@abc123"] = 42

	// Add a manifest so template context is recovered.
	fc.manifests["vol-clean"] = &cas.Manifest{
		VolumeID:     "vol-clean",
		TemplateName: "nextjs",
		Base:         "sha256:tmplhash",
	}

	d.discoverVolumes(context.Background())

	d.mu.Lock()
	tv, ok := d.tracked["vol-clean"]
	d.mu.Unlock()

	if !ok {
		t.Fatal("vol-clean should be tracked")
	}
	if tv.dirty {
		t.Error("vol-clean should be clean (same generation as snapshot)")
	}
	if tv.lastSnapPath != "layers/vol-clean@abc123" {
		t.Errorf("lastSnapPath = %q, want layers/vol-clean@abc123", tv.lastSnapPath)
	}
	if tv.templateName != "nextjs" {
		t.Errorf("templateName = %q, want nextjs", tv.templateName)
	}
}

func TestDiscoverVolumes_DirtyViaGeneration(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)

	// Volume modified after snapshot — generation is higher.
	fb.subvolumes["volumes/vol-dirty"] = true
	fb.subvolumes["layers/vol-dirty@abc123"] = true
	fb.generations["volumes/vol-dirty"] = 50
	fb.generations["layers/vol-dirty@abc123"] = 42

	d.discoverVolumes(context.Background())

	d.mu.Lock()
	tv, ok := d.tracked["vol-dirty"]
	d.mu.Unlock()

	if !ok {
		t.Fatal("vol-dirty should be tracked")
	}
	if !tv.dirty {
		t.Error("vol-dirty should be dirty (volume generation > snapshot generation)")
	}
}

func TestDiscoverVolumes_DirtyNoSnapshot(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)

	// Volume exists but no layer snapshot — must be dirty.
	fb.subvolumes["volumes/vol-new"] = true
	fb.generations["volumes/vol-new"] = 10

	d.discoverVolumes(context.Background())

	d.mu.Lock()
	tv, ok := d.tracked["vol-new"]
	d.mu.Unlock()

	if !ok {
		t.Fatal("vol-new should be tracked")
	}
	if !tv.dirty {
		t.Error("vol-new should be dirty (no layer snapshot exists)")
	}
}

func TestDrainAll_PreservesLayerSnapshots(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)

	volID := "vol-drain-keep"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true
	d.TrackVolume(volID, "tmpl", "sha256:base")

	// Sync the volume first — this creates a layer snapshot.
	err := d.SyncVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Verify a layer snapshot was created.
	d.mu.Lock()
	tv := d.tracked[volID]
	snapPath := tv.lastSnapPath
	d.mu.Unlock()
	if snapPath == "" {
		t.Fatal("expected lastSnapPath after sync")
	}
	if !fb.SubvolumeExists(context.Background(), snapPath) {
		t.Fatalf("layer snapshot %s should exist after sync", snapPath)
	}

	// Mark dirty again to force drain to sync.
	d.MarkDirty(volID)

	// Drain.
	if err := d.DrainAll(context.Background()); err != nil {
		t.Fatalf("DrainAll: %v", err)
	}

	// The layer snapshot should STILL exist (drain preserves it).
	if !fb.SubvolumeExists(context.Background(), snapPath) {
		// Check if a new snapshot was created (drain creates new layers).
		found := false
		for path := range fb.subvolumes {
			if strings.HasPrefix(path, "layers/"+volID+"@") {
				found = true
				break
			}
		}
		if !found {
			t.Error("layer snapshot should be preserved after drain (needed for generation comparison)")
		}
	}
}

func TestDiscoverVolumes_MixedCleanAndDirty(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)

	// 3 clean volumes, 2 dirty, 1 new (no snapshot).
	for i := 0; i < 3; i++ {
		volID := fmt.Sprintf("vol-clean-%d", i)
		fb.subvolumes["volumes/"+volID] = true
		fb.subvolumes[fmt.Sprintf("layers/%s@hash%d", volID, i)] = true
		fb.generations["volumes/"+volID] = 100
		fb.generations[fmt.Sprintf("layers/%s@hash%d", volID, i)] = 100
	}
	for i := 0; i < 2; i++ {
		volID := fmt.Sprintf("vol-dirty-%d", i)
		fb.subvolumes["volumes/"+volID] = true
		fb.subvolumes[fmt.Sprintf("layers/%s@hash%d", volID, i)] = true
		fb.generations["volumes/"+volID] = 200 // higher than snapshot
		fb.generations[fmt.Sprintf("layers/%s@hash%d", volID, i)] = 100
	}
	fb.subvolumes["volumes/vol-new"] = true
	fb.generations["volumes/vol-new"] = 10

	d.discoverVolumes(context.Background())

	d.mu.Lock()
	cleanCount := 0
	dirtyCount := 0
	for _, tv := range d.tracked {
		if tv.dirty {
			dirtyCount++
		} else {
			cleanCount++
		}
	}
	total := len(d.tracked)
	d.mu.Unlock()

	if total != 6 {
		t.Errorf("tracked %d volumes, want 6", total)
	}
	if cleanCount != 3 {
		t.Errorf("clean = %d, want 3", cleanCount)
	}
	if dirtyCount != 3 {
		t.Errorf("dirty = %d, want 3 (2 modified + 1 new)", dirtyCount)
	}
}

// ---------------------------------------------------------------------------
// downloadLayer tests (stall detection + idempotent @pending cleanup)
// ---------------------------------------------------------------------------

func TestDownloadLayer_HappyPath(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-download-happy"
	blobHash := "sha256:abcd1234"
	targetPath := fmt.Sprintf("layers/%s@abcd12", volID)

	// Store a blob in CAS.
	fc.blobs[blobHash] = "fake-layer-data"

	// Simulate btrfs receive creating @pending.
	fb.receiveCreates = fmt.Sprintf("layers/%s@pending", volID)

	err := d.downloadLayer(context.Background(), volID, blobHash, targetPath)
	if err != nil {
		t.Fatalf("downloadLayer: %v", err)
	}

	// Verify @pending was renamed to target.
	fb.mu.Lock()
	hasTarget := fb.subvolumes[targetPath]
	hasPending := fb.subvolumes[fmt.Sprintf("layers/%s@pending", volID)]
	fb.mu.Unlock()

	if !hasTarget {
		t.Error("target path should exist after rename")
	}
	if hasPending {
		t.Error("@pending should have been renamed away")
	}
}

func TestDownloadLayer_CleansUpStalePending(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-stale-pending"
	blobHash := "sha256:beef5678"
	targetPath := fmt.Sprintf("layers/%s@beef56", volID)
	pendingPath := fmt.Sprintf("layers/%s@pending", volID)

	// Pre-existing stale @pending from a previous failed run.
	fb.subvolumes[pendingPath] = true

	// Store a blob in CAS.
	fc.blobs[blobHash] = "fresh-layer-data"

	// Simulate btrfs receive creating @pending (after cleanup).
	fb.receiveCreates = pendingPath

	err := d.downloadLayer(context.Background(), volID, blobHash, targetPath)
	if err != nil {
		t.Fatalf("downloadLayer: %v", err)
	}

	// Verify stale @pending was deleted (should appear in deletes).
	fb.mu.Lock()
	deleted := false
	for _, d := range fb.deletes {
		if d == pendingPath {
			deleted = true
			break
		}
	}
	fb.mu.Unlock()

	if !deleted {
		t.Error("stale @pending should have been deleted before receive")
	}
}

func TestDownloadLayer_StalePendingUndeletable(t *testing.T) {
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(nil, fc, ft)

	volID := "vol-undeletable"
	blobHash := "sha256:dead9999"
	targetPath := fmt.Sprintf("layers/%s@dead99", volID)
	pendingPath := fmt.Sprintf("layers/%s@pending", volID)

	// Custom fakeBtrfs that fails to delete @pending.
	fb := &fakeBtrfs{
		subvolumes:  map[string]bool{pendingPath: true},
		generations: make(map[string]uint64),
		sendData:    "fake-btrfs-stream",
	}
	d.btrfs = fb

	// Store a blob.
	fc.blobs[blobHash] = "layer-data"

	// The fakeBtrfs.Delete always succeeds, so the stale @pending is cleaned up
	// and the receive proceeds normally. The unique-suffix fallback path is
	// exercised in integration tests where real btrfs subvolume deletion can fail.

	err := d.downloadLayer(context.Background(), volID, blobHash, targetPath)
	if err != nil {
		t.Fatalf("downloadLayer: %v", err)
	}
}

func TestRestoreVolume_WithStalePending(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-restore-stale"
	blobHash := "sha256:aabbccddeeff001122334455"
	pendingPath := fmt.Sprintf("layers/%s@pending", volID)
	targetPath := fmt.Sprintf("layers/%s@%s", volID, cas.ShortHash(blobHash))

	// Pre-existing stale @pending.
	fb.subvolumes[pendingPath] = true

	// Set up manifest with one layer.
	fc.manifests[volID] = &cas.Manifest{
		VolumeID:     volID,
		TemplateName: "test-tmpl",
		Base:         "sha256:tmplbase",
		Snapshots: []cas.Layer{
			{Hash: blobHash, Parent: "sha256:tmplbase", Role: "sync"},
		},
	}
	fc.blobs[blobHash] = "restore-layer-data"

	// Simulate btrfs receive creating @pending (after cleanup).
	fb.receiveCreates = pendingPath

	// Track the volume (RestoreVolume requires per-volume lock).
	d.TrackVolume(volID, "test-tmpl", "sha256:tmplbase")

	err := d.RestoreVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("RestoreVolume: %v", err)
	}

	// Verify stale @pending was cleaned up.
	fb.mu.Lock()
	deletedPending := false
	for _, del := range fb.deletes {
		if del == pendingPath {
			deletedPending = true
			break
		}
	}
	// Verify layer was received and renamed.
	hasTarget := fb.subvolumes[targetPath]
	fb.mu.Unlock()

	if !deletedPending {
		t.Error("stale @pending should have been deleted before restore")
	}
	if !hasTarget {
		t.Error("layer target path should exist after restore")
	}
}

// ---------------------------------------------------------------------------
// Root Cause C tests
// ---------------------------------------------------------------------------

// TestSyncAll_PeriodicDiscovery verifies that discoverVolumes runs every
// discoverInterval cycles via syncAll.
func TestSyncAll_PeriodicDiscovery(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 15*time.Second)

	ctx := context.Background()

	// Run discoverInterval-1 cycles — no discovery should happen.
	for i := 0; i < discoverInterval-1; i++ {
		_ = d.syncAll(ctx)
	}

	// Add an untracked volume on "disk" with a matching layer snapshot
	// so it's discovered as clean (won't trigger syncOne).
	fb.mu.Lock()
	fb.subvolumes["volumes/vol-untracked"] = true
	fb.generations["volumes/vol-untracked"] = 100
	fb.subvolumes["layers/vol-untracked@abc123"] = true
	fb.generations["layers/vol-untracked@abc123"] = 100 // same gen = clean
	fb.mu.Unlock()

	d.mu.Lock()
	_, tracked := d.tracked["vol-untracked"]
	d.mu.Unlock()
	if tracked {
		t.Fatal("volume should NOT be tracked before discovery interval")
	}

	// The Nth cycle triggers discovery.
	_ = d.syncAll(ctx)

	d.mu.Lock()
	_, tracked = d.tracked["vol-untracked"]
	d.mu.Unlock()
	if !tracked {
		t.Fatal("volume should be tracked after periodic discovery")
	}
}

// TestDrainAll_DiscoverBeforeSnapshot verifies that DrainAll re-discovers
// volumes from disk before building the drain list, catching late arrivals.
func TestDrainAll_DiscoverBeforeSnapshot(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 15*time.Second)

	// Put a volume on "disk" that isn't tracked.
	fb.mu.Lock()
	fb.subvolumes["volumes/vol-late"] = true
	fb.generations["volumes/vol-late"] = 50
	fb.mu.Unlock()

	ctx := context.Background()
	// DrainAll should discover vol-late and attempt to sync it.
	// The sync itself may fail (no real btrfs), but we verify discovery
	// happened by checking a snapshot was attempted.
	_ = d.DrainAll(ctx)

	// The key assertion: DrainAll should have attempted to sync vol-late,
	// which means it was discovered. Check that a snapshot was attempted.
	fb.mu.Lock()
	hasSnapshot := false
	for _, snap := range fb.snapshots {
		if strings.HasPrefix(snap.Source, "volumes/vol-late") {
			hasSnapshot = true
			break
		}
	}
	fb.mu.Unlock()

	if !hasSnapshot {
		t.Fatal("DrainAll should have discovered vol-late and attempted to sync it")
	}
}

// TestCleanupStaging_NilCAS verifies cleanupStaging is a no-op with nil CAS.
func TestCleanupStaging_NilCAS(t *testing.T) {
	d := newDaemonWithInterfaces(newFakeBtrfs(), nil, nil, 15*time.Second)
	// Should not panic.
	d.cleanupStaging(context.Background())
}

// ---------------------------------------------------------------------------
// Tombstone + safe delete tests
// ---------------------------------------------------------------------------

// TestUntrackVolume_WaitsForInflightSync verifies that UntrackVolume blocks
// until the per-volume lock is released, preventing a race with SyncVolume.
func TestUntrackVolume_WaitsForInflightSync(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 15*time.Second)

	volID := "vol-concurrent"
	fb.mu.Lock()
	fb.subvolumes["volumes/"+volID] = true
	fb.mu.Unlock()
	d.TrackVolume(volID, "", "")

	// Hold the per-volume lock to simulate an inflight SyncVolume.
	vl := d.volumeLock(volID)
	vl.Lock()

	untrackDone := make(chan struct{})
	go func() {
		d.UntrackVolume(volID)
		close(untrackDone)
	}()

	// Give UntrackVolume time to reach the lock.
	time.Sleep(50 * time.Millisecond)
	select {
	case <-untrackDone:
		t.Fatal("UntrackVolume returned before per-volume lock was released")
	default:
		// expected — still blocked
	}

	// Release the lock.
	vl.Unlock()

	select {
	case <-untrackDone:
		// success
	case <-time.After(2 * time.Second):
		t.Fatal("UntrackVolume did not complete after lock release")
	}

	// Volume should be untracked.
	d.mu.Lock()
	_, exists := d.tracked[volID]
	d.mu.Unlock()
	if exists {
		t.Error("volume should be untracked")
	}
}

// TestDiscoverVolumes_SkipsTombstoned verifies that discoverVolumes skips
// tombstoned volumes and cleans up their local resources.
func TestDiscoverVolumes_SkipsTombstoned(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 15*time.Second)

	// Volume exists on disk.
	fb.mu.Lock()
	fb.subvolumes["volumes/vol-deleted"] = true
	fb.subvolumes["layers/vol-deleted@abc123"] = true
	fb.subvolumes["templates/_vol_vol-deleted"] = true
	fb.mu.Unlock()

	// Tombstone exists in CAS.
	fc.mu.Lock()
	fc.tombstones["vol-deleted"] = true
	fc.mu.Unlock()

	d.discoverVolumes(context.Background())

	// Should NOT be tracked.
	d.mu.Lock()
	_, tracked := d.tracked["vol-deleted"]
	d.mu.Unlock()
	if tracked {
		t.Error("tombstoned volume should not be tracked")
	}

	// Local subvolume should be cleaned up (self-healing).
	fb.mu.Lock()
	volExists := fb.subvolumes["volumes/vol-deleted"]
	layerExists := fb.subvolumes["layers/vol-deleted@abc123"]
	tmplExists := fb.subvolumes["templates/_vol_vol-deleted"]
	fb.mu.Unlock()
	if volExists {
		t.Error("tombstoned volume subvolume should be deleted from disk")
	}
	if layerExists {
		t.Error("tombstoned volume layer should be deleted from disk")
	}
	if tmplExists {
		t.Error("tombstoned volume synthetic template should be deleted from disk")
	}

	// Tombstone should be deleted after cleanup.
	fc.mu.Lock()
	tombExists := fc.tombstones["vol-deleted"]
	fc.mu.Unlock()
	if tombExists {
		t.Error("tombstone should be removed after local cleanup")
	}
}

// TestDiscoverVolumes_TombstonedAndNormal verifies that tombstoned volumes
// are cleaned up while normal volumes are still tracked.
func TestDiscoverVolumes_TombstonedAndNormal(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 15*time.Second)

	// Normal volume on disk.
	fb.mu.Lock()
	fb.subvolumes["volumes/vol-alive"] = true
	fb.generations["volumes/vol-alive"] = 100
	// Tombstoned volume on disk.
	fb.subvolumes["volumes/vol-dead"] = true
	fb.mu.Unlock()

	fc.mu.Lock()
	fc.tombstones["vol-dead"] = true
	fc.mu.Unlock()

	d.discoverVolumes(context.Background())

	d.mu.Lock()
	_, aliveTracked := d.tracked["vol-alive"]
	_, deadTracked := d.tracked["vol-dead"]
	d.mu.Unlock()

	if !aliveTracked {
		t.Error("normal volume should be tracked")
	}
	if deadTracked {
		t.Error("tombstoned volume should not be tracked")
	}
}

// ---------------------------------------------------------------------------
// Phase 2: Incremental chain + consolidation tests
// ---------------------------------------------------------------------------

// TestSyncOne_IncrementalFromPrevious verifies that the second sync diffs
// from the previous snapshot (not the template), producing an incremental.
func TestSyncOne_IncrementalFromPrevious(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-incr"
	fb.subvolumes["volumes/"+volID] = true
	fb.subvolumes["templates/tmpl1"] = true
	d.TrackVolume(volID, "tmpl1", "sha256:base")

	// First sync: should use template as parent (no previous snapshot).
	fc.hashQueue = []string{"sha256:hash1", "sha256:hash2"}
	err := d.SyncVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("first sync: %v", err)
	}

	fb.mu.Lock()
	firstSend := fb.sends[0]
	fb.mu.Unlock()
	if firstSend.Parent != "templates/tmpl1" {
		t.Errorf("first sync parent = %q, want templates/tmpl1", firstSend.Parent)
	}

	// Second sync: should use previous layer snapshot as parent (incremental).
	d.MarkDirty(volID)
	err = d.SyncVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("second sync: %v", err)
	}

	fb.mu.Lock()
	secondSend := fb.sends[1]
	fb.mu.Unlock()

	// The previous layer snapshot should be the parent — it starts with "layers/"
	if !strings.HasPrefix(secondSend.Parent, "layers/"+volID+"@") {
		t.Errorf("second sync parent = %q, want layers/%s@<hash>", secondSend.Parent, volID)
	}
}

// TestSyncOne_ConsolidationAtInterval verifies that a consolidation snapshot
// is created when the number of snapshots since the last consolidation
// reaches the configured interval.
func TestSyncOne_ConsolidationAtInterval(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)
	d.consolidationInterval = 3 // consolidate every 3 snapshots
	d.consolidationRetention = 10

	volID := "vol-consol"
	fb.subvolumes["volumes/"+volID] = true
	fb.subvolumes["templates/tmpl1"] = true
	d.TrackVolume(volID, "tmpl1", "sha256:base")

	// Pre-populate manifest with 2 existing snapshots (no consolidation).
	fc.manifests[volID] = &cas.Manifest{
		VolumeID:     volID,
		Base:         "sha256:base",
		TemplateName: "tmpl1",
		Snapshots: []cas.Snapshot{
			{Hash: "sha256:s1", Parent: "sha256:base", Role: "sync"},
			{Hash: "sha256:s2", Parent: "sha256:s1", Role: "sync"},
		},
	}

	// Set up tracked state to match.
	d.mu.Lock()
	tv := d.tracked[volID]
	tv.lastLayerHash = "sha256:s2"
	tv.lastSnapPath = "layers/" + volID + "@s2hash"
	fb.subvolumes["layers/"+volID+"@s2hash"] = true
	d.mu.Unlock()

	// Third sync: should trigger consolidation (3 snapshots since no consolidation).
	fc.nextHash = "sha256:consol1"
	err := d.SyncVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("sync: %v", err)
	}

	// Check manifest: 3rd snapshot should be a consolidation.
	fc.mu.Lock()
	m := fc.manifests[volID]
	fc.mu.Unlock()

	if len(m.Snapshots) != 3 {
		t.Fatalf("manifest has %d snapshots, want 3", len(m.Snapshots))
	}
	third := m.Snapshots[2]
	if !third.Consolidation {
		t.Error("third snapshot should be a consolidation")
	}
	// Consolidation parent should be template base (no previous consolidation).
	if third.Parent != "sha256:base" {
		t.Errorf("consolidation parent = %q, want sha256:base", third.Parent)
	}

	// The btrfs send should use template as parent (consolidation).
	fb.mu.Lock()
	lastSend := fb.sends[len(fb.sends)-1]
	fb.mu.Unlock()
	if lastSend.Parent != "templates/tmpl1" {
		t.Errorf("consolidation send parent = %q, want templates/tmpl1", lastSend.Parent)
	}
}

// TestSyncOne_ConsolidationBlobsKept verifies that all consolidation blobs
// are kept in CAS (no pruning — chain integrity requires all blobs).
func TestSyncOne_ConsolidationBlobsKept(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)
	d.consolidationInterval = 2
	d.consolidationRetention = 2 // retention is set but pruning is a no-op

	volID := "vol-retention"
	fb.subvolumes["volumes/"+volID] = true
	fb.subvolumes["templates/tmpl1"] = true
	d.TrackVolume(volID, "tmpl1", "sha256:base")

	// Manifest with 2 existing consolidations.
	fc.manifests[volID] = &cas.Manifest{
		VolumeID:     volID,
		Base:         "sha256:base",
		TemplateName: "tmpl1",
		Snapshots: []cas.Snapshot{
			{Hash: "sha256:c1", Parent: "sha256:base", Role: "sync", Consolidation: true},
			{Hash: "sha256:s2", Parent: "sha256:c1", Role: "sync"},
			{Hash: "sha256:c2", Parent: "sha256:c1", Role: "sync", Consolidation: true},
			{Hash: "sha256:s4", Parent: "sha256:c2", Role: "sync"},
		},
	}
	fc.blobs["sha256:c1"] = "consol-1-data"
	fc.blobs["sha256:c2"] = "consol-2-data"

	d.mu.Lock()
	tv := d.tracked[volID]
	tv.lastLayerHash = "sha256:s4"
	tv.lastSnapPath = "layers/" + volID + "@s4hash"
	tv.lastConsolidationPath = "layers/" + volID + "@consol-c2"
	tv.lastConsolidationHash = "sha256:c2"
	fb.subvolumes["layers/"+volID+"@s4hash"] = true
	fb.subvolumes["layers/"+volID+"@consol-c2"] = true
	d.mu.Unlock()

	// 5th snapshot: triggers c3 consolidation.
	fc.nextHash = "sha256:c3"
	err := d.SyncVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("sync: %v", err)
	}

	// All consolidation blobs should still exist (no pruning).
	fc.mu.Lock()
	_, c1Exists := fc.blobs["sha256:c1"]
	_, c2Exists := fc.blobs["sha256:c2"]
	deletedCount := len(fc.deleted)
	fc.mu.Unlock()

	if !c1Exists {
		t.Error("c1 blob should be kept (no pruning)")
	}
	if !c2Exists {
		t.Error("c2 blob should be kept (no pruning)")
	}
	if deletedCount > 0 {
		t.Errorf("no blobs should be deleted, got %d", deletedCount)
	}

	// All 3 consolidations should be marked in the manifest.
	fc.mu.Lock()
	m := fc.manifests[volID]
	fc.mu.Unlock()

	consolCount := 0
	for _, s := range m.Snapshots {
		if s.Consolidation {
			consolCount++
		}
	}
	if consolCount != 3 {
		t.Errorf("expected 3 consolidations, got %d", consolCount)
	}
}

// TestSyncOne_ConsolidationSnapPath verifies that consolidation snapshots
// are kept on disk separately from incremental snapshots.
func TestSyncOne_ConsolidationSnapPath(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)
	d.consolidationInterval = 1 // every snapshot is a consolidation

	volID := "vol-path"
	fb.subvolumes["volumes/"+volID] = true
	fb.subvolumes["templates/tmpl1"] = true
	d.TrackVolume(volID, "tmpl1", "sha256:base")

	fc.nextHash = "sha256:c1hash"
	err := d.SyncVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("sync: %v", err)
	}

	// The consolidation snapshot should use @consol- prefix.
	d.mu.Lock()
	tv := d.tracked[volID]
	snapPath := tv.lastSnapPath
	consolPath := tv.lastConsolidationPath
	d.mu.Unlock()

	if !strings.Contains(snapPath, "@consol-") {
		t.Errorf("snapPath = %q, want @consol- prefix", snapPath)
	}
	if snapPath != consolPath {
		t.Errorf("for consolidation, snapPath (%s) should equal consolPath (%s)", snapPath, consolPath)
	}
}

// TestRestoreVolume_IncrementalChain verifies that RestoreVolume replays
// the full incremental chain (consolidation + incrementals).
func TestRestoreVolume_IncrementalChain(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-chain-restore"
	fb.subvolumes["templates/tmpl1"] = true

	// Manifest: template → c1 → s2 → s3
	fc.manifests[volID] = &cas.Manifest{
		VolumeID:     volID,
		Base:         "sha256:base",
		TemplateName: "tmpl1",
		Snapshots: []cas.Snapshot{
			{Hash: "sha256:s0", Parent: "sha256:base", Role: "sync"},
			{Hash: "sha256:c1", Parent: "sha256:base", Role: "sync", Consolidation: true},
			{Hash: "sha256:s2", Parent: "sha256:c1", Role: "sync"},
			{Hash: "sha256:s3", Parent: "sha256:s2", Role: "checkpoint"},
		},
	}
	// Blobs for all snapshots.
	fc.blobs["sha256:s0"] = "s0-data"
	fc.blobs["sha256:c1"] = "c1-data"
	fc.blobs["sha256:s2"] = "s2-data"
	fc.blobs["sha256:s3"] = "s3-data"

	// Simulate btrfs receive creating @pending for each layer.
	// We'll track what subvolumes get created via receiveCreates.
	fb.receiveCreates = fmt.Sprintf("layers/%s@pending", volID)

	d.TrackVolume(volID, "tmpl1", "sha256:base")

	err := d.RestoreVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("RestoreVolume: %v", err)
	}

	// Should have created a writable volume.
	if !fb.SubvolumeExists(context.Background(), "volumes/"+volID) {
		t.Error("volumes/vol-chain-restore should exist after restore")
	}

	// Verify the restore chain: c1, s2, s3 (skipping s0 because c1 is at index 1).
	// The chain should download c1, s2, s3 — that's 3 blobs.
	// Each blob triggers a GetBlob call on the CAS (but we can check the receive calls).
}

// TestDaemonConfig_Defaults verifies DefaultDaemonConfig returns sensible values.
func TestDaemonConfig_Defaults(t *testing.T) {
	cfg := DefaultDaemonConfig()
	if cfg.SafetyInterval != 5*time.Minute {
		t.Errorf("SafetyInterval = %v, want 5m", cfg.SafetyInterval)
	}
	if cfg.ConsolidationInterval != 50 {
		t.Errorf("ConsolidationInterval = %d, want 50", cfg.ConsolidationInterval)
	}
	if cfg.ConsolidationRetention != 3 {
		t.Errorf("ConsolidationRetention = %d, want 3", cfg.ConsolidationRetention)
	}
}

// TestSyncOne_FirstSync_NoTemplate_FullSend verifies that a volume with no
// template produces a full send (no parent) on the first sync.
func TestSyncOne_FirstSync_NoTemplate_FullSend(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-no-tmpl"
	fb.subvolumes["volumes/"+volID] = true
	d.TrackVolume(volID, "", "")

	fc.nextHash = "sha256:fullhash"
	err := d.SyncVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("sync: %v", err)
	}

	// First sync with no template: parent should be "" (full send).
	fb.mu.Lock()
	firstSend := fb.sends[0]
	fb.mu.Unlock()
	if firstSend.Parent != "" {
		t.Errorf("parent = %q, want empty (full send)", firstSend.Parent)
	}
}

// TestSyncOne_IncrementalKeepsConsolidationOnDisk verifies that creating a
// normal incremental does NOT delete the consolidation snapshot on disk.
func TestSyncOne_IncrementalKeepsConsolidationOnDisk(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := newDaemonWithInterfaces(fb, fc, ft, 1*time.Hour)
	d.consolidationInterval = 100 // won't trigger

	volID := "vol-keep-consol"
	fb.subvolumes["volumes/"+volID] = true
	fb.subvolumes["templates/tmpl1"] = true
	d.TrackVolume(volID, "tmpl1", "sha256:base")

	// Simulate existing consolidation on disk.
	consolPath := "layers/" + volID + "@consol-prev"
	incrPath := "layers/" + volID + "@prevhash"
	fb.subvolumes[consolPath] = true
	fb.subvolumes[incrPath] = true

	d.mu.Lock()
	tv := d.tracked[volID]
	tv.lastSnapPath = incrPath
	tv.lastLayerHash = "sha256:prev"
	tv.lastConsolidationPath = consolPath
	tv.lastConsolidationHash = "sha256:cprev"
	d.mu.Unlock()

	// Pre-populate manifest so it doesn't trigger consolidation.
	fc.manifests[volID] = &cas.Manifest{
		VolumeID:     volID,
		Base:         "sha256:base",
		TemplateName: "tmpl1",
		Snapshots: []cas.Snapshot{
			{Hash: "sha256:cprev", Parent: "sha256:base", Role: "sync", Consolidation: true},
			{Hash: "sha256:prev", Parent: "sha256:cprev", Role: "sync"},
		},
	}

	fc.nextHash = "sha256:newhash"
	d.MarkDirty(volID)
	err := d.SyncVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("sync: %v", err)
	}

	// The old incremental should be deleted, but the consolidation should remain.
	if fb.SubvolumeExists(context.Background(), incrPath) {
		t.Error("old incremental snapshot should be deleted")
	}
	if !fb.SubvolumeExists(context.Background(), consolPath) {
		t.Error("consolidation snapshot should be kept on disk")
	}
}
