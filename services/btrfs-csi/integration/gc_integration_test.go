//go:build integration

package integration

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/gc"
)

// --------------------------------------------------------------------------
// Orphaned subvolume cleanup
// --------------------------------------------------------------------------

func TestGC_CleanOrphanedSubvolumes(t *testing.T) {
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	volA := "volumes/" + uniqueName("gc-orphan-a")
	volB := "volumes/" + uniqueName("gc-orphan-b")
	volC := "volumes/" + uniqueName("gc-orphan-c")

	for _, v := range []string{volA, volB, volC} {
		if err := mgr.CreateSubvolume(ctx, v); err != nil {
			t.Fatalf("create %s: %v", v, err)
		}
		defer mgr.DeleteSubvolume(ctx, v) // safety net
	}

	// Write a file into each so they are non-empty.
	pool := getPoolPath(t)
	for _, v := range []string{volA, volB, volC} {
		writeTestFile(t, filepath.Join(pool, v), "data.txt", "payload-"+v)
	}

	// Discover the Name that btrfs returns for volA so the knownVolumes
	// map uses the right key.
	subs, err := mgr.ListSubvolumes(ctx, "volumes/")
	if err != nil {
		t.Fatalf("ListSubvolumes: %v", err)
	}

	// Build a lookup: path-basename -> sub.Name
	baseToName := make(map[string]string)
	for _, sub := range subs {
		baseToName[filepath.Base(sub.Path)] = sub.Name
	}

	keepName, ok := baseToName[filepath.Base(volA)]
	if !ok {
		// Fall back to the basename itself.
		keepName = filepath.Base(volA)
	}

	collector := gc.NewCollector(mgr, nil, gc.Config{
		GracePeriod: 0,
		DryRun:      false,
	})
	collector.SetKnownVolumesFunc(func(_ context.Context) (map[string]bool, error) {
		return map[string]bool{keepName: true}, nil
	})

	if err := collector.RunOnce(ctx); err != nil {
		t.Fatalf("RunOnce: %v", err)
	}

	// vol-a must survive.
	if !mgr.SubvolumeExists(ctx, volA) {
		t.Errorf("expected kept volume %s to still exist", volA)
	}

	// vol-b and vol-c should be deleted.
	for _, orphan := range []string{volB, volC} {
		if mgr.SubvolumeExists(ctx, orphan) {
			t.Errorf("expected orphan %s to be deleted", orphan)
		}
	}
}

// --------------------------------------------------------------------------
// Grace period (CreatedAt is zero → orphans are still deleted)
// --------------------------------------------------------------------------

func TestGC_GracePeriod(t *testing.T) {
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	volX := "volumes/" + uniqueName("gc-grace-x")
	volY := "volumes/" + uniqueName("gc-grace-y")

	for _, v := range []string{volX, volY} {
		if err := mgr.CreateSubvolume(ctx, v); err != nil {
			t.Fatalf("create %s: %v", v, err)
		}
		defer mgr.DeleteSubvolume(ctx, v)
	}

	collector := gc.NewCollector(mgr, nil, gc.Config{
		GracePeriod: 1 * time.Hour, // very long grace period
		DryRun:      false,
	})
	// Empty map → every volume is an orphan.
	collector.SetKnownVolumesFunc(func(_ context.Context) (map[string]bool, error) {
		return map[string]bool{}, nil
	})

	if err := collector.RunOnce(ctx); err != nil {
		t.Fatalf("RunOnce: %v", err)
	}

	// CreatedAt from btrfs subvolume list is zero for most entries, so the
	// grace-period check (!sub.CreatedAt.IsZero() && ...) evaluates to false
	// and orphans ARE deleted despite the long grace period.
	for _, v := range []string{volX, volY} {
		if mgr.SubvolumeExists(ctx, v) {
			t.Errorf("expected orphan %s to be deleted (zero CreatedAt bypasses grace period)", v)
		}
	}
}

// --------------------------------------------------------------------------
// Dry-run mode
// --------------------------------------------------------------------------

func TestGC_DryRun(t *testing.T) {
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	volP := "volumes/" + uniqueName("gc-dry-p")
	volQ := "volumes/" + uniqueName("gc-dry-q")

	for _, v := range []string{volP, volQ} {
		if err := mgr.CreateSubvolume(ctx, v); err != nil {
			t.Fatalf("create %s: %v", v, err)
		}
		defer mgr.DeleteSubvolume(ctx, v)
	}

	collector := gc.NewCollector(mgr, nil, gc.Config{
		GracePeriod: 0,
		DryRun:      true,
	})
	collector.SetKnownVolumesFunc(func(_ context.Context) (map[string]bool, error) {
		return map[string]bool{}, nil // all are orphans
	})

	if err := collector.RunOnce(ctx); err != nil {
		t.Fatalf("RunOnce: %v", err)
	}

	// Dry-run must not delete anything.
	for _, v := range []string{volP, volQ} {
		if !mgr.SubvolumeExists(ctx, v) {
			t.Errorf("expected volume %s to survive dry run", v)
		}
	}
}

