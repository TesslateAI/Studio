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
)

// ---------------------------------------------------------------------------
// Fake btrfsOps
// ---------------------------------------------------------------------------

type fakeBtrfs struct {
	mu          stdsync.Mutex
	subvolumes  map[string]bool   // path → exists
	generations map[string]uint64 // path → btrfs generation
	snapshots   []snapshotCall
	deletes     []string
	renames     []renameCall
	sendData    string // returned by Send
	sendErr     error
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

func (f *fakeBtrfs) Send(_ context.Context, _ string, _ string) (io.ReadCloser, error) {
	f.mu.Lock()
	sendErr := f.sendErr
	sendData := f.sendData
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

func (f *fakeBtrfs) Receive(_ context.Context, _ string, _ io.Reader) error {
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
	mu        stdsync.Mutex
	blobs     map[string]string // hash → data
	manifests map[string]*cas.Manifest
	putCount  int
	nextHash  string // hash returned by PutBlob
}

func newFakeCAS() *fakeCAS {
	return &fakeCAS{
		blobs:     make(map[string]string),
		manifests: make(map[string]*cas.Manifest),
		nextHash:  "sha256:aabbccddee001122334455667788990011223344556677889900112233445566",
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
	h := f.nextHash
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

// ---------------------------------------------------------------------------
// Fake templateOps
// ---------------------------------------------------------------------------

type fakeTemplate struct {
	uploaded map[string]string // name → hash
	nextHash string
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

func (f *fakeTemplate) EnsureTemplateByHash(_ context.Context, _, _ string) error {
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
// Tests
// ---------------------------------------------------------------------------

func TestSyncOne_AutoPromote_TemplatelessVolume(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-no-template"
	// Simulate volume subvolume existing.
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true

	tv := &trackedVolume{
		volumeID:     volID,
		templateName: "", // no template
		templateHash: "",
	}

	hash, _, err := d.syncOne(context.Background(), tv, "sync", "")
	if err != nil {
		t.Fatalf("syncOne failed: %v", err)
	}

	if hash == "" {
		t.Fatal("expected non-empty hash from syncOne")
	}

	// Verify auto-promote set templateName and templateHash on tv.
	expectedTmplName := "_vol_" + volID
	if tv.templateName != expectedTmplName {
		t.Errorf("templateName = %q, want %q", tv.templateName, expectedTmplName)
	}
	if tv.templateHash == "" {
		t.Error("templateHash should be set after auto-promote")
	}

	// Verify template was uploaded.
	if _, ok := ft.uploaded[expectedTmplName]; !ok {
		t.Error("synthetic template was not uploaded")
	}

	// Verify snapshot was created at templates/_vol_{volID}.
	tmplPath := "templates/" + expectedTmplName
	found := false
	for _, s := range fb.snapshots {
		if s.Dest == tmplPath && s.ReadOnly {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected read-only snapshot at %s, snapshots: %+v", tmplPath, fb.snapshots)
	}

	// Verify manifest was created with template info.
	manifest, err := fc.GetManifest(context.Background(), volID)
	if err != nil {
		t.Fatalf("manifest not found: %v", err)
	}
	if manifest.TemplateName != expectedTmplName {
		t.Errorf("manifest.TemplateName = %q, want %q", manifest.TemplateName, expectedTmplName)
	}
	if manifest.Base != ft.nextHash {
		t.Errorf("manifest.Base = %q, want %q", manifest.Base, ft.nextHash)
	}
}

func TestSyncOne_SkipsAutoPromote_TemplateBasedVolume(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-with-template"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true
	// Template exists locally.
	fb.subvolumes["templates/nodejs"] = true

	tv := &trackedVolume{
		volumeID:     volID,
		templateName: "nodejs",
		templateHash: "sha256:existinghash",
	}

	_, _, err := d.syncOne(context.Background(), tv, "sync", "")
	if err != nil {
		t.Fatalf("syncOne failed: %v", err)
	}

	// templateName should remain unchanged.
	if tv.templateName != "nodejs" {
		t.Errorf("templateName changed to %q, should remain %q", tv.templateName, "nodejs")
	}
	if tv.templateHash != "sha256:existinghash" {
		t.Errorf("templateHash changed to %q, should remain unchanged", tv.templateHash)
	}

	// No synthetic template should have been uploaded.
	if len(ft.uploaded) != 0 {
		t.Errorf("expected no template uploads, got %d", len(ft.uploaded))
	}
}

func TestSyncOne_AutoPromote_UploadFailure_GracefulDegradation(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	ft.uploadErr = fmt.Errorf("S3 unavailable")
	d := setupDaemon(fb, fc, ft)

	volID := "vol-upload-fail"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true

	tv := &trackedVolume{
		volumeID:     volID,
		templateName: "",
		templateHash: "",
	}

	hash, _, err := d.syncOne(context.Background(), tv, "sync", "")
	if err != nil {
		t.Fatalf("syncOne should succeed even when auto-promote fails: %v", err)
	}
	if hash == "" {
		t.Fatal("expected non-empty hash")
	}

	// templateName should still be empty — auto-promote failed gracefully.
	if tv.templateName != "" {
		t.Errorf("templateName = %q, should remain empty after failed auto-promote", tv.templateName)
	}
	if tv.templateHash != "" {
		t.Errorf("templateHash = %q, should remain empty after failed auto-promote", tv.templateHash)
	}

	// Synthetic template snapshot should have been cleaned up.
	tmplPath := "templates/_vol_" + volID
	if fb.subvolumes[tmplPath] {
		t.Error("synthetic template subvolume should be cleaned up after upload failure")
	}
}

func TestSyncVolume_WritesBackTemplateFields(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-writeback"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true

	// Track with no template.
	d.TrackVolume(volID, "", "")

	err := d.SyncVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("SyncVolume failed: %v", err)
	}

	// Verify tracked map has the promoted template fields.
	d.mu.Lock()
	tv := d.tracked[volID]
	d.mu.Unlock()

	expectedTmplName := "_vol_" + volID
	if tv.templateName != expectedTmplName {
		t.Errorf("tracked templateName = %q, want %q", tv.templateName, expectedTmplName)
	}
	if tv.templateHash == "" {
		t.Error("tracked templateHash should be set after auto-promote write-back")
	}
	if tv.lastLayerHash == "" {
		t.Error("tracked lastLayerHash should be set")
	}
	if tv.lastSyncAt.IsZero() {
		t.Error("tracked lastSyncAt should be set")
	}
}

func TestSyncAll_WritesBackTemplateFields(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-syncall"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true
	d.TrackVolume(volID, "", "")

	err := d.syncAll(context.Background())
	if err != nil {
		t.Fatalf("syncAll failed: %v", err)
	}

	d.mu.Lock()
	tv := d.tracked[volID]
	d.mu.Unlock()

	expectedTmplName := "_vol_" + volID
	if tv.templateName != expectedTmplName {
		t.Errorf("tracked templateName = %q, want %q", tv.templateName, expectedTmplName)
	}
	if tv.templateHash == "" {
		t.Error("tracked templateHash should be set after auto-promote via syncAll")
	}
}

func TestCreateSnapshot_WritesBackTemplateFields(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-snapshot-wb"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true
	d.TrackVolume(volID, "", "")

	hash, err := d.CreateSnapshot(context.Background(), volID, "test-label")
	if err != nil {
		t.Fatalf("CreateSnapshot failed: %v", err)
	}
	if hash == "" {
		t.Fatal("expected non-empty hash from CreateSnapshot")
	}

	d.mu.Lock()
	tv := d.tracked[volID]
	d.mu.Unlock()

	expectedTmplName := "_vol_" + volID
	if tv.templateName != expectedTmplName {
		t.Errorf("tracked templateName = %q, want %q", tv.templateName, expectedTmplName)
	}
	if tv.templateHash == "" {
		t.Error("tracked templateHash should be set after auto-promote via CreateSnapshot")
	}
}

func TestDeleteVolume_CleansSyntheticTemplate(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-delete-tmpl"
	syntheticPath := "templates/_vol_" + volID
	fb.subvolumes[syntheticPath] = true

	err := d.DeleteVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("DeleteVolume failed: %v", err)
	}

	// Synthetic template should have been deleted.
	if fb.subvolumes[syntheticPath] {
		t.Error("synthetic template subvolume should be deleted")
	}

	// Verify it was in the deletes list.
	found := false
	for _, p := range fb.deletes {
		if p == syntheticPath {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected %s in deletes list, got %v", syntheticPath, fb.deletes)
	}
}

func TestDeleteVolume_NoSyntheticTemplate_NoError(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-no-synth"
	// No synthetic template exists — should not error.

	err := d.DeleteVolume(context.Background(), volID)
	if err != nil {
		t.Fatalf("DeleteVolume failed: %v", err)
	}
}

func TestSyncOne_SecondSync_UsesTemplate(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-second-sync"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true

	tv := &trackedVolume{
		volumeID:     volID,
		templateName: "",
		templateHash: "",
	}

	// First sync: auto-promote creates synthetic template.
	_, _, err := d.syncOne(context.Background(), tv, "sync", "")
	if err != nil {
		t.Fatalf("first syncOne failed: %v", err)
	}
	if tv.templateName == "" {
		t.Fatal("auto-promote should have set templateName")
	}

	// Use a different hash for the second blob to distinguish it.
	fc.nextHash = "sha256:secondhash00000000000000000000000000000000000000000000000000000000"

	// Second sync: should use the synthetic template as parent (incremental).
	_, _, err = d.syncOne(context.Background(), tv, "sync", "")
	if err != nil {
		t.Fatalf("second syncOne failed: %v", err)
	}

	// Verify manifest has 2 layers, both with the template hash as parent.
	manifest, err := fc.GetManifest(context.Background(), volID)
	if err != nil {
		t.Fatalf("manifest not found: %v", err)
	}
	if len(manifest.Layers) != 2 {
		t.Fatalf("expected 2 layers, got %d", len(manifest.Layers))
	}
	for i, layer := range manifest.Layers {
		if layer.Parent != tv.templateHash {
			t.Errorf("layer[%d].Parent = %q, want %q (template hash)", i, layer.Parent, tv.templateHash)
		}
	}
}

func TestSyncOne_AutoPromote_OnlyOnFirstSync(t *testing.T) {
	fb := newFakeBtrfs()
	fc := newFakeCAS()
	ft := newFakeTemplate()
	d := setupDaemon(fb, fc, ft)

	volID := "vol-once"
	fb.subvolumes[fmt.Sprintf("volumes/%s", volID)] = true

	tv := &trackedVolume{
		volumeID:     volID,
		templateName: "",
		templateHash: "",
	}

	// First sync: triggers auto-promote.
	_, _, err := d.syncOne(context.Background(), tv, "sync", "")
	if err != nil {
		t.Fatalf("syncOne failed: %v", err)
	}

	uploadCountAfterFirst := len(ft.uploaded)

	// Second sync: should NOT trigger auto-promote (templateName is now set).
	fc.nextHash = "sha256:anotherhash0000000000000000000000000000000000000000000000000000000"
	_, _, err = d.syncOne(context.Background(), tv, "sync", "")
	if err != nil {
		t.Fatalf("second syncOne failed: %v", err)
	}

	if len(ft.uploaded) != uploadCountAfterFirst {
		t.Errorf("auto-promote ran twice: uploads went from %d to %d", uploadCountAfterFirst, len(ft.uploaded))
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
	if len(m.Layers) > 2 {
		t.Errorf("expected ≤2 layers, got %d (possible race)", len(m.Layers))
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
	if len(m.Layers) < 2 {
		t.Errorf("expected ≥2 layers after generation-promoted sync, got %d", len(m.Layers))
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
	// Should detect stall within ~syncStallTimeout + small overhead, not hang.
	if elapsed > syncStallTimeout+5*time.Second {
		t.Errorf("stall detection took %v, expected ~%v", elapsed, syncStallTimeout)
	}
	t.Logf("Stall detected in %v (timeout=%v)", elapsed, syncStallTimeout)
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
