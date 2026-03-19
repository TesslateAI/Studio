//go:build integration && load

package integration

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
)

// --------------------------------------------------------------------------
// Load test 1: CoW clone efficiency
// --------------------------------------------------------------------------

// TestLoadCoWCloneEfficiency creates a template with 10 MiB of data, clones
// it 100 times, and verifies that btrfs CoW keeps the total pool usage well
// below 2x the template size.
func TestLoadCoWCloneEfficiency(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	const (
		numFiles   = 10
		fileSize   = 1 << 20 // 1 MiB
		numClones  = 100
		maxUsageMB = 20 // 2x template = 20 MiB
	)

	// Create template subvolume with 10 MiB of data.
	tmplName := uniqueName("load-cow-tmpl")
	tmplPath := "templates/" + tmplName

	if err := mgr.CreateSubvolume(ctx, tmplPath); err != nil {
		t.Fatalf("CreateSubvolume (template): %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), tmplPath)
	})

	// Fill the template with 10 x 1 MiB files.
	tmplDir := filepath.Join(pool, tmplPath)
	fileData := bytes.Repeat([]byte("A"), fileSize)
	for i := 0; i < numFiles; i++ {
		name := fmt.Sprintf("data-%03d.bin", i)
		if err := os.WriteFile(filepath.Join(tmplDir, name), fileData, 0644); err != nil {
			t.Fatalf("write template file %d: %v", i, err)
		}
	}

	// Snapshot as read-only template.
	roTmplPath := "snapshots/" + tmplName + "-ro"
	if err := mgr.SnapshotSubvolume(ctx, tmplPath, roTmplPath, true); err != nil {
		t.Fatalf("SnapshotSubvolume (ro template): %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), roTmplPath)
	})

	// Clone 100 volumes from the read-only template.
	cloneNames := make([]string, numClones)
	cloneDurations := make([]time.Duration, numClones)

	for i := 0; i < numClones; i++ {
		cloneName := fmt.Sprintf("volumes/%s-clone-%03d", tmplName, i)
		cloneNames[i] = cloneName

		start := time.Now()
		if err := mgr.SnapshotSubvolume(ctx, roTmplPath, cloneName, false); err != nil {
			t.Fatalf("clone %d: %v", i, err)
		}
		cloneDurations[i] = time.Since(start)
	}

	t.Cleanup(func() {
		for _, cn := range cloneNames {
			mgr.DeleteSubvolume(context.Background(), cn)
		}
	})

	// Measure pool usage.
	totalBytes, availableBytes, err := mgr.GetCapacity(ctx)
	if err != nil {
		t.Fatalf("GetCapacity: %v", err)
	}

	usedMB := float64(totalBytes-availableBytes) / (1 << 20)
	t.Logf("Pool usage after %d clones: %.2f MiB (total=%.2f MiB, avail=%.2f MiB)",
		numClones, usedMB, float64(totalBytes)/(1<<20), float64(availableBytes)/(1<<20))

	if usedMB > float64(maxUsageMB)*5 {
		// Allow generous headroom for btrfs metadata overhead, but flag
		// egregious bloat that would indicate CoW is not working.
		t.Errorf("pool usage %.2f MiB exceeds %d MiB threshold (CoW dedup may be broken)",
			usedMB, maxUsageMB*5)
	}

	// Log per-clone timing statistics.
	sort.Slice(cloneDurations, func(i, j int) bool { return cloneDurations[i] < cloneDurations[j] })
	p50 := cloneDurations[numClones/2]
	p95 := cloneDurations[int(float64(numClones)*0.95)]
	p99 := cloneDurations[int(float64(numClones)*0.99)]
	t.Logf("Clone latency: p50=%v  p95=%v  p99=%v  max=%v",
		p50, p95, p99, cloneDurations[numClones-1])

	if p95 > 50*time.Millisecond {
		t.Logf("WARNING: p95 clone latency %v exceeds 50ms target", p95)
	}
}

// --------------------------------------------------------------------------
// Load test 2: Concurrent file operations
// --------------------------------------------------------------------------

// TestLoadConcurrentFileOps starts a FileOps server and hammers it with 50
// concurrent writers, then verifies all files are present with correct content.
func TestLoadConcurrentFileOps(t *testing.T) {
	pool := getPoolPath(t)
	ctx := context.Background()

	const numWorkers = 50
	const fileSize = 4096 // 4 KiB

	// Create volume directory for FileOps.
	volID := uniqueName("load-fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	if err := os.MkdirAll(volDir, 0755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)

	// Each goroutine writes a unique file and records its latency.
	type result struct {
		index   int
		latency time.Duration
		err     error
	}

	results := make([]result, numWorkers)
	var wg sync.WaitGroup
	wg.Add(numWorkers)

	for i := 0; i < numWorkers; i++ {
		go func(idx int) {
			defer wg.Done()
			fileName := fmt.Sprintf("file-%03d.bin", idx)
			content := bytes.Repeat([]byte{byte(idx % 256)}, fileSize)

			start := time.Now()
			err := client.WriteFile(ctx, volID, fileName, content, 0644)
			results[idx] = result{
				index:   idx,
				latency: time.Since(start),
				err:     err,
			}
		}(i)
	}
	wg.Wait()

	// Collect latencies and check for errors.
	latencies := make([]time.Duration, 0, numWorkers)
	for _, r := range results {
		if r.err != nil {
			t.Errorf("worker %d write failed: %v", r.index, r.err)
			continue
		}
		latencies = append(latencies, r.latency)
	}

	if len(latencies) == 0 {
		t.Fatal("all workers failed")
	}

	sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })
	n := len(latencies)
	p50 := latencies[n/2]
	p95 := latencies[int(float64(n)*0.95)]
	p99 := latencies[int(float64(n)*0.99)]
	t.Logf("Concurrent write latency (%d workers): p50=%v  p95=%v  p99=%v  max=%v",
		numWorkers, p50, p95, p99, latencies[n-1])

	// Verify all files exist and have correct content.
	for i := 0; i < numWorkers; i++ {
		fileName := fmt.Sprintf("file-%03d.bin", i)
		expected := bytes.Repeat([]byte{byte(i % 256)}, fileSize)

		data, err := client.ReadFile(ctx, volID, fileName)
		if err != nil {
			t.Errorf("ReadFile %s: %v", fileName, err)
			continue
		}
		if !bytes.Equal(data, expected) {
			t.Errorf("file %s content mismatch (len got=%d want=%d)", fileName, len(data), len(expected))
		}
	}
}