// --------------------------------------------------------------------------
// Orphaned S3 snapshot cleanup
// --------------------------------------------------------------------------

func TestGC_CleanOrphanedS3Snapshots(t *testing.T) {
	mgr := newBtrfsManager(t)
	ctx := context.Background()
	bucket := uniqueName("gc-s3")
	s3c := newS3Client(t, bucket)

	// Upload S3 objects for three "volumes".
	volIDs := []string{
		uniqueName("s3vol-a"),
		uniqueName("s3vol-b"),
		uniqueName("s3vol-c"),
	}
	for _, vid := range volIDs {
		key := "volumes/" + vid + "/full-test.zst"
		if err := s3c.Upload(ctx, key, bytes.NewReader([]byte("test")), 4); err != nil {
			t.Fatalf("upload %s: %v", key, err)
		}
	}

	// Only volIDs[0] is "known"; the other two are orphans.
	collector := gc.NewCollector(mgr, s3c, gc.Config{
		GracePeriod: 0,
		DryRun:      false,
	})
	collector.SetKnownVolumesFunc(func(_ context.Context) (map[string]bool, error) {
		return map[string]bool{volIDs[0]: true}, nil
	})

	if err := collector.RunOnce(ctx); err != nil {
		t.Fatalf("RunOnce: %v", err)
	}

	// Kept volume's object must still exist.
	exists, err := s3c.Exists(ctx, "volumes/"+volIDs[0]+"/full-test.zst")
	if err != nil {
		t.Fatalf("Exists check: %v", err)
	}
	if !exists {
		t.Errorf("expected S3 object for kept volume %s to remain", volIDs[0])
	}

	// Orphan volumes' objects must be gone.
	for _, vid := range volIDs[1:] {
		exists, err := s3c.Exists(ctx, "volumes/"+vid+"/full-test.zst")
		if err != nil {
			t.Fatalf("Exists check: %v", err)
		}
		if exists {
			t.Errorf("expected S3 object for orphan volume %s to be deleted", vid)
		}
	}
}

// --------------------------------------------------------------------------
// Stale local snapshot cleanup
// --------------------------------------------------------------------------

func TestGC_CleanStaleLocalSnapshots(t *testing.T) {
	mgr := newBtrfsManager(t)
	ctx := context.Background()
	pool := getPoolPath(t)

	// We need a source subvolume to snapshot from.
	srcName := "volumes/" + uniqueName("gc-snap-src")
	if err := mgr.CreateSubvolume(ctx, srcName); err != nil {
		t.Fatalf("create source: %v", err)
	}
	defer mgr.DeleteSubvolume(ctx, srcName)

	// Create snapshot subvolumes with different name patterns.
	syncSnap := "snapshots/" + uniqueName("vol1") + "@sync-new"
	tmplSnap := "snapshots/" + uniqueName("tmpl1") + "-tmpl-upload"
	staleSnap1 := "snapshots/" + uniqueName("old-snap-1")
	staleSnap2 := "snapshots/" + uniqueName("old-snap-2")

	allSnaps := []string{syncSnap, tmplSnap, staleSnap1, staleSnap2}
	for _, s := range allSnaps {
		if err := mgr.SnapshotSubvolume(ctx, srcName, s, false); err != nil {
			t.Fatalf("create snapshot %s: %v", s, err)
		}
		defer mgr.DeleteSubvolume(ctx, s)
	}

	collector := gc.NewCollector(mgr, nil, gc.Config{
		GracePeriod: 0,
		DryRun:      false,
	})
	// knownVolumes can be nil; stale snapshot cleanup doesn't use it.

	if err := collector.RunOnce(ctx); err != nil {
		t.Fatalf("RunOnce: %v", err)
	}

	// Active sync and template upload snapshots must be preserved.
	for _, preserved := range []string{syncSnap, tmplSnap} {
		if !mgr.SubvolumeExists(ctx, preserved) {
			// Also check on disk in case SubvolumeExists relies on btrfs list.
			if _, statErr := os.Stat(filepath.Join(pool, preserved)); statErr != nil {
				t.Errorf("expected snapshot %s to be preserved", preserved)
			}
		}
	}

	// Stale snapshots must be deleted.
	for _, stale := range []string{staleSnap1, staleSnap2} {
		if mgr.SubvolumeExists(ctx, stale) {
			t.Errorf("expected stale snapshot %s to be deleted", stale)
		}
	}
}

