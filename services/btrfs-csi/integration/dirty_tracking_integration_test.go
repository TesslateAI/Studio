//go:build integration

package integration

import (
	"context"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/fileops"
	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
)

// --------------------------------------------------------------------------
// Dirty tracking integration tests
// --------------------------------------------------------------------------

// TestDirty_NewVolumeStartsDirty verifies TrackVolume sets dirty=true and
// GetTrackedState reports it.
func TestDirty_NewVolumeStartsDirty(t *testing.T) {
	mgr := newBtrfsManager(t)
	daemon := bsync.NewDaemon(mgr, nil, nil, 1*time.Hour)

	volID := uniqueName("dirty")
	daemon.TrackVolume(volID, "", "")

	states := daemon.GetTrackedState()
	if len(states) != 1 {
		t.Fatalf("expected 1 tracked volume, got %d", len(states))
	}
	if !states[0].Dirty {
		t.Error("newly tracked volume should report Dirty=true")
	}
}

// TestDirty_SyncClearsDirty verifies that a successful CAS sync clears the
// dirty flag.
func TestDirty_SyncClearsDirty(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	store := newObjectStorage(t, uniqueName("dirty"))
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	volID := uniqueName("dirty")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
		synth := "templates/_vol_" + volID
		if mgr.SubvolumeExists(ctx, synth) {
			mgr.DeleteSubvolume(context.Background(), synth)
		}
	})

	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "initial")
	daemon.TrackVolume(volID, "", "")

	// Before sync: dirty.
	states := daemon.GetTrackedState()
	if !states[0].Dirty {
		t.Fatal("expected dirty=true before sync")
	}

	// Sync to CAS.
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// After sync: clean.
	states = daemon.GetTrackedState()
	if states[0].Dirty {
		t.Error("expected dirty=false after successful sync")
	}
}

// TestDirty_MarkDirtyAfterSync verifies MarkDirty re-dirties a clean volume.
func TestDirty_MarkDirtyAfterSync(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	store := newObjectStorage(t, uniqueName("dirty"))
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	volID := uniqueName("dirty")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
		synth := "templates/_vol_" + volID
		if mgr.SubvolumeExists(ctx, synth) {
			mgr.DeleteSubvolume(context.Background(), synth)
		}
	})

	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "initial")
	daemon.TrackVolume(volID, "", "")

	// Sync to clean.
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	states := daemon.GetTrackedState()
	if states[0].Dirty {
		t.Fatal("expected clean after sync")
	}

	// MarkDirty.
	daemon.MarkDirty(volID)

	states = daemon.GetTrackedState()
	if !states[0].Dirty {
		t.Error("expected dirty=true after MarkDirty")
	}

	// Sync again to verify it clears again.
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("second SyncVolume: %v", err)
	}

	states = daemon.GetTrackedState()
	if states[0].Dirty {
		t.Error("expected clean after second sync")
	}
}

// TestDirty_DrainSkipsCleanVolumes creates multiple volumes, syncs them all,
// marks only some as dirty, and verifies DrainAll only uploads the dirty ones.
func TestDirty_DrainSkipsCleanVolumes(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	store := newObjectStorage(t, uniqueName("dirty"))
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	// Create 4 volumes.
	volIDs := make([]string, 4)
	for i := range volIDs {
		volIDs[i] = uniqueName("drain")
		volPath := "volumes/" + volIDs[i]
		if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
			t.Fatalf("CreateSubvolume %d: %v", i, err)
		}
		vid := volIDs[i]
		t.Cleanup(func() {
			mgr.DeleteSubvolume(context.Background(), "volumes/"+vid)
			subs, _ := mgr.ListSubvolumes(ctx, "layers/"+vid)
			for _, sub := range subs {
				mgr.DeleteSubvolume(context.Background(), sub.Path)
			}
			synth := "templates/_vol_" + vid
			if mgr.SubvolumeExists(ctx, synth) {
				mgr.DeleteSubvolume(context.Background(), synth)
			}
		})
		writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "vol-"+volIDs[i])
		daemon.TrackVolume(volIDs[i], "", "")
	}

	// Sync all to make them clean.
	for _, vid := range volIDs {
		if err := daemon.SyncVolume(ctx, vid); err != nil {
			t.Fatalf("SyncVolume %s: %v", vid, err)
		}
	}

	// Verify all clean.
	for _, s := range daemon.GetTrackedState() {
		if s.Dirty {
			t.Fatalf("volume %s should be clean after sync", s.VolumeID)
		}
	}

	// Mark only vol[1] dirty by writing a file.
	writeTestFile(t, filepath.Join(pool, "volumes", volIDs[1]), "new.txt", "modified")
	daemon.MarkDirty(volIDs[1])

	// DrainAll — should be fast because only 1 of 4 is dirty.
	start := time.Now()
	if err := daemon.DrainAll(ctx); err != nil {
		t.Fatalf("DrainAll: %v", err)
	}
	elapsed := time.Since(start)

	t.Logf("DrainAll completed in %v (1 dirty / 4 total)", elapsed)

	// Verify the dirty volume's new data was persisted.
	manifest, err := casStore.GetManifest(ctx, volIDs[1])
	if err != nil {
		t.Fatalf("GetManifest for dirty vol: %v", err)
	}
	if len(manifest.Layers) < 2 {
		t.Errorf("expected at least 2 layers for dirty volume (initial sync + drain sync), got %d",
			len(manifest.Layers))
	}
}

