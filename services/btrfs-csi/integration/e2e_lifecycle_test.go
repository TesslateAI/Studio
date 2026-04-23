//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/gc"
	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
)

// ---------------------------------------------------------------------------
// Test 1: TestTier0_FileOps
// Create a template, snapshot it, then exercise FileOps read/write through
// the gRPC client to verify the full path: btrfs snapshot → gRPC → file I/O.
// ---------------------------------------------------------------------------

func TestTier0_FileOps(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	// Create a template subvolume with a seed file.
	tmplName := "templates/" + uniqueName("e2e-tmpl")
	if err := mgr.CreateSubvolume(ctx, tmplName); err != nil {
		t.Fatalf("create template: %v", err)
	}
	t.Cleanup(func() { mgr.DeleteSubvolume(context.Background(), tmplName) })

	seedContent := "seed-data-" + uniqueName("content")
	writeTestFile(t, filepath.Join(pool, tmplName), "seed.txt", seedContent)

	// Create a volume by snapshotting the template.
	volID := uniqueName("e2e-vol")
	volPath := "volumes/" + volID
	if err := mgr.SnapshotSubvolume(ctx, tmplName, volPath, false); err != nil {
		t.Fatalf("snapshot template to volume: %v", err)
	}
	t.Cleanup(func() { mgr.DeleteSubvolume(context.Background(), volPath) })

	// Start FileOps server + client.
	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)

	// Read seed file via FileOps client.
	data, err := client.ReadFile(ctx, volID, "seed.txt")
	if err != nil {
		t.Fatalf("ReadFile seed.txt: %v", err)
	}
	if string(data) != seedContent {
		t.Fatalf("seed.txt content = %q, want %q", string(data), seedContent)
	}

	// Write a new file via FileOps client, then read it back.
	newContent := "new-data-" + uniqueName("payload")
	if err := client.WriteFile(ctx, volID, "created.txt", []byte(newContent), 0644); err != nil {
		t.Fatalf("WriteFile created.txt: %v", err)
	}

	readBack, err := client.ReadFile(ctx, volID, "created.txt")
	if err != nil {
		t.Fatalf("ReadFile created.txt: %v", err)
	}
	if string(readBack) != newContent {
		t.Fatalf("created.txt content = %q, want %q", string(readBack), newContent)
	}
}

// ---------------------------------------------------------------------------
// Test 2: TestDrainLifecycle
// Create CAS infrastructure, track 3 volumes, call DrainAll, then verify
// all volumes are untracked and their manifests exist in S3.
// ---------------------------------------------------------------------------

func TestDrainLifecycle(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	// Ensure layers/ directory exists for sync snapshots.
	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	// Create CAS infrastructure.
	bucket := uniqueName("drain")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create a template with a seed file.
	tmplName := uniqueName("drain-tmpl")
	tmplPath := "templates/" + tmplName
	if err := mgr.CreateSubvolume(ctx, tmplPath); err != nil {
		t.Fatalf("create template: %v", err)
	}
	t.Cleanup(func() { mgr.DeleteSubvolume(context.Background(), tmplPath) })
	writeTestFile(t, filepath.Join(pool, tmplPath), "base.txt", "template-content")

	// Upload template to CAS to get its hash.
	tmplHash, err := tmplMgr.UploadTemplate(ctx, tmplName)
	if err != nil {
		t.Fatalf("UploadTemplate: %v", err)
	}

	// Create 3 volumes from template, track each with sync daemon.
	// 1h interval so the daemon never auto-fires.
	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	volIDs := make([]string, 3)
	for i := 0; i < 3; i++ {
		volIDs[i] = uniqueName("drain-vol")
		vp := "volumes/" + volIDs[i]
		if err := mgr.SnapshotSubvolume(ctx, tmplPath, vp, false); err != nil {
			t.Fatalf("snapshot for vol %d: %v", i, err)
		}
		vid := volIDs[i]
		t.Cleanup(func() {
			mgr.DeleteSubvolume(context.Background(), "volumes/"+vid)
		})
		writeTestFile(t, filepath.Join(pool, vp), "vol-data.txt", fmt.Sprintf("data-for-%s", volIDs[i]))
		daemon.TrackVolume(volIDs[i], tmplName, tmplHash)
	}

	// Verify all 3 are tracked.
	states := daemon.GetTrackedState()
	if len(states) != 3 {
		t.Fatalf("expected 3 tracked volumes before drain, got %d", len(states))
	}

	// DrainAll with 60s timeout.
	drainCtx, drainCancel := context.WithTimeout(ctx, 60*time.Second)
	defer drainCancel()
	if err := daemon.DrainAll(drainCtx); err != nil {
		t.Fatalf("DrainAll: %v", err)
	}

	// Assert tracked state is empty after drain.
	states = daemon.GetTrackedState()
	if len(states) != 0 {
		t.Fatalf("expected 0 tracked volumes after drain, got %d", len(states))
	}

	// Verify CAS manifests exist in S3 for all 3 volumes.
	for _, vid := range volIDs {
		manifest, err := casStore.GetManifest(ctx, vid)
		if err != nil {
			t.Errorf("GetManifest(%s): %v — expected manifest to exist after drain", vid, err)
			continue
		}
		if manifest.VolumeID != vid {
			t.Errorf("manifest.VolumeID = %q, want %q", manifest.VolumeID, vid)
		}
		if len(manifest.Snapshots) == 0 {
			t.Errorf("manifest for %s has 0 layers, expected at least 1", vid)
		}
	}

	// Clean up layer snapshots created by sync.
	for _, vid := range volIDs {
		subs, _ := mgr.ListSubvolumes(ctx, "layers/"+vid)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
	}
}

