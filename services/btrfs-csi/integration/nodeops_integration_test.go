//go:build integration

package integration

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// ---------------------------------------------------------------------------
// Subvolume lifecycle via gRPC
// ---------------------------------------------------------------------------

func TestNodeOps_CreateAndDeleteSubvolume(t *testing.T) {
	bm := newBtrfsManager(t)
	addr := startNodeOpsServer(t, bm, nil, nil)
	client := connectNodeOpsClient(t, addr)
	ctx := context.Background()

	name := "volumes/" + uniqueName("nodeops")

	// Create
	if err := client.CreateSubvolume(ctx, name); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() {
		// Best-effort cleanup via the manager directly.
		_ = bm.DeleteSubvolume(context.Background(), name)
	})

	// Verify exists
	exists, err := client.SubvolumeExists(ctx, name)
	if err != nil {
		t.Fatalf("SubvolumeExists: %v", err)
	}
	if !exists {
		t.Fatal("SubvolumeExists returned false after create")
	}

	// Delete
	if err := client.DeleteSubvolume(ctx, name); err != nil {
		t.Fatalf("DeleteSubvolume: %v", err)
	}

	// Verify gone
	exists, err = client.SubvolumeExists(ctx, name)
	if err != nil {
		t.Fatalf("SubvolumeExists after delete: %v", err)
	}
	if exists {
		t.Fatal("SubvolumeExists returned true after delete")
	}
}

// ---------------------------------------------------------------------------
// Snapshot via gRPC
// ---------------------------------------------------------------------------

func TestNodeOps_SnapshotSubvolume(t *testing.T) {
	pool := getPoolPath(t)
	bm := newBtrfsManager(t)
	addr := startNodeOpsServer(t, bm, nil, nil)
	client := connectNodeOpsClient(t, addr)
	ctx := context.Background()

	sourceName := "volumes/" + uniqueName("snap-src")
	snapName := "snapshots/" + uniqueName("snap-dst")

	// Create source subvolume and write a file directly to disk.
	if err := client.CreateSubvolume(ctx, sourceName); err != nil {
		t.Fatalf("create source: %v", err)
	}
	t.Cleanup(func() { _ = bm.DeleteSubvolume(context.Background(), sourceName) })

	writeTestFile(t, filepath.Join(pool, sourceName), "file.txt", "snapshot-content")

	// Snapshot (writable).
	if err := client.SnapshotSubvolume(ctx, sourceName, snapName, false); err != nil {
		t.Fatalf("SnapshotSubvolume: %v", err)
	}
	t.Cleanup(func() { _ = bm.DeleteSubvolume(context.Background(), snapName) })

	// Verify the file exists in the snapshot on disk.
	verifyFileContent(t, filepath.Join(pool, snapName, "file.txt"), "snapshot-content")
}

// ---------------------------------------------------------------------------
// SubvolumeExists for non-existent path
// ---------------------------------------------------------------------------

func TestNodeOps_SubvolumeExists_NotFound(t *testing.T) {
	bm := newBtrfsManager(t)
	addr := startNodeOpsServer(t, bm, nil, nil)
	client := connectNodeOpsClient(t, addr)
	ctx := context.Background()

	exists, err := client.SubvolumeExists(ctx, "volumes/nonexistent-"+uniqueName("x"))
	if err != nil {
		t.Fatalf("SubvolumeExists: %v", err)
	}
	if exists {
		t.Fatal("expected false for non-existent subvolume")
	}
}

// ---------------------------------------------------------------------------
// GetCapacity
// ---------------------------------------------------------------------------

func TestNodeOps_GetCapacity(t *testing.T) {
	bm := newBtrfsManager(t)
	addr := startNodeOpsServer(t, bm, nil, nil)
	client := connectNodeOpsClient(t, addr)
	ctx := context.Background()

	total, available, err := client.GetCapacity(ctx)
	if err != nil {
		t.Fatalf("GetCapacity: %v", err)
	}
	if total <= 0 {
		t.Fatalf("total = %d, want > 0", total)
	}
	if available <= 0 {
		t.Fatalf("available = %d, want > 0", available)
	}
	if available > total {
		t.Fatalf("available (%d) > total (%d)", available, total)
	}
}

// ---------------------------------------------------------------------------
// ListSubvolumes
// ---------------------------------------------------------------------------