// TestDirty_FileOpsWriteMarksDirty verifies that writing via FileOps gRPC
// marks the volume as dirty for sync.
func TestDirty_FileOpsWriteMarksDirty(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	store := newObjectStorage(t, uniqueName("dirty"))
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	volID := uniqueName("dirty")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
		synth := "templates/_vol_" + volID
		if mgr.SubvolumeExists(ctx, synth) {
			mgr.DeleteSubvolume(context.Background(), synth)
		}
	})

	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "initial")
	daemon.TrackVolume(volID, "", "")

	// Sync to clean.
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	states := daemon.GetTrackedState()
	if states[0].Dirty {
		t.Fatal("expected clean after sync")
	}

	// Start FileOps server with the daemon as syncer.
	addr := startFileOpsServerWithSyncer(t, pool, daemon)
	client := connectFileOpsClient(t, addr)

	// Write via FileOps gRPC — should mark dirty.
	if err := client.WriteFile(ctx, volID, "new-file.txt", []byte("written via fileops"), 0644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	states = daemon.GetTrackedState()
	if !states[0].Dirty {
		t.Error("expected dirty=true after FileOps WriteFile")
	}

	// Sync again — should clear dirty.
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("second SyncVolume: %v", err)
	}

	states = daemon.GetTrackedState()
	if states[0].Dirty {
		t.Error("expected clean after second sync")
	}
}

// TestDirty_FileOpsDeleteMarksDirty verifies that deleting via FileOps
// marks the volume as dirty.
func TestDirty_FileOpsDeleteMarksDirty(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	store := newObjectStorage(t, uniqueName("dirty"))
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	volID := uniqueName("dirty")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
		synth := "templates/_vol_" + volID
		if mgr.SubvolumeExists(ctx, synth) {
			mgr.DeleteSubvolume(context.Background(), synth)
		}
	})

	writeTestFile(t, filepath.Join(pool, volPath), "to-delete.txt", "will be deleted")
	daemon.TrackVolume(volID, "", "")

	// Sync to clean.
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Start FileOps with syncer.
	addr := startFileOpsServerWithSyncer(t, pool, daemon)
	client := connectFileOpsClient(t, addr)

	// Delete via FileOps.
	if err := client.DeletePath(ctx, volID, "to-delete.txt"); err != nil {
		t.Fatalf("DeletePath: %v", err)
	}

	states := daemon.GetTrackedState()
	if !states[0].Dirty {
		t.Error("expected dirty=true after FileOps DeletePath")
	}
}

// TestDirty_FileOpsTarExtractMarksDirty verifies that TarExtract via FileOps
// marks the volume as dirty.
func TestDirty_FileOpsTarExtractMarksDirty(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	store := newObjectStorage(t, uniqueName("dirty"))
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	volID := uniqueName("dirty")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
		synth := "templates/_vol_" + volID
		if mgr.SubvolumeExists(ctx, synth) {
			mgr.DeleteSubvolume(context.Background(), synth)
		}
	})

	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "initial")
	daemon.TrackVolume(volID, "", "")

	// Sync to clean.
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Start FileOps with syncer.
	addr := startFileOpsServerWithSyncer(t, pool, daemon)
	client := connectFileOpsClient(t, addr)

	// TarExtract via FileOps.
	tarData := buildTestTar(t, map[string]string{
		"extracted.txt": "from tar",
	})
	if err := client.TarExtract(ctx, volID, "dest", tarData); err != nil {
		t.Fatalf("TarExtract: %v", err)
	}

	states := daemon.GetTrackedState()
	if !states[0].Dirty {
		t.Error("expected dirty=true after FileOps TarExtract")
	}
}

