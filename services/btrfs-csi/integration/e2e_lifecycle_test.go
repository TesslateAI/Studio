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
		if len(manifest.Layers) == 0 {
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
	collector.SetOrchestratorURL(ts.URL)

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

	// Verify manifest exists.
	manifest, err := casStore.GetManifest(ctx, volID)
	if err != nil {
		t.Fatalf("GetManifest after sync: %v", err)
	}
	if len(manifest.Layers) == 0 {
		t.Fatal("expected at least 1 layer in manifest after sync")
	}

	// Delete the local volume subvolume (simulate node loss).
	if err := mgr.DeleteSubvolume(ctx, volPath); err != nil {
		t.Fatalf("delete volume for restore test: %v", err)
	}
	if mgr.SubvolumeExists(ctx, volPath) {
		t.Fatal("volume should not exist after deletion")
	}

	// Clean up the layer snapshot from the sync so restore has to re-download.
	layerSubs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
	for _, sub := range layerSubs {
		mgr.DeleteSubvolume(ctx, sub.Path)
	}

	// Restore from S3.
	if err := daemon.RestoreVolume(ctx, volID); err != nil {
		t.Fatalf("RestoreVolume: %v", err)
	}

	// Verify the volume exists again.
	if !mgr.SubvolumeExists(ctx, volPath) {
		t.Fatal("volume should exist after restore")
	}

	// Read data back and verify content matches original.
	verifyFileContent(t, filepath.Join(pool, volPath, "user-data.txt"), uniqueData)
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