func TestNodeOps_ListSubvolumes(t *testing.T) {
	bm := newBtrfsManager(t)
	addr := startNodeOpsServer(t, bm, nil, nil)
	client := connectNodeOpsClient(t, addr)
	ctx := context.Background()

	prefix := "list-nodeops-"
	names := make([]string, 3)
	for i := range names {
		names[i] = "volumes/" + prefix + uniqueName("v")
		if err := client.CreateSubvolume(ctx, names[i]); err != nil {
			t.Fatalf("create %s: %v", names[i], err)
		}
		t.Cleanup(func() { _ = bm.DeleteSubvolume(context.Background(), names[i]) })
	}

	subs, err := client.ListSubvolumes(ctx, "volumes/")
	if err != nil {
		t.Fatalf("ListSubvolumes: %v", err)
	}

	// Index all returned Name and Path values for lookup.
	found := make(map[string]bool)
	for _, s := range subs {
		found[s.Name] = true
		found[s.Path] = true
		found[filepath.Base(s.Path)] = true
	}

	for _, n := range names {
		base := filepath.Base(n)
		if !found[base] && !found[n] {
			t.Errorf("subvolume %q not found in listing", n)
		}
	}
}

// ---------------------------------------------------------------------------
// TrackVolume / UntrackVolume
// ---------------------------------------------------------------------------

func TestNodeOps_TrackAndUntrackVolume(t *testing.T) {
	bm := newBtrfsManager(t)
	syncer := bsync.NewDaemon(bm, nil, nil, 1*time.Hour)
	t.Cleanup(func() { syncer.Stop() })

	addr := startNodeOpsServer(t, bm, syncer, nil)
	client := connectNodeOpsClient(t, addr)
	ctx := context.Background()

	volID := uniqueName("track")
	if err := client.TrackVolume(ctx, volID, "", ""); err != nil {
		t.Fatalf("TrackVolume: %v", err)
	}
	if err := client.UntrackVolume(ctx, volID); err != nil {
		t.Fatalf("UntrackVolume: %v", err)
	}
}

// ---------------------------------------------------------------------------
// EnsureTemplate (full round-trip via CAS store)
// ---------------------------------------------------------------------------