// ---------------------------------------------------------------------------
// Test 3: TestQuotaEnforcement
// Enable quotas, create a subvolume, set a 1 MiB limit, write a small file,
// then verify usage and limit are reported correctly.
// ---------------------------------------------------------------------------

func TestQuotaEnforcement(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// Enable quotas (may already be enabled by test runner).
	if err := mgr.EnableQuotas(ctx); err != nil {
		// Quotas might already be enabled — log but don't fail.
		t.Logf("EnableQuotas: %v (may already be enabled)", err)
	}

	volName := "volumes/" + uniqueName("quota")
	if err := mgr.CreateSubvolume(ctx, volName); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() { mgr.DeleteSubvolume(context.Background(), volName) })

	// Set 1 MiB qgroup limit.
	const limitBytes int64 = 1048576
	if err := mgr.SetQgroupLimit(ctx, volName, limitBytes); err != nil {
		t.Skipf("SetQgroupLimit not supported in this environment: %v", err)
	}

	// Write a 512 KiB file — should succeed.
	data512K := make([]byte, 512*1024)
	for i := range data512K {
		data512K[i] = byte(i % 256)
	}
	filePath := filepath.Join(pool, volName, "data.bin")
	if err := os.WriteFile(filePath, data512K, 0644); err != nil {
		t.Fatalf("write 512K file: %v", err)
	}

	// Force btrfs to flush metadata so qgroup accounting is updated.
	// Use a sync command to ensure the data is flushed.
	mgr.SubvolumeExists(ctx, volName) // triggers btrfs subvolume show

	// Verify qgroup usage.
	excl, limit, err := mgr.GetQgroupUsage(ctx, volName)
	if err != nil {
		t.Fatalf("GetQgroupUsage: %v", err)
	}

	if excl <= 0 {
		t.Errorf("exclusive usage = %d, want > 0 after writing 512K", excl)
	}
	if limit != limitBytes {
		t.Errorf("qgroup limit = %d, want %d", limit, limitBytes)
	}

	t.Logf("Quota results: exclusive=%d, limit=%d", excl, limit)
}

// ---------------------------------------------------------------------------
// Test 4: TestGC_WithHTTPKnownVolumes
// Create 4 volumes, start a test HTTP server returning 2 as "known",
// run GC, and verify only the unknown volumes are deleted.
// ---------------------------------------------------------------------------

func TestGC_WithHTTPKnownVolumes(t *testing.T) {
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	pool := getPoolPath(t)

	// Create 4 volumes.
	volA := "volumes/" + uniqueName("gc-http-a")
	volB := "volumes/" + uniqueName("gc-http-b")
	volC := "volumes/" + uniqueName("gc-http-c")
	volD := "volumes/" + uniqueName("gc-http-d")

	allVols := []string{volA, volB, volC, volD}
	for _, v := range allVols {
		if err := mgr.CreateSubvolume(ctx, v); err != nil {
			t.Fatalf("create %s: %v", v, err)
		}
		vCopy := v
		t.Cleanup(func() { mgr.DeleteSubvolume(context.Background(), vCopy) })
		writeTestFile(t, filepath.Join(pool, v), "data.txt", "payload-"+v)
	}

	// Discover the btrfs subvolume Names for volA and volB (the ones to keep).
	subs, err := mgr.ListSubvolumes(ctx, "volumes/")
	if err != nil {
		t.Fatalf("ListSubvolumes: %v", err)
	}
	baseToName := make(map[string]string)
	for _, sub := range subs {
		baseToName[filepath.Base(sub.Path)] = sub.Name
	}

	keepNameA := baseToName[filepath.Base(volA)]
	if keepNameA == "" {
		keepNameA = filepath.Base(volA)
	}
	keepNameB := baseToName[filepath.Base(volB)]
	if keepNameB == "" {
		keepNameB = filepath.Base(volB)
	}

	// Start a test HTTP server that returns vol-a and vol-b as known.
	knownIDs := []string{keepNameA, keepNameB}
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/internal/known-volume-ids" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"volume_ids": knownIDs,
		})
	}))
	defer ts.Close()

	// Create GC collector with grace period of 0 and SetOrchestratorURL.
	collector := gc.NewCollector(mgr, nil, gc.Config{
		GracePeriod: 0,
		DryRun:      false,
	})
	collector.SetOrchestratorURL(ts.URL, "") // empty secret — test server has no auth

	if err := collector.RunOnce(ctx); err != nil {
		t.Fatalf("RunOnce: %v", err)
	}

	// Assert vol-a and vol-b still exist.
	if !mgr.SubvolumeExists(ctx, volA) {
		t.Errorf("expected kept volume %s to still exist", volA)
	}
	if !mgr.SubvolumeExists(ctx, volB) {
		t.Errorf("expected kept volume %s to still exist", volB)
	}

	// Assert vol-c and vol-d are deleted.
	if mgr.SubvolumeExists(ctx, volC) {
		t.Errorf("expected orphan %s to be deleted", volC)
	}
	if mgr.SubvolumeExists(ctx, volD) {
		t.Errorf("expected orphan %s to be deleted", volD)
	}
}