// --------------------------------------------------------------------------
// Full GC cycle: volumes + S3 + stale snapshots
// --------------------------------------------------------------------------

func TestGC_FullCycle(t *testing.T) {
	mgr := newBtrfsManager(t)
	ctx := context.Background()
	pool := getPoolPath(t)
	bucket := uniqueName("gc-full")
	s3c := newS3Client(t, bucket)

	// --- Volumes ---
	keptVol := "volumes/" + uniqueName("gc-full-keep")
	orphanVol := "volumes/" + uniqueName("gc-full-orphan")
	for _, v := range []string{keptVol, orphanVol} {
		if err := mgr.CreateSubvolume(ctx, v); err != nil {
			t.Fatalf("create %s: %v", v, err)
		}
		defer mgr.DeleteSubvolume(ctx, v)
		writeTestFile(t, filepath.Join(pool, v), "f.txt", "data")
	}

	// Discover btrfs names.
	subs, err := mgr.ListSubvolumes(ctx, "volumes/")
	if err != nil {
		t.Fatalf("ListSubvolumes: %v", err)
	}
	baseToName := make(map[string]string)
	for _, sub := range subs {
		baseToName[filepath.Base(sub.Path)] = sub.Name
	}
	keepName := baseToName[filepath.Base(keptVol)]
	if keepName == "" {
		keepName = filepath.Base(keptVol)
	}

	// --- S3 objects ---
	keptS3Vol := uniqueName("s3-keep")
	orphanS3Vol := uniqueName("s3-orphan")
	for _, vid := range []string{keptS3Vol, orphanS3Vol} {
		key := "volumes/" + vid + "/full-snap.zst"
		if err := s3c.Upload(ctx, key, bytes.NewReader([]byte("data")), 4); err != nil {
			t.Fatalf("upload %s: %v", key, err)
		}
	}

	// --- Stale local snapshots ---
	srcForSnaps := "volumes/" + uniqueName("gc-full-src")
	if err := mgr.CreateSubvolume(ctx, srcForSnaps); err != nil {
		t.Fatalf("create snap source: %v", err)
	}
	defer mgr.DeleteSubvolume(ctx, srcForSnaps)

	preservedSnap := "snapshots/" + uniqueName("active") + "@sync-new"
	staleSnap := "snapshots/" + uniqueName("stale-snap")
	for _, s := range []string{preservedSnap, staleSnap} {
		if err := mgr.SnapshotSubvolume(ctx, srcForSnaps, s, false); err != nil {
			t.Fatalf("create snapshot %s: %v", s, err)
		}
		defer mgr.DeleteSubvolume(ctx, s)
	}

	// --- Run GC ---
	collector := gc.NewCollector(mgr, s3c, gc.Config{
		GracePeriod: 0,
		DryRun:      false,
	})
	collector.SetKnownVolumesFunc(func(_ context.Context) (map[string]bool, error) {
		return map[string]bool{
			keepName:   true,
			keptS3Vol:  true,
		}, nil
	})

	if err := collector.RunOnce(ctx); err != nil {
		t.Fatalf("RunOnce: %v", err)
	}

	// --- Verify volumes ---
	if !mgr.SubvolumeExists(ctx, keptVol) {
		t.Error("kept volume should still exist")
	}
	if mgr.SubvolumeExists(ctx, orphanVol) {
		t.Error("orphan volume should be deleted")
	}

	// --- Verify S3 ---
	exists, err := s3c.Exists(ctx, "volumes/"+keptS3Vol+"/full-snap.zst")
	if err != nil {
		t.Fatalf("S3 Exists: %v", err)
	}
	if !exists {
		t.Error("kept S3 object should still exist")
	}

	exists, err = s3c.Exists(ctx, "volumes/"+orphanS3Vol+"/full-snap.zst")
	if err != nil {
		t.Fatalf("S3 Exists: %v", err)
	}
	if exists {
		t.Error("orphan S3 object should be deleted")
	}

	// --- Verify snapshots ---
	if !mgr.SubvolumeExists(ctx, preservedSnap) {
		// Double-check on disk.
		if _, statErr := os.Stat(filepath.Join(pool, preservedSnap)); statErr != nil {
			t.Error("active sync snapshot should be preserved")
		}
	}
	if mgr.SubvolumeExists(ctx, staleSnap) {
		t.Error("stale snapshot should be deleted")
	}

}
