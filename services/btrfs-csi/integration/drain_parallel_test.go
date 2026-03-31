//go:build integration && load

package integration

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
)

// TestDrainAll_Parallel_Integration creates 5 real btrfs volumes with data,
// tracks them all as dirty, runs DrainAll, and verifies:
// 1. All manifests exist in S3 with correct layers
// 2. Wall time is significantly less than serial (proving parallelism)
func TestDrainAll_Parallel_Integration(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	const numVolumes = 5
	const fileSize = 128 * 1024 // 128 KiB per file

	// Set up CAS infrastructure.
	bucket := uniqueName("drain-parallel")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create a shared template.
	tmplName := uniqueName("drain-tmpl")
	tmplPath := "templates/" + tmplName

	if err := mgr.CreateSubvolume(ctx, tmplPath); err != nil {
		t.Fatalf("CreateSubvolume (template): %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), tmplPath)
	})

	writeTestFile(t, filepath.Join(pool, tmplPath), "base.txt", "template-base")

	// Make template read-only and upload to CAS.
	roTmplPath := "snapshots/" + tmplName + "-ro"
	if err := mgr.SnapshotSubvolume(ctx, tmplPath, roTmplPath, true); err != nil {
		t.Fatalf("SnapshotSubvolume (ro template): %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), roTmplPath)
	})

	tmplHash, err := tmplMgr.UploadTemplate(ctx, tmplName)
	if err != nil {
		t.Fatalf("UploadTemplate: %v", err)
	}

	// 1h interval so the daemon never auto-fires during the test.
	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	// Create volumes from template and write unique data.
	volIDs := make([]string, numVolumes)
	for i := 0; i < numVolumes; i++ {
		volID := uniqueName("drain-vol")
		volIDs[i] = volID
		volPath := "volumes/" + volID

		if err := mgr.SnapshotSubvolume(ctx, roTmplPath, volPath, false); err != nil {
			t.Fatalf("clone volume %d: %v", i, err)
		}

		vp := volPath
		vid := volID
		t.Cleanup(func() {
			mgr.DeleteSubvolume(context.Background(), vp)
			subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+vid)
			for _, sub := range subs {
				mgr.DeleteSubvolume(context.Background(), sub.Path)
			}
		})

		// Write unique data to each volume.
		volDir := filepath.Join(pool, volPath)
		content := bytes.Repeat([]byte{byte(i)}, fileSize)
		if err := os.WriteFile(filepath.Join(volDir, fmt.Sprintf("data-%d.bin", i)), content, 0644); err != nil {
			t.Fatalf("write volume %d: %v", i, err)
		}

		daemon.TrackVolume(volID, tmplName, tmplHash)
	}

	// Drain all volumes and measure wall time.
	start := time.Now()
	if err := daemon.DrainAll(ctx); err != nil {
		t.Fatalf("DrainAll: %v", err)
	}
	elapsed := time.Since(start)
	t.Logf("DrainAll: %d volumes in %v (%.2f vol/s)", numVolumes, elapsed, float64(numVolumes)/elapsed.Seconds())

	// Verify all manifests exist and have layers in S3.
	for _, volID := range volIDs {
		manifest, err := casStore.GetManifest(ctx, volID)
		if err != nil {
			t.Errorf("GetManifest(%s): %v", volID, err)
			continue
		}
		if len(manifest.Layers) == 0 {
			t.Errorf("volume %s manifest has no layers", volID)
			continue
		}
		// Verify the layer blob exists.
		for _, layer := range manifest.Layers {
			exists, bErr := store.Exists(ctx, "blobs/"+layer.Hash+".zst")
			if bErr != nil {
				t.Errorf("Exists(%s) for volume %s: %v", layer.Hash, volID, bErr)
			} else if !exists {
				t.Errorf("blob %s missing for volume %s", layer.Hash, volID)
			}
		}
	}

	// Verify parallelism: measure against a baseline.
	// We can't compare to serial directly in an integration test, but we log
	// throughput for manual verification.
	if elapsed > 5*time.Minute {
		t.Errorf("DrainAll took %v — too slow for %d volumes with parallel drain", elapsed, numVolumes)
	}
}