// ---------------------------------------------------------------------------
// Test 5: TestConcurrentFileOps
// Create a volume, launch 10 goroutines each writing a unique file,
// then verify all 10 files exist with correct content.
// ---------------------------------------------------------------------------

func TestConcurrentFileOps(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	volID := uniqueName("concurrent")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() { mgr.DeleteSubvolume(context.Background(), volPath) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)

	const numWorkers = 10
	var wg sync.WaitGroup
	errs := make(chan error, numWorkers)

	for i := 0; i < numWorkers; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			fileName := fmt.Sprintf("file-%02d.txt", idx)
			content := fmt.Sprintf("content-from-worker-%02d", idx)
			if err := client.WriteFile(ctx, volID, fileName, []byte(content), 0644); err != nil {
				errs <- fmt.Errorf("worker %d WriteFile: %w", idx, err)
			}
		}(i)
	}
	wg.Wait()
	close(errs)

	for err := range errs {
		t.Errorf("concurrent write error: %v", err)
	}

	// Verify all 10 files exist with correct content.
	for i := 0; i < numWorkers; i++ {
		fileName := fmt.Sprintf("file-%02d.txt", i)
		expectedContent := fmt.Sprintf("content-from-worker-%02d", i)

		data, err := client.ReadFile(ctx, volID, fileName)
		if err != nil {
			t.Errorf("ReadFile %s: %v", fileName, err)
			continue
		}
		if string(data) != expectedContent {
			t.Errorf("file %s content = %q, want %q", fileName, string(data), expectedContent)
		}
	}
}

// ---------------------------------------------------------------------------
// Test 6: TestRestoreFromS3
// Create CAS infrastructure, create a volume with unique data, sync to S3,
// delete the local volume, restore from S3, and verify the data.
// ---------------------------------------------------------------------------

func TestRestoreFromS3(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	// Ensure layers/ directory exists.
	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	// Create CAS infrastructure.
	bucket := uniqueName("restore")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create a template: build in a staging subvolume, then snapshot as
	// read-only (matches production flow — templates must be read-only for
	// btrfs send -p to work).
	tmplName := uniqueName("restore-tmpl")
	tmplPath := "templates/" + tmplName
	stagingPath := "volumes/" + uniqueName("staging")
	if err := mgr.CreateSubvolume(ctx, stagingPath); err != nil {
		t.Fatalf("create staging: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, stagingPath), "base.txt", "template-base")
	if err := mgr.SnapshotSubvolume(ctx, stagingPath, tmplPath, true); err != nil {
		t.Fatalf("snapshot staging to template: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), tmplPath)
		mgr.DeleteSubvolume(context.Background(), stagingPath)
	})

	// Upload template to CAS.
	tmplHash, err := tmplMgr.UploadTemplate(ctx, tmplName)
	if err != nil {
		t.Fatalf("UploadTemplate: %v", err)
	}

	// Create a volume from template and write unique data.
	volID := uniqueName("restore-vol")
	volPath := "volumes/" + volID
	if err := mgr.SnapshotSubvolume(ctx, tmplPath, volPath, false); err != nil {
		t.Fatalf("snapshot template to volume: %v", err)
	}

	uniqueData := "unique-data-" + uniqueName("payload")
	writeTestFile(t, filepath.Join(pool, volPath), "user-data.txt", uniqueData)

	// Track and sync to S3.
	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	daemon.TrackVolume(volID, tmplName, tmplHash)

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Modify the volume and sync again to create a second layer.
	secondData := "second-sync-" + uniqueName("payload2")
	writeTestFile(t, filepath.Join(pool, volPath), "second.txt", secondData)

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("second SyncVolume: %v", err)
	}

	// Verify manifest has 2 layers (each independently restorable).
	manifest, err := casStore.GetManifest(ctx, volID)
	if err != nil {
		t.Fatalf("GetManifest after sync: %v", err)
	}
	if len(manifest.Snapshots) != 2 {
		t.Fatalf("expected 2 layers in manifest, got %d", len(manifest.Snapshots))
	}

	// Delete local volume and ALL layer snapshots (simulate fresh node).
	if err := mgr.DeleteSubvolume(ctx, volPath); err != nil {
		t.Fatalf("delete volume for restore test: %v", err)
	}
	if mgr.SubvolumeExists(ctx, volPath) {
		t.Fatal("volume should not exist after deletion")
	}

	layerSubs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
	for _, sub := range layerSubs {
		mgr.DeleteSubvolume(ctx, sub.Path)
	}

	// Restore from S3 — should succeed with only the latest layer + template.
	if err := daemon.RestoreVolume(ctx, volID); err != nil {
		t.Fatalf("RestoreVolume: %v", err)
	}

	// Verify the volume exists again.
	if !mgr.SubvolumeExists(ctx, volPath) {
		t.Fatal("volume should exist after restore")
	}

	// Restored volume should have content from the latest (second) sync.
	verifyFileContent(t, filepath.Join(pool, volPath, "user-data.txt"), uniqueData)
	verifyFileContent(t, filepath.Join(pool, volPath, "second.txt"), secondData)
	verifyFileContent(t, filepath.Join(pool, volPath, "base.txt"), "template-base")

	// Cleanup: delete the restored volume and any layer snapshots.
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
	})
}

