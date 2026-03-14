//go:build integration

package integration

import (
	"context"
	"path/filepath"
	"strings"
	"testing"
	"time"

	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
)

// --------------------------------------------------------------------------
// Sync daemon integration tests
// --------------------------------------------------------------------------

// TestSync_FullCycle creates a volume, syncs it to S3, and verifies that a
// full snapshot object was uploaded.
func TestSync_FullCycle(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	bucket := uniqueName("sync-full")
	s3c := newS3Client(t, bucket)

	// 1h interval so the daemon never auto-fires during the test.
	daemon := bsync.NewDaemon(mgr, s3c, 1*time.Hour)

	volID := uniqueName("sync")
	volPath := "volumes/" + volID
	snapPath := "snapshots/" + volID + "@sync-new"

	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		mgr.DeleteSubvolume(context.Background(), snapPath)
	})

	writeTestFile(t, filepath.Join(pool, volPath), "testfile.txt", "full-cycle-data")

	daemon.TrackVolume(volID)

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	keys, err := daemon.ListS3Objects(ctx, "volumes/"+volID+"/")
	if err != nil {
		t.Fatalf("ListS3Objects: %v", err)
	}
	if len(keys) < 1 {
		t.Fatalf("expected at least 1 S3 object, got %d", len(keys))
	}
	if !strings.Contains(keys[0], "full-") {
		t.Errorf("expected first key to contain 'full-', got %q", keys[0])
	}
	t.Logf("Uploaded S3 key: %s", keys[0])
}

// TestSync_IncrementalSync verifies that a second sync produces an
// incremental snapshot rather than another full snapshot.
func TestSync_IncrementalSync(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	bucket := uniqueName("sync-incr")
	s3c := newS3Client(t, bucket)
	daemon := bsync.NewDaemon(mgr, s3c, 1*time.Hour)

	volID := uniqueName("sync")
	volPath := "volumes/" + volID
	snapPath := "snapshots/" + volID + "@sync-new"

	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		mgr.DeleteSubvolume(context.Background(), snapPath)
	})

	writeTestFile(t, filepath.Join(pool, volPath), "file1.txt", "first")
	daemon.TrackVolume(volID)

	// First sync: full.
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("first SyncVolume: %v", err)
	}

	// Write more data and sync again: incremental.
	writeTestFile(t, filepath.Join(pool, volPath), "file2.txt", "second")

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("second SyncVolume: %v", err)
	}

	keys, err := daemon.ListS3Objects(ctx, "volumes/"+volID+"/")
	if err != nil {
		t.Fatalf("ListS3Objects: %v", err)
	}
	if len(keys) != 2 {
		t.Fatalf("expected 2 S3 objects, got %d: %v", len(keys), keys)
	}

	var hasFull, hasIncremental bool
	for _, k := range keys {
		if strings.Contains(k, "full-") {
			hasFull = true
		}
		if strings.Contains(k, "incremental-") {
			hasIncremental = true
		}
	}
	if !hasFull {
		t.Error("expected one key containing 'full-'")
	}
	if !hasIncremental {
		t.Error("expected one key containing 'incremental-'")
	}
	t.Logf("S3 keys: %v", keys)
}

// TestSync_RestoreFromS3 syncs a volume to S3, deletes it locally, then
// restores from S3 using an explicit key and verifies file content.
func TestSync_RestoreFromS3(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	bucket := uniqueName("sync-rest")
	s3c := newS3Client(t, bucket)
	daemon := bsync.NewDaemon(mgr, s3c, 1*time.Hour)

	volID := uniqueName("sync")
	volPath := "volumes/" + volID
	snapPath := "snapshots/" + volID + "@sync-new"
	// After restore, btrfs receive creates the subvolume with the snapshot
	// basename, which is "{volID}@sync-new", inside the "volumes" directory.
	restoredPath := "volumes/" + volID + "@sync-new"

	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		mgr.DeleteSubvolume(context.Background(), snapPath)
		mgr.DeleteSubvolume(context.Background(), restoredPath)
	})

	writeTestFile(t, filepath.Join(pool, volPath), "testfile.txt", "restore-me")

	daemon.TrackVolume(volID)
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Get the S3 key that was uploaded.
	keys, err := daemon.ListS3Objects(ctx, "volumes/"+volID+"/")
	if err != nil {
		t.Fatalf("ListS3Objects: %v", err)
	}
	if len(keys) == 0 {
		t.Fatal("no S3 objects found after sync")
	}
	s3Key := keys[0]

	// Delete local volume and sync snapshot.
	if err := mgr.DeleteSubvolume(ctx, volPath); err != nil {
		t.Fatalf("delete volume: %v", err)
	}
	if err := mgr.DeleteSubvolume(ctx, snapPath); err != nil {
		t.Fatalf("delete sync snapshot: %v", err)
	}

	// Restore using the explicit S3 key.
	if err := daemon.RestoreFromS3(ctx, volID, s3Key); err != nil {
		t.Fatalf("RestoreFromS3: %v", err)
	}

	// Verify file content in the restored subvolume.
	verifyFileContent(t, filepath.Join(pool, restoredPath, "testfile.txt"), "restore-me")
}