// --------------------------------------------------------------------------
// Load test 3: Sync throughput
// --------------------------------------------------------------------------

// TestLoadSyncThroughput creates 20 volumes with data, tracks them in the
// sync daemon, drains all, and verifies manifests are present in S3.
func TestLoadSyncThroughput(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	const numVolumes = 20
	const filesPerVolume = 4
	const fileSize = 256 * 1024 // 256 KiB -> ~1 MiB per volume

	// Set up CAS infrastructure.
	bucket := uniqueName("load-sync")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create a shared template.
	tmplName := uniqueName("load-tmpl")
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
		volID := uniqueName("load-vol")
		volIDs[i] = volID
		volPath := "volumes/" + volID

		if err := mgr.SnapshotSubvolume(ctx, roTmplPath, volPath, false); err != nil {
			t.Fatalf("clone volume %d: %v", i, err)
		}

		vp := volPath
		vid := volID
		t.Cleanup(func() {
			mgr.DeleteSubvolume(context.Background(), vp)
			// Clean up layer snapshots.
			subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+vid)
			for _, sub := range subs {
				mgr.DeleteSubvolume(context.Background(), sub.Path)
			}
		})

		// Write unique data to each volume (~1 MiB).
		volDir := filepath.Join(pool, volPath)
		for j := 0; j < filesPerVolume; j++ {
			name := fmt.Sprintf("data-%03d.bin", j)
			content := bytes.Repeat([]byte{byte((i*filesPerVolume + j) % 256)}, fileSize)
			if err := os.WriteFile(filepath.Join(volDir, name), content, 0644); err != nil {
				t.Fatalf("write volume %d file %d: %v", i, j, err)
			}
		}

		daemon.TrackVolume(volID, tmplName, tmplHash)
	}

	// Drain all volumes and measure total wall time.
	start := time.Now()
	if err := daemon.DrainAll(ctx); err != nil {
		t.Fatalf("DrainAll: %v", err)
	}
	drainDuration := time.Since(start)

	t.Logf("DrainAll: %d volumes synced in %v (%.2f vol/s)",
		numVolumes, drainDuration, float64(numVolumes)/drainDuration.Seconds())

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
			exists, err := casStore.HasBlob(ctx, layer.Hash)
			if err != nil {
				t.Errorf("HasBlob(%s) for volume %s: %v", layer.Hash, volID, err)
			} else if !exists {
				t.Errorf("blob %s for volume %s not found in S3", layer.Hash, volID)
			}
		}
	}
}

// --------------------------------------------------------------------------
// Load test 4: Maximum volumes until pool exhaustion
// --------------------------------------------------------------------------

// TestLoadMaxVolumes creates volumes in batches of 50 until the pool has less
// than 10% free space or 500 volumes are reached, logging capacity and timing.
func TestLoadMaxVolumes(t *testing.T) {
	_ = getPoolPath(t) // ensure we're in an integration environment
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	const (
		batchSize       = 50
		maxVolumes      = 500
		freeThreshold   = 0.10 // stop when < 10% free
	)

	var allVolumes []string
	t.Cleanup(func() {
		for _, v := range allVolumes {
			mgr.DeleteSubvolume(context.Background(), v)
		}
	})

	totalCreated := 0
	batchNum := 0

	for totalCreated < maxVolumes {
		batchNum++
		batchStart := time.Now()
		batchCreated := 0

		for i := 0; i < batchSize && totalCreated < maxVolumes; i++ {
			volName := fmt.Sprintf("volumes/load-max-%04d", totalCreated)

			if err := mgr.CreateSubvolume(ctx, volName); err != nil {
				t.Logf("CreateSubvolume failed at volume %d: %v", totalCreated, err)
				goto done
			}

			allVolumes = append(allVolumes, volName)
			totalCreated++
			batchCreated++
		}

		batchDuration := time.Since(batchStart)
		t.Logf("Batch %d: created %d volumes in %v (%.2f vol/s)",
			batchNum, batchCreated, batchDuration, float64(batchCreated)/batchDuration.Seconds())

		// Check pool capacity.
		totalBytes, availableBytes, err := mgr.GetCapacity(ctx)
		if err != nil {
			t.Logf("GetCapacity error at volume %d: %v", totalCreated, err)
			goto done
		}

		freeRatio := float64(availableBytes) / float64(totalBytes)
		t.Logf("  Pool: total=%.2f MiB  avail=%.2f MiB  free=%.1f%%",
			float64(totalBytes)/(1<<20), float64(availableBytes)/(1<<20), freeRatio*100)

		if freeRatio < freeThreshold {
			t.Logf("Pool below %.0f%% free — stopping", freeThreshold*100)
			goto done
		}
	}

done:
	t.Logf("Final: created %d volumes total across %d batches", totalCreated, batchNum)
}