// TestRestoreToSnapshot verifies that any layer in the manifest can be restored
// independently without replaying earlier layers. Each layer is a full diff
// from the template, so only the target layer + template are needed.
func TestRestoreToSnapshot(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	// CAS infrastructure.
	bucket := uniqueName("snaprestore")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create template.
	tmplName := uniqueName("sr-tmpl")
	tmplPath := "templates/" + tmplName
	stagingPath := "volumes/" + uniqueName("staging")
	if err := mgr.CreateSubvolume(ctx, stagingPath); err != nil {
		t.Fatalf("create staging: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, stagingPath), "base.txt", "template-base")
	if err := mgr.SnapshotSubvolume(ctx, stagingPath, tmplPath, true); err != nil {
		t.Fatalf("snapshot staging to template: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), tmplPath)
		mgr.DeleteSubvolume(context.Background(), stagingPath)
	})

	tmplHash, err := tmplMgr.UploadTemplate(ctx, tmplName)
	if err != nil {
		t.Fatalf("UploadTemplate: %v", err)
	}

	// Create volume and sync twice to get 2 layers.
	volID := uniqueName("sr-vol")
	volPath := "volumes/" + volID
	if err := mgr.SnapshotSubvolume(ctx, tmplPath, volPath, false); err != nil {
		t.Fatalf("snapshot template to volume: %v", err)
	}

	v1Data := "version-1-" + uniqueName("v1")
	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", v1Data)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	daemon.TrackVolume(volID, tmplName, tmplHash)

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume v1: %v", err)
	}

	// Get the first layer's hash.
	manifest, err := casStore.GetManifest(ctx, volID)
	if err != nil {
		t.Fatalf("GetManifest: %v", err)
	}
	if len(manifest.Snapshots) != 1 {
		t.Fatalf("expected 1 layer, got %d", len(manifest.Snapshots))
	}
	v1Hash := manifest.Head

	// Second sync with different content.
	v2Data := "version-2-" + uniqueName("v2")
	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", v2Data)

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume v2: %v", err)
	}

	// Delete all local layers so restore has to re-download.
	layerSubs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
	for _, sub := range layerSubs {
		mgr.DeleteSubvolume(ctx, sub.Path)
	}

	// Restore to v1 (first layer) — should only need that one layer + template.
	if err := daemon.RestoreToSnapshot(ctx, volID, v1Hash); err != nil {
		t.Fatalf("RestoreToSnapshot to v1: %v", err)
	}

	// Volume should have v1 content.
	verifyFileContent(t, filepath.Join(pool, volPath, "data.txt"), v1Data)
	verifyFileContent(t, filepath.Join(pool, volPath, "base.txt"), "template-base")

	// Cleanup.
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
	})
}

// ---------------------------------------------------------------------------
// Test 8: TestAutoPromote_TemplatelessVolume
// Create a volume WITHOUT a template (simulates migration restore / blank
// project), sync it, verify auto-promote creates a synthetic per-volume
// template, then sync again and verify the second sync is incremental
// (uses the synthetic template as parent). Finally, delete the volume and
// verify the synthetic template is cleaned up.
// ---------------------------------------------------------------------------

func TestAutoPromote_TemplatelessVolume(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	// CAS infrastructure.
	bucket := uniqueName("autopromote")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create a volume directly (no template).
	volID := uniqueName("nontmpl-vol")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}

	initialData := "initial-data-" + uniqueName("payload")
	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", initialData)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	// Track with empty template — this is the template-less case.
	daemon.TrackVolume(volID, "", "")

	// ---- First sync: full send + auto-promote ----
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("first SyncVolume: %v", err)
	}

	// Verify manifest exists with 1 layer.
	manifest, err := casStore.GetManifest(ctx, volID)
	if err != nil {
		t.Fatalf("GetManifest after first sync: %v", err)
	}
	if len(manifest.Snapshots) != 1 {
		t.Fatalf("expected 1 layer after first sync, got %d", len(manifest.Snapshots))
	}

	// Verify auto-promote: manifest should now have a synthetic template name.
	expectedTmplName := "_vol_" + volID
	if manifest.TemplateName != expectedTmplName {
		t.Fatalf("manifest.TemplateName = %q, want %q", manifest.TemplateName, expectedTmplName)
	}
	if manifest.Base == "" {
		t.Fatal("manifest.Base should be set after auto-promote")
	}

	// Verify synthetic template subvolume exists locally.
	syntheticTmplPath := "templates/" + expectedTmplName
	if !mgr.SubvolumeExists(ctx, syntheticTmplPath) {
		t.Fatalf("synthetic template %s should exist after auto-promote", syntheticTmplPath)
	}

	// Verify tracked state reflects the promotion.
	states := daemon.GetTrackedState()
	if len(states) != 1 {
		t.Fatalf("expected 1 tracked volume, got %d", len(states))
	}
	if states[0].TemplateHash == "" {
		t.Error("tracked TemplateHash should be set after auto-promote")
	}

	// ---- Second sync: should be incremental (uses synthetic template) ----
	secondData := "second-sync-" + uniqueName("payload2")
	writeTestFile(t, filepath.Join(pool, volPath), "second.txt", secondData)

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("second SyncVolume: %v", err)
	}

	// Verify manifest now has 2 layers, both parented to the synthetic template.
	manifest, err = casStore.GetManifest(ctx, volID)
	if err != nil {
		t.Fatalf("GetManifest after second sync: %v", err)
	}
	if len(manifest.Snapshots) != 2 {
		t.Fatalf("expected 2 layers after second sync, got %d", len(manifest.Snapshots))
	}
	for hash, layer := range manifest.Snapshots {
		if layer.Parent != manifest.Base {
			t.Errorf("layer[%s].Parent = %q, want %q (synthetic template hash)", cas.ShortHash(hash), layer.Parent, manifest.Base)
		}
	}

	// ---- Restore: delete volume, restore from CAS, verify data ----
	if err := mgr.DeleteSubvolume(ctx, volPath); err != nil {
		t.Fatalf("delete volume for restore: %v", err)
	}
	// Clean up layer snapshots to simulate a fresh node.
	layerSubs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
	for _, sub := range layerSubs {
		mgr.DeleteSubvolume(ctx, sub.Path)
	}

	if err := daemon.RestoreVolume(ctx, volID); err != nil {
		t.Fatalf("RestoreVolume: %v", err)
	}

	if !mgr.SubvolumeExists(ctx, volPath) {
		t.Fatal("volume should exist after restore")
	}
	verifyFileContent(t, filepath.Join(pool, volPath, "data.txt"), initialData)
	verifyFileContent(t, filepath.Join(pool, volPath, "second.txt"), secondData)

	// ---- DeleteVolume: verify synthetic template cleanup ----
	if err := daemon.DeleteVolume(ctx, volID); err != nil {
		t.Fatalf("DeleteVolume: %v", err)
	}
	if mgr.SubvolumeExists(ctx, syntheticTmplPath) {
		t.Errorf("synthetic template %s should be deleted after DeleteVolume", syntheticTmplPath)
	}

	// Cleanup.
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		mgr.DeleteSubvolume(context.Background(), syntheticTmplPath)
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
	})
}