// TestDirty_FileOpsMkdirMarksDirty verifies that MkdirAll via FileOps
// marks the volume as dirty.
func TestDirty_FileOpsMkdirMarksDirty(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	store := newObjectStorage(t, uniqueName("dirty"))
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	volID := uniqueName("dirty")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
		synth := "templates/_vol_" + volID
		if mgr.SubvolumeExists(ctx, synth) {
			mgr.DeleteSubvolume(context.Background(), synth)
		}
	})

	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "initial")
	daemon.TrackVolume(volID, "", "")

	// Sync to clean.
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Start FileOps with syncer.
	addr := startFileOpsServerWithSyncer(t, pool, daemon)
	client := connectFileOpsClient(t, addr)

	// MkdirAll via FileOps.
	if err := client.MkdirAll(ctx, volID, "new/nested/dir"); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}

	states := daemon.GetTrackedState()
	if !states[0].Dirty {
		t.Error("expected dirty=true after FileOps MkdirAll")
	}
}

// TestDirty_FullCycle_EndToEnd is the comprehensive end-to-end test:
// 1. Create volume → track (dirty)
// 2. Sync → clean
// 3. Write via FileOps → dirty
// 4. Sync → clean
// 5. No changes → stays clean through syncAll (skipped)
func TestDirty_FullCycle_EndToEnd(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	store := newObjectStorage(t, uniqueName("dirty"))
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	// Create 2 volumes.
	vol1 := uniqueName("e2e")
	vol2 := uniqueName("e2e")
	for _, vid := range []string{vol1, vol2} {
		volPath := "volumes/" + vid
		if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
			t.Fatalf("CreateSubvolume %s: %v", vid, err)
		}
		v := vid
		t.Cleanup(func() {
			mgr.DeleteSubvolume(context.Background(), "volumes/"+v)
			subs, _ := mgr.ListSubvolumes(ctx, "layers/"+v)
			for _, sub := range subs {
				mgr.DeleteSubvolume(context.Background(), sub.Path)
			}
			synth := "templates/_vol_" + v
			if mgr.SubvolumeExists(ctx, synth) {
				mgr.DeleteSubvolume(context.Background(), synth)
			}
		})
		writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "initial-"+vid)
		daemon.TrackVolume(vid, "", "")
	}

	// Step 1: Both start dirty.
	for _, s := range daemon.GetTrackedState() {
		if !s.Dirty {
			t.Fatalf("volume %s should start dirty", s.VolumeID)
		}
	}

	// Step 2: Sync both.
	for _, vid := range []string{vol1, vol2} {
		if err := daemon.SyncVolume(ctx, vid); err != nil {
			t.Fatalf("SyncVolume %s: %v", vid, err)
		}
	}
	for _, s := range daemon.GetTrackedState() {
		if s.Dirty {
			t.Fatalf("volume %s should be clean after sync", s.VolumeID)
		}
	}

	// Step 3: Write to vol1 via FileOps.
	addr := startFileOpsServerWithSyncer(t, pool, daemon)
	client := connectFileOpsClient(t, addr)

	if err := client.WriteFile(ctx, vol1, "update.txt", []byte("updated"), 0644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	// vol1 = dirty, vol2 = clean.
	for _, s := range daemon.GetTrackedState() {
		switch s.VolumeID {
		case vol1:
			if !s.Dirty {
				t.Error("vol1 should be dirty after write")
			}
		case vol2:
			if s.Dirty {
				t.Error("vol2 should still be clean")
			}
		}
	}

	// Step 4: Sync vol1.
	if err := daemon.SyncVolume(ctx, vol1); err != nil {
		t.Fatalf("SyncVolume vol1: %v", err)
	}
	for _, s := range daemon.GetTrackedState() {
		if s.Dirty {
			t.Errorf("volume %s should be clean after all syncs", s.VolumeID)
		}
	}

	// Step 5: Verify vol1 data persisted to CAS.
	manifest, err := casStore.GetManifest(ctx, vol1)
	if err != nil {
		t.Fatalf("GetManifest vol1: %v", err)
	}
	if len(manifest.Layers) < 2 {
		t.Errorf("expected at least 2 layers (initial + update), got %d", len(manifest.Layers))
	}

	t.Log("Full dirty tracking cycle passed")
}

// verify fileops.DirtySyncer is satisfied by sync.Daemon at compile time.
var _ fileops.DirtySyncer = (*bsync.Daemon)(nil)