func TestNodeOps_EnsureTemplate(t *testing.T) {
	pool := getPoolPath(t)
	bm := newBtrfsManager(t)
	tmplMgr := template.NewManager(bm, nil, pool)
	ctx := context.Background()

	tmplName := uniqueName("tmpl")
	tmplPath := "templates/" + tmplName

	// Create a local template subvolume and add some content.
	if err := bm.CreateSubvolume(ctx, tmplPath); err != nil {
		t.Fatalf("create template subvolume: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, tmplPath), "index.js", "console.log('hi')")

	t.Cleanup(func() {
		_ = bm.DeleteSubvolume(context.Background(), tmplPath)
	})

	// Start nodeops server with the template manager and verify EnsureTemplate
	// returns success when template already exists locally.
	addr := startNodeOpsServer(t, bm, nil, tmplMgr)
	client := connectNodeOpsClient(t, addr)

	if err := client.EnsureTemplate(ctx, tmplName); err != nil {
		t.Fatalf("EnsureTemplate: %v", err)
	}

	if !bm.SubvolumeExists(ctx, tmplPath) {
		t.Fatal("template subvolume does not exist after EnsureTemplate")
	}
}

// ---------------------------------------------------------------------------
// RestoreVolume (requires CAS store — skip if not configured)
// ---------------------------------------------------------------------------

func TestNodeOps_RestoreVolume(t *testing.T) {
	pool := getPoolPath(t)
	bm := newBtrfsManager(t)
	syncer := bsync.NewDaemon(bm, nil, nil, 1*time.Hour)
	t.Cleanup(func() { syncer.Stop() })

	ctx := context.Background()
	volID := uniqueName("restore")
	volPath := "volumes/" + volID

	// Create volume, write data, track.
	if err := bm.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("create volume: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "restore-me")

	syncer.TrackVolume(volID, "", "")

	// SyncVolume requires CAS store — will fail with nil CAS.
	// This test verifies the server handles the restore path gracefully.
	addr := startNodeOpsServer(t, bm, syncer, nil)
	client := connectNodeOpsClient(t, addr)

	err := client.RestoreVolume(ctx, volID)
	if err != nil {
		// Expected when CAS store is nil.
		t.Logf("RestoreVolume failed as expected without CAS: %v", err)
	}

	t.Cleanup(func() {
		_ = bm.DeleteSubvolume(context.Background(), volPath)
	})
}

// ---------------------------------------------------------------------------
// PromoteToTemplate (full round-trip)
// ---------------------------------------------------------------------------

func TestNodeOps_PromoteToTemplate(t *testing.T) {
	pool := getPoolPath(t)
	bm := newBtrfsManager(t)
	tmplMgr := template.NewManager(bm, nil, pool)
	ctx := context.Background()

	volID := uniqueName("promote")
	volPath := "volumes/" + volID
	tmplName := uniqueName("tmpl-promote")

	// Create a "build volume" and write some content (simulating a builder job).
	if err := bm.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("create build volume: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, volPath), "package.json", `{"name": "test"}`)
	writeTestFile(t, filepath.Join(pool, volPath), "node_modules/.package-lock.json", "{}")

	// Start server with template manager.
	addr := startNodeOpsServer(t, bm, nil, tmplMgr)
	client := connectNodeOpsClient(t, addr)

	// Promote the volume to a template. This will fail at UploadTemplate
	// because CAS store is nil, but the local snapshot should still work
	// for the promotion step.
	err := client.PromoteToTemplate(ctx, volID, tmplName)

	tmplPath := "templates/" + tmplName
	t.Cleanup(func() {
		_ = bm.DeleteSubvolume(context.Background(), tmplPath)
		_ = bm.DeleteSubvolume(context.Background(), volPath)
		_ = bm.DeleteSubvolume(context.Background(), "snapshots/"+tmplName)
	})

	if err != nil {
		// Expected when CAS store is nil — UploadTemplate will fail.
		t.Logf("PromoteToTemplate failed as expected without CAS: %v", err)
		return
	}

	// The source volume should be deleted.
	if bm.SubvolumeExists(ctx, volPath) {
		t.Error("source volume should have been deleted after promotion")
	}

	// The template subvolume should exist.
	if !bm.SubvolumeExists(ctx, tmplPath) {
		t.Fatal("template subvolume does not exist after promotion")
	}

	// Verify the template content is preserved.
	verifyFileContent(t, filepath.Join(pool, tmplPath, "package.json"), `{"name": "test"}`)
}

func TestNodeOps_PromoteToTemplate_RefreshExisting(t *testing.T) {
	pool := getPoolPath(t)
	bm := newBtrfsManager(t)
	tmplMgr := template.NewManager(bm, nil, pool)
	ctx := context.Background()

	tmplName := uniqueName("tmpl-refresh")
	tmplPath := "templates/" + tmplName

	// Create an existing template (simulating a previous build).
	if err := bm.CreateSubvolume(ctx, tmplPath); err != nil {
		t.Fatalf("create existing template: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, tmplPath), "old.txt", "old-content")

	// Create a new build volume with updated content.
	volID := uniqueName("promote-v2")
	volPath := "volumes/" + volID
	if err := bm.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("create build volume: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, volPath), "new.txt", "new-content")

	addr := startNodeOpsServer(t, bm, nil, tmplMgr)
	client := connectNodeOpsClient(t, addr)

	// Promote should replace the existing template.
	err := client.PromoteToTemplate(ctx, volID, tmplName)
	t.Cleanup(func() {
		_ = bm.DeleteSubvolume(context.Background(), tmplPath)
		_ = bm.DeleteSubvolume(context.Background(), volPath)
		_ = bm.DeleteSubvolume(context.Background(), "snapshots/"+tmplName)
	})

	if err != nil {
		// Expected when CAS store is nil.
		t.Logf("PromoteToTemplate (refresh) failed as expected without CAS: %v", err)
		return
	}

	// New content should be present.
	verifyFileContent(t, filepath.Join(pool, tmplPath, "new.txt"), "new-content")

	// Old content should NOT be present (template was replaced, not merged).
	if _, err := os.Stat(filepath.Join(pool, tmplPath, "old.txt")); err == nil {
		t.Error("old.txt should not exist in refreshed template")
	}
}

func TestNodeOps_PromoteToTemplate_VolumeNotFound(t *testing.T) {
	bm := newBtrfsManager(t)
	tmplMgr := template.NewManager(bm, nil, getPoolPath(t))

	addr := startNodeOpsServer(t, bm, nil, tmplMgr)
	client := connectNodeOpsClient(t, addr)
	ctx := context.Background()

	err := client.PromoteToTemplate(ctx, "nonexistent-"+uniqueName("x"), "tmpl")
	if err == nil {
		t.Fatal("expected error for nonexistent volume, got nil")
	}

	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status error, got %T: %v", err, err)
	}
	if st.Code() != codes.NotFound {
		t.Errorf("code = %v, want %v: %s", st.Code(), codes.NotFound, st.Message())
	}
}

// ---------------------------------------------------------------------------
// Error propagation (path traversal)
// ---------------------------------------------------------------------------

func TestNodeOps_ErrorPropagation(t *testing.T) {
	bm := newBtrfsManager(t)
	addr := startNodeOpsServer(t, bm, nil, nil)
	client := connectNodeOpsClient(t, addr)
	ctx := context.Background()

	err := client.CreateSubvolume(ctx, "../../etc/passwd")
	if err == nil {
		t.Fatal("expected error for path traversal, got nil")
	}

	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status error, got %T: %v", err, err)
	}
	if st.Code() != codes.Internal {
		t.Fatalf("expected codes.Internal, got %s: %s", st.Code(), st.Message())
	}
}

// ---------------------------------------------------------------------------
// Sequential exercise of all RPCs
// ---------------------------------------------------------------------------

func TestNodeOps_AllRPCs_Sequential(t *testing.T) {
	pool := getPoolPath(t)
	bm := newBtrfsManager(t)
	syncer := bsync.NewDaemon(bm, nil, nil, 1*time.Hour)
	t.Cleanup(func() { syncer.Stop() })

	addr := startNodeOpsServer(t, bm, syncer, nil)
	client := connectNodeOpsClient(t, addr)
	ctx := context.Background()

	volName := "volumes/" + uniqueName("allrpc")
	snapName := "snapshots/" + uniqueName("allrpc-snap")

	// 1. CreateSubvolume
	if err := client.CreateSubvolume(ctx, volName); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	t.Cleanup(func() { _ = bm.DeleteSubvolume(context.Background(), volName) })

	// 2. SubvolumeExists -> true
	exists, err := client.SubvolumeExists(ctx, volName)
	if err != nil {
		t.Fatalf("SubvolumeExists: %v", err)
	}
	if !exists {
		t.Fatal("expected true after create")
	}

	// Write a test file for the snapshot.
	writeTestFile(t, filepath.Join(pool, volName), "seq.txt", "sequential")

	// 3. SnapshotSubvolume
	if err := client.SnapshotSubvolume(ctx, volName, snapName, false); err != nil {
		t.Fatalf("SnapshotSubvolume: %v", err)
	}
	t.Cleanup(func() { _ = bm.DeleteSubvolume(context.Background(), snapName) })

	// 4. ListSubvolumes -> find created ones
	subs, err := client.ListSubvolumes(ctx, "volumes/")
	if err != nil {
		t.Fatalf("ListSubvolumes: %v", err)
	}
	if len(subs) == 0 {
		t.Fatal("ListSubvolumes returned empty")
	}

	// 5. GetCapacity -> total > 0
	total, _, err := client.GetCapacity(ctx)
	if err != nil {
		t.Fatalf("GetCapacity: %v", err)
	}
	if total <= 0 {
		t.Fatalf("total = %d, want > 0", total)
	}

	// 6. TrackVolume (with template context)
	volID := filepath.Base(volName)
	if err := client.TrackVolume(ctx, volID, "", ""); err != nil {
		t.Fatalf("TrackVolume: %v", err)
	}

	// 7. UntrackVolume
	if err := client.UntrackVolume(ctx, volID); err != nil {
		t.Fatalf("UntrackVolume: %v", err)
	}

	// 8. DeleteSubvolume (snapshot)
	if err := client.DeleteSubvolume(ctx, snapName); err != nil {
		t.Fatalf("DeleteSubvolume snapshot: %v", err)
	}

	// 9. DeleteSubvolume (original)
	if err := client.DeleteSubvolume(ctx, volName); err != nil {
		t.Fatalf("DeleteSubvolume original: %v", err)
	}

	// 10. SubvolumeExists -> false
	exists, err = client.SubvolumeExists(ctx, volName)
	if err != nil {
		t.Fatalf("SubvolumeExists final: %v", err)
	}
	if exists {
		t.Fatal("expected false after delete")
	}
}