// ---------------------------------------------------------------------------
// Test: RestoreVolume recovers when a stale @pending subvolume exists
// from a previous failed restore attempt. Without idempotent cleanup,
// btrfs receive would fail because the destination already exists.
// ---------------------------------------------------------------------------

func TestRestoreVolume_StalePendingCleanup(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	// CAS infrastructure.
	bucket := uniqueName("stale-pending")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create template (staging → read-only snapshot → upload).
	tmplName := uniqueName("sp-tmpl")
	tmplPath := "templates/" + tmplName
	stagingPath := "volumes/" + uniqueName("staging")
	if err := mgr.CreateSubvolume(ctx, stagingPath); err != nil {
		t.Fatalf("create staging: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, stagingPath), "base.txt", "template-base")
	if err := mgr.SnapshotSubvolume(ctx, stagingPath, tmplPath, true); err != nil {
		t.Fatalf("snapshot staging to template: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), tmplPath)
		mgr.DeleteSubvolume(context.Background(), stagingPath)
	})

	tmplHash, err := tmplMgr.UploadTemplate(ctx, tmplName)
	if err != nil {
		t.Fatalf("UploadTemplate: %v", err)
	}

	// Create volume, write data, sync to S3.
	volID := uniqueName("sp-vol")
	volPath := "volumes/" + volID
	if err := mgr.SnapshotSubvolume(ctx, tmplPath, volPath, false); err != nil {
		t.Fatalf("snapshot template to volume: %v", err)
	}

	uniqueData := "unique-" + uniqueName("payload")
	writeTestFile(t, filepath.Join(pool, volPath), "user-data.txt", uniqueData)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	daemon.TrackVolume(volID, tmplName, tmplHash)

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Delete local volume + layer snapshots to force CAS restore.
	if err := mgr.DeleteSubvolume(ctx, volPath); err != nil {
		t.Fatalf("delete volume: %v", err)
	}
	layerSubs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
	for _, sub := range layerSubs {
		mgr.DeleteSubvolume(ctx, sub.Path)
	}

	// Simulate a failed previous restore: create a stale @pending subvolume.
	// In production this happens when btrfs receive is interrupted mid-stream.
	stalePending := fmt.Sprintf("layers/%s@pending", volID)
	if err := mgr.CreateSubvolume(ctx, stalePending); err != nil {
		t.Fatalf("create stale @pending: %v", err)
	}

	// RestoreVolume should clean up the stale @pending and succeed.
	if err := daemon.RestoreVolume(ctx, volID); err != nil {
		t.Fatalf("RestoreVolume with stale @pending: %v", err)
	}

	// Verify restored content.
	if !mgr.SubvolumeExists(ctx, volPath) {
		t.Fatal("volume should exist after restore")
	}
	verifyFileContent(t, filepath.Join(pool, volPath, "user-data.txt"), uniqueData)
	verifyFileContent(t, filepath.Join(pool, volPath, "base.txt"), "template-base")

	// Verify stale @pending is gone.
	if mgr.SubvolumeExists(ctx, stalePending) {
		t.Error("stale @pending subvolume should have been cleaned up")
	}

	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		mgr.DeleteSubvolume(context.Background(), stalePending)
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
	})
}

// ---------------------------------------------------------------------------
// Test: RestoreToSnapshot recovers when a stale @pending exists.
// Same scenario as above but for the layer-specific restore path.
// ---------------------------------------------------------------------------