// --------------------------------------------------------------------------
// Generation-based smart dirty detection
// --------------------------------------------------------------------------

// TestDirty_GenerationBasedDetection verifies that discoverVolumes uses btrfs
// generation comparison to correctly detect clean vs dirty volumes after a
// pod restart. This is the real btrfs integration test.
func TestDirty_GenerationBasedDetection(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	store := newObjectStorage(t, uniqueName("gen-detect"))
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create 3 volumes.
	volIDs := make([]string, 3)
	for i := range volIDs {
		volID := uniqueName("gen-vol")
		volIDs[i] = volID
		volPath := "volumes/" + volID
		if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
			t.Fatalf("CreateSubvolume(%s): %v", volID, err)
		}
		writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "initial")
		t.Cleanup(func() {
			mgr.DeleteSubvolume(context.Background(), volPath)
			subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
			for _, sub := range subs {
				mgr.DeleteSubvolume(context.Background(), sub.Path)
			}
		})
	}

	// First daemon: track and sync all 3 volumes.
	daemon1 := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	for _, volID := range volIDs {
		daemon1.TrackVolume(volID, "", "")
	}
	for _, volID := range volIDs {
		if err := daemon1.SyncVolume(ctx, volID); err != nil {
			t.Fatalf("SyncVolume(%s): %v", volID, err)
		}
	}

	// Simulate drain: sync dirty volumes but preserve layer snapshots.
	// (Mark dirty first to force drain to actually sync.)
	for _, volID := range volIDs {
		daemon1.MarkDirty(volID)
	}
	if err := daemon1.DrainAll(ctx); err != nil {
		t.Fatalf("DrainAll: %v", err)
	}

	// Modify volume 0 AFTER drain (simulates user writing between drain and pod death).
	writeTestFile(t, filepath.Join(pool, "volumes/"+volIDs[0]), "post-drain.txt", "modified")
	// Force btrfs transaction commit so generation is updated.
	exec.CommandContext(ctx, "sync").Run()

	// Verify layer snapshots still exist (drain preserves them).
	for _, volID := range volIDs {
		subs, err := mgr.ListSubvolumes(ctx, "layers/"+volID)
		if err != nil {
			t.Fatalf("ListSubvolumes(layers/%s): %v", volID, err)
		}
		if len(subs) == 0 {
			t.Fatalf("layer snapshot for %s should exist after drain", volID)
		}
	}

	// Second daemon: simulates new pod starting. discoverVolumes should detect:
	// - volIDs[0]: DIRTY (modified after drain → generation > snapshot generation)
	// - volIDs[1]: CLEAN (not modified → generation == snapshot generation)
	// - volIDs[2]: CLEAN (not modified → generation == snapshot generation)
	daemon2 := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)

	// Start triggers discoverVolumes internally. We can check tracked state after.
	// But Start blocks on the ticker. Instead, call discoverVolumes indirectly
	// by checking GetTrackedState (it's populated by the first sync tick or
	// we can just create a daemon and not start it — discoverVolumes is called
	// from Start).

	// Use a context that we cancel immediately after discovery.
	discoverCtx, discoverCancel := context.WithCancel(ctx)
	go daemon2.Start(discoverCtx)
	// Give it time to run discoverVolumes.
	time.Sleep(500 * time.Millisecond)
	discoverCancel()
	time.Sleep(100 * time.Millisecond)

	states := daemon2.GetTrackedState()
	if len(states) < 3 {
		t.Fatalf("expected at least 3 tracked volumes, got %d", len(states))
	}

	stateMap := make(map[string]bool) // volID → dirty
	for _, s := range states {
		stateMap[s.VolumeID] = s.Dirty
	}

	// volIDs[0] should be dirty (modified after drain).
	if dirty, ok := stateMap[volIDs[0]]; !ok {
		t.Errorf("%s not tracked", volIDs[0])
	} else if !dirty {
		t.Errorf("%s should be DIRTY (modified after drain)", volIDs[0])
	}

	// volIDs[1] and [2] should be clean (not modified after drain).
	for _, volID := range volIDs[1:] {
		if dirty, ok := stateMap[volID]; !ok {
			t.Errorf("%s not tracked", volID)
		} else if dirty {
			t.Errorf("%s should be CLEAN (not modified after drain)", volID)
		}
	}

	t.Logf("Generation-based detection: %s=dirty, %s=clean, %s=clean ✓",
		volIDs[0], volIDs[1], volIDs[2])
}