// TestSync_RestoreFromS3_AutoDiscover syncs a volume, deletes it locally,
// then restores with an empty s3Key to trigger auto-discovery.
func TestSync_RestoreFromS3_AutoDiscover(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	bucket := uniqueName("sync-auto")
	s3c := newS3Client(t, bucket)
	daemon := bsync.NewDaemon(mgr, s3c, 1*time.Hour)

	volID := uniqueName("sync")
	volPath := "volumes/" + volID
	snapPath := "snapshots/" + volID + "@sync-new"
	restoredPath := "volumes/" + volID + "@sync-new"

	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		mgr.DeleteSubvolume(context.Background(), snapPath)
		mgr.DeleteSubvolume(context.Background(), restoredPath)
	})

	writeTestFile(t, filepath.Join(pool, volPath), "autofile.txt", "auto-discover-data")

	daemon.TrackVolume(volID)
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Delete local volume and sync snapshot.
	if err := mgr.DeleteSubvolume(ctx, volPath); err != nil {
		t.Fatalf("delete volume: %v", err)
	}
	if err := mgr.DeleteSubvolume(ctx, snapPath); err != nil {
		t.Fatalf("delete sync snapshot: %v", err)
	}

	// Restore with auto-discovery (empty s3Key).
	if err := daemon.RestoreFromS3(ctx, volID, ""); err != nil {
		t.Fatalf("RestoreFromS3 auto-discover: %v", err)
	}

	verifyFileContent(t, filepath.Join(pool, restoredPath, "autofile.txt"), "auto-discover-data")
}

// TestSync_SyncAll_MultipleVolumes tracks three volumes, syncs each one
// individually, and verifies all three have S3 objects.
func TestSync_SyncAll_MultipleVolumes(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	bucket := uniqueName("sync-multi")
	s3c := newS3Client(t, bucket)
	daemon := bsync.NewDaemon(mgr, s3c, 1*time.Hour)

	const count = 3
	volIDs := make([]string, count)
	for i := 0; i < count; i++ {
		volIDs[i] = uniqueName("sync")
		volPath := "volumes/" + volIDs[i]
		snapPath := "snapshots/" + volIDs[i] + "@sync-new"

		if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
			t.Fatalf("CreateSubvolume %d: %v", i, err)
		}

		// Capture loop vars for cleanup.
		vp, sp := volPath, snapPath
		t.Cleanup(func() {
			mgr.DeleteSubvolume(context.Background(), vp)
			mgr.DeleteSubvolume(context.Background(), sp)
		})

		writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "vol-"+volIDs[i])
		daemon.TrackVolume(volIDs[i])
	}

	// Sync each volume individually (syncAll is private).
	for _, id := range volIDs {
		if err := daemon.SyncVolume(ctx, id); err != nil {
			t.Fatalf("SyncVolume(%s): %v", id, err)
		}
	}

	// Verify each volume has at least one S3 object.
	for _, id := range volIDs {
		keys, err := daemon.ListS3Objects(ctx, "volumes/"+id+"/")
		if err != nil {
			t.Fatalf("ListS3Objects(%s): %v", id, err)
		}
		if len(keys) < 1 {
			t.Errorf("volume %s: expected at least 1 S3 object, got %d", id, len(keys))
		}
		t.Logf("volume %s: %d S3 objects", id, len(keys))
	}
}

// TestSync_ListS3Objects performs a full sync then an incremental sync and
// verifies ListS3Objects returns both keys with the correct prefixes.
func TestSync_ListS3Objects(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	bucket := uniqueName("sync-list")
	s3c := newS3Client(t, bucket)
	daemon := bsync.NewDaemon(mgr, s3c, 1*time.Hour)

	volID := uniqueName("sync")
	volPath := "volumes/" + volID
	snapPath := "snapshots/" + volID + "@sync-new"

	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		mgr.DeleteSubvolume(context.Background(), snapPath)
	})

	// First sync (full).
	writeTestFile(t, filepath.Join(pool, volPath), "a.txt", "aaa")
	daemon.TrackVolume(volID)

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("first SyncVolume: %v", err)
	}

	// Second sync (incremental).
	writeTestFile(t, filepath.Join(pool, volPath), "b.txt", "bbb")

	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("second SyncVolume: %v", err)
	}

	keys, err := daemon.ListS3Objects(ctx, "volumes/"+volID+"/")
	if err != nil {
		t.Fatalf("ListS3Objects: %v", err)
	}
	if len(keys) != 2 {
		t.Fatalf("expected 2 S3 keys, got %d: %v", len(keys), keys)
	}

	var hasFull, hasIncremental bool
	for _, k := range keys {
		if strings.Contains(k, "full-") {
			hasFull = true
		}
		if strings.Contains(k, "incremental-") {
			hasIncremental = true
		}
	}
	if !hasFull {
		t.Errorf("no key with 'full-' found in %v", keys)
	}
	if !hasIncremental {
		t.Errorf("no key with 'incremental-' found in %v", keys)
	}
}