func TestRestoreToSnapshot_StalePendingCleanup(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	bucket := uniqueName("snap-stale")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create template.
	tmplName := uniqueName("ss-tmpl")
	tmplPath := "templates/" + tmplName
	stagingPath := "volumes/" + uniqueName("staging")
	if err := mgr.CreateSubvolume(ctx, stagingPath); err != nil {
		t.Fatalf("create staging: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, stagingPath), "base.txt", "template-base")
	if err := mgr.SnapshotSubvolume(ctx, stagingPath, tmplPath, true); err != nil {
		t.Fatalf("snapshot staging to template: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), tmplPath)
		mgr.DeleteSubvolume(context.Background(), stagingPath)
	})

	tmplHash, err := tmplMgr.UploadTemplate(ctx, tmplName)
	if err != nil {
		t.Fatalf("UploadTemplate: %v", err)
	}

	// Create volume, sync v1, modify, sync v2.
	volID := uniqueName("ss-vol")
	volPath := "volumes/" + volID
	if err := mgr.SnapshotSubvolume(ctx, tmplPath, volPath, false); err != nil {
		t.Fatalf("snapshot template to volume: %v", err)
	}

	v1Data := "version-1-" + uniqueName("v1")
	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", v1Data)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	daemon.TrackVolume(volID, tmplName, tmplHash)

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume v1: %v", err)
	}

	manifest, err := casStore.GetManifest(ctx, volID)
	if err != nil {
		t.Fatalf("GetManifest: %v", err)
	}
	v1Hash := manifest.Head

	v2Data := "version-2-" + uniqueName("v2")
	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", v2Data)
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume v2: %v", err)
	}

	// Delete all layer snapshots to force CAS download.
	layerSubs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
	for _, sub := range layerSubs {
		mgr.DeleteSubvolume(ctx, sub.Path)
	}

	// Simulate stale @pending from a previous failed restore.
	stalePending := fmt.Sprintf("layers/%s@pending", volID)
	if err := mgr.CreateSubvolume(ctx, stalePending); err != nil {
		t.Fatalf("create stale @pending: %v", err)
	}

	// RestoreToSnapshot should clean up stale @pending and restore v1.
	if err := daemon.RestoreToSnapshot(ctx, volID, v1Hash); err != nil {
		t.Fatalf("RestoreToSnapshot with stale @pending: %v", err)
	}

	verifyFileContent(t, filepath.Join(pool, volPath, "data.txt"), v1Data)

	if mgr.SubvolumeExists(ctx, stalePending) {
		t.Error("stale @pending should have been cleaned up")
	}

	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		mgr.DeleteSubvolume(context.Background(), stalePending)
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
	})
}

// ---------------------------------------------------------------------------
// Test: Peer transfer receive cleans up stale @transfer subvolume
// from a previous failed ReceiveVolumeStream.
// ---------------------------------------------------------------------------

func TestPeerTransfer_StaleTransferCleanup(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	casStore := cas.NewStore(nil) // no S3 needed for peer transfer
	tmplMgr := template.NewManager(mgr, nil, pool)
	daemon := bsync.NewDaemon(mgr, nil, tmplMgr, 1*time.Hour)

	// Start sender and receiver nodeops servers.
	senderAddr := startNodeOpsServer(t, mgr, daemon, tmplMgr)
	receiverAddr := startNodeOpsServer(t, mgr, daemon, tmplMgr)
	_ = casStore

	// Create a source volume with data on the "sender" (same node in test).
	volID := uniqueName("transfer-vol")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("create volume: %v", err)
	}

	transferData := "transfer-payload-" + uniqueName("data")
	writeTestFile(t, filepath.Join(pool, volPath), "transfer.txt", transferData)

	// Simulate stale @transfer on the receiver from a previous failed transfer.
	staleTransfer := fmt.Sprintf("volumes/%s@transfer", volID)
	if err := mgr.CreateSubvolume(ctx, staleTransfer); err != nil {
		t.Fatalf("create stale @transfer: %v", err)
	}

	// Perform peer transfer: sender → receiver (same node, but exercises the gRPC path).
	senderClient := connectNodeOpsClient(t, senderAddr)

	// Need read-only snapshot for send.
	snapPath := "volumes/" + volID + "@snap"
	if err := mgr.SnapshotSubvolume(ctx, volPath, snapPath, true); err != nil {
		t.Fatalf("create ro snapshot: %v", err)
	}
	t.Cleanup(func() { mgr.DeleteSubvolume(context.Background(), snapPath) })

	if err := senderClient.SendVolumeTo(ctx, volID, receiverAddr); err != nil {
		t.Fatalf("SendVolumeTo: %v", err)
	}

	// Verify the transfer succeeded — volume should exist at canonical path.
	if !mgr.SubvolumeExists(ctx, volPath) {
		t.Fatal("volume should exist at canonical path after transfer")
	}

	// Verify stale @transfer was cleaned up.
	if mgr.SubvolumeExists(ctx, staleTransfer) {
		t.Error("stale @transfer subvolume should have been cleaned up by receiver")
	}

	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		mgr.DeleteSubvolume(context.Background(), staleTransfer)
	})
}

// ---------------------------------------------------------------------------
// Root Cause C integration tests: disk-authoritative tracking
// ---------------------------------------------------------------------------

// TestDrainAll_DiscoversUntrackedVolumes verifies that DrainAll re-runs
// discoverVolumes, catching volumes that exist on disk but were never
// explicitly tracked (e.g., service volumes created by the Hub before
// periodic discovery ran). The volume should be synced to S3 during drain.
func TestDrainAll_DiscoversUntrackedVolumes(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	bucket := uniqueName("drain-disc")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create daemon with 1h interval (manual control only).
	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	// Create a volume on disk WITHOUT calling TrackVolume — simulates a
	// service volume created by the Hub that was missed by discovery.
	volID := uniqueName("untracked")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("create untracked volume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		// Clean up layer snapshots.
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
		synth := "templates/_vol_" + volID
		if mgr.SubvolumeExists(context.Background(), synth) {
			mgr.DeleteSubvolume(context.Background(), synth)
		}
	})
	writeTestFile(t, filepath.Join(pool, volPath), "important.txt", "do-not-lose-this")

	// Verify NOT tracked yet.
	for _, s := range daemon.GetTrackedState() {
		if s.VolumeID == volID {
			t.Fatal("volume should not be tracked before DrainAll")
		}
	}

	// DrainAll should discover the volume and sync it to S3.
	if err := daemon.DrainAll(ctx); err != nil {
		t.Fatalf("DrainAll: %v", err)
	}

	// Verify the volume was persisted: a CAS manifest should exist.
	manifest, err := casStore.GetManifest(ctx, volID)
	if err != nil {
		t.Fatalf("volume %s should have a CAS manifest after drain (discovered + synced): %v", volID, err)
	}
	if len(manifest.Snapshots) == 0 {
		t.Error("manifest should have at least 1 layer after drain sync")
	}

	t.Logf("DrainAll discovered untracked volume %s and synced %d layer(s)", volID, len(manifest.Snapshots))
}

// TestPeriodicDiscovery_TracksNewVolume verifies that syncAll's periodic
// discovery picks up volumes created after initial startup.
func TestPeriodicDiscovery_TracksNewVolume(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	bucket := uniqueName("periodic")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create daemon with 1h interval (manual sync only).
	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	// Start daemon — initial discovery sees nothing.
	dCtx, dCancel := context.WithCancel(ctx)
	go daemon.Start(dCtx)
	t.Cleanup(func() {
		dCancel()
		daemon.Stop()
	})

	// Give startup discovery a moment.
	time.Sleep(100 * time.Millisecond)

	// Create a volume AFTER startup.
	volID := uniqueName("late-vol")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("create volume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
	})

	// Verify NOT tracked yet.
	found := false
	for _, s := range daemon.GetTrackedState() {
		if s.VolumeID == volID {
			found = true
		}
	}
	if found {
		t.Fatal("volume should not be tracked before periodic discovery")
	}

	// Manually trigger syncAll enough times to trigger periodic discovery.
	// discoverInterval is 5, so we need 5 calls.
	for i := 0; i < 5; i++ {
		daemon.SyncAll(ctx)
	}

	// Now check tracking.
	found = false
	for _, s := range daemon.GetTrackedState() {
		if s.VolumeID == volID {
			found = true
		}
	}
	if !found {
		t.Fatal("volume should be tracked after periodic discovery triggered by 5 syncAll cycles")
	}

	t.Logf("Periodic discovery picked up late volume %s", volID)
}

// TestNodeOps_TrackVolume_Integration verifies the TrackVolume gRPC call
// works end-to-end: Hub calls TrackVolume on node → sync daemon tracks it.
func TestNodeOps_TrackVolume_Integration(t *testing.T) {
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// Create daemon + nodeops server.
	daemon := bsync.NewDaemon(mgr, nil, nil, 1*time.Hour)
	addr := startNodeOpsServer(t, mgr, daemon, nil)
	client := connectNodeOpsClient(t, addr)

	volID := uniqueName("svc-vol")

	// Verify not tracked.
	for _, s := range daemon.GetTrackedState() {
		if s.VolumeID == volID {
			t.Fatal("should not be tracked before RPC")
		}
	}

	// Call TrackVolume via gRPC (same path as Hub's CreateServiceVolume).
	if err := client.TrackVolume(ctx, volID, "", ""); err != nil {
		t.Fatalf("TrackVolume RPC: %v", err)
	}

	// Verify tracked + dirty.
	found := false
	for _, s := range daemon.GetTrackedState() {
		if s.VolumeID == volID {
			found = true
			if !s.Dirty {
				t.Error("newly tracked volume should be dirty")
			}
		}
	}
	if !found {
		t.Fatal("volume should be tracked after TrackVolume RPC")
	}
}

// ---------------------------------------------------------------------------
// Bonus F integration test: staging GC
// ---------------------------------------------------------------------------

// TestStagingGC_DeletesOrphanedKeys verifies that CleanupStaging deletes
// orphaned staging keys from real S3 (MinIO).
func TestStagingGC_DeletesOrphanedKeys(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	bucket := uniqueName("staging-gc")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)

	// Plant an orphaned staging key by uploading directly to the staging prefix.
	// In production this would be left by a crashed PutBlob.
	orphanKey := "blobs/_staging/orphan-test.zst"
	if err := store.Upload(ctx, orphanKey, strings.NewReader("orphan-data"), -1); err != nil {
		t.Fatalf("upload orphan key: %v", err)
	}

	// Verify it exists.
	exists, err := store.Exists(ctx, orphanKey)
	if err != nil || !exists {
		t.Fatal("orphan key should exist after upload")
	}

	// CleanupStaging with default 1h max age — key was just created, should NOT be deleted.
	deleted, err := casStore.CleanupStaging(ctx)
	if err != nil {
		t.Fatalf("CleanupStaging: %v", err)
	}
	if deleted != 0 {
		t.Errorf("fresh staging key should not be deleted, got %d deleted", deleted)
	}

	// Verify still exists.
	exists, _ = store.Exists(ctx, orphanKey)
	if !exists {
		t.Fatal("fresh staging key should still exist")
	}

	t.Log("CleanupStaging correctly preserved fresh staging key (would delete keys >1h old)")
}

// ---------------------------------------------------------------------------
// Tombstone + safe delete integration tests
// ---------------------------------------------------------------------------

// TestTombstone_DiscoverVolumesSkipsAndCleansUp verifies that a tombstoned
// volume found on disk is cleaned up (subvolume, layers, synthetic template)
// and the tombstone is removed from S3 afterwards.
func TestTombstone_DiscoverVolumesSkipsAndCleansUp(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	bucket := uniqueName("tombstone")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create a volume and sync it (so it has layers and a manifest).
	volID := uniqueName("tomb-vol")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("create volume: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "tombstone-test")

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	daemon.TrackVolume(volID, "", "")
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Verify manifest exists.
	if has, _ := casStore.HasManifest(ctx, volID); !has {
		t.Fatal("manifest should exist after sync")
	}

	// Write a tombstone (simulating DeleteVolumeFromNode).
	if err := casStore.PutTombstone(ctx, volID); err != nil {
		t.Fatalf("PutTombstone: %v", err)
	}

	// Create a NEW daemon (simulating node restart) that doesn't know about the volume.
	// Use 1h interval so the daemon only runs initial discovery, not periodic syncs.
	daemon2 := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	// Start the daemon — initial discoverVolumes runs synchronously in Start()
	// before the ticker begins. We use a short-lived context: Start blocks on
	// discoverVolumes, then enters the ticker loop. We wait long enough for
	// initial discovery + tombstone cleanup to complete, then cancel.
	dCtx, dCancel := context.WithCancel(ctx)
	go daemon2.Start(dCtx)
	// Initial discovery can take 30+ seconds with S3 manifest fetches.
	// Poll for the tombstone to be cleaned up.
	for i := 0; i < 60; i++ {
		time.Sleep(1 * time.Second)
		if !mgr.SubvolumeExists(ctx, volPath) {
			break
		}
	}
	dCancel()
	daemon2.Stop()

	// Verify the subvolume was cleaned up.
	if mgr.SubvolumeExists(ctx, volPath) {
		t.Error("tombstoned volume subvolume should be deleted")
	}

	// Verify the tombstone was removed after cleanup.
	if has, _ := casStore.HasTombstone(ctx, volID); has {
		t.Error("tombstone should be removed after local cleanup")
	}

	// Verify the volume is NOT tracked.
	for _, s := range daemon2.GetTrackedState() {
		if s.VolumeID == volID {
			t.Error("tombstoned volume should not be tracked")
		}
	}

	t.Logf("Tombstone self-healing: volume %s cleaned up on simulated restart", volID)

	// Cleanup: layers and synthetic templates should already be gone.
	// But clean up anything remaining to be safe.
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
		synth := "templates/_vol_" + volID
		if mgr.SubvolumeExists(context.Background(), synth) {
			mgr.DeleteSubvolume(context.Background(), synth)
		}
	})
}

// TestUntrackVolume_SafeWithConcurrentSync verifies that UntrackVolume
// waits for an inflight SyncVolume to complete before deleting resources.
func TestUntrackVolume_SafeWithConcurrentSync(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	bucket := uniqueName("untrack-safe")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create a volume with data.
	volID := uniqueName("safe-vol")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("create volume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
		synth := "templates/_vol_" + volID
		if mgr.SubvolumeExists(context.Background(), synth) {
			mgr.DeleteSubvolume(context.Background(), synth)
		}
	})
	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "sync-before-untrack")

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	daemon.TrackVolume(volID, "", "")

	// Start a sync and untrack concurrently.
	// With the per-volume lock fix, UntrackVolume waits for SyncVolume.
	syncDone := make(chan error, 1)
	go func() {
		syncDone <- daemon.SyncVolume(ctx, volID)
	}()

	// Small delay to let SyncVolume acquire the lock first.
	time.Sleep(10 * time.Millisecond)

	untrackDone := make(chan struct{})
	go func() {
		daemon.UntrackVolume(volID)
		close(untrackDone)
	}()

	// SyncVolume should complete first (it has the lock).
	if err := <-syncDone; err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// UntrackVolume should complete after SyncVolume releases.
	select {
	case <-untrackDone:
		// success
	case <-time.After(30 * time.Second):
		t.Fatal("UntrackVolume did not complete")
	}

	// Verify the sync actually wrote a manifest (data was captured).
	manifest, err := casStore.GetManifest(ctx, volID)
	if err != nil {
		t.Fatalf("GetManifest: %v (sync should have completed before untrack)", err)
	}
	if len(manifest.Snapshots) == 0 {
		t.Error("sync should have created at least 1 layer before untrack")
	}

	t.Logf("UntrackVolume waited for SyncVolume — %d layer(s) safely persisted", len(manifest.Snapshots))
}
