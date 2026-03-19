package sync

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
)

func TestNewDaemon(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	interval := 30 * time.Second

	// Pass nil for CAS store and template manager since we only test constructor fields.
	d := NewDaemon(bm, nil, nil, interval)

	if d == nil {
		t.Fatal("NewDaemon returned nil")
	}
	if d.btrfs != bm {
		t.Error("btrfs manager not set correctly")
	}
	if d.cas != nil {
		t.Error("CAS store should be nil when passed nil")
	}
	if d.tmplMgr != nil {
		t.Error("template manager should be nil when passed nil")
	}
	if d.interval != interval {
		t.Errorf("interval = %v, want %v", d.interval, interval)
	}
	if d.tracked == nil {
		t.Error("tracked map should be initialized")
	}
	if len(d.tracked) != 0 {
		t.Errorf("tracked map should be empty, got %d entries", len(d.tracked))
	}
	if d.stopCh == nil {
		t.Error("stopCh should be initialized")
	}
}

func TestTrackUntrack(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	d := NewDaemon(bm, nil, nil, 60*time.Second)

	// Track a volume.
	d.TrackVolume("vol-1", "", "")

	d.mu.Lock()
	if _, exists := d.tracked["vol-1"]; !exists {
		t.Error("vol-1 should be tracked after TrackVolume")
	}
	if len(d.tracked) != 1 {
		t.Errorf("tracked map length = %d, want 1", len(d.tracked))
	}
	d.mu.Unlock()

	// Track a second volume.
	d.TrackVolume("vol-2", "", "")

	d.mu.Lock()
	if len(d.tracked) != 2 {
		t.Errorf("tracked map length = %d, want 2", len(d.tracked))
	}
	d.mu.Unlock()

	// Untrack vol-1. Note: UntrackVolume tries to delete the last layer
	// snapshot via btrfs, but since there is no lastSnapPath set and the
	// btrfs manager won't find any real subvolume, the untrack still
	// removes the entry from the map.
	d.UntrackVolume("vol-1")

	d.mu.Lock()
	if _, exists := d.tracked["vol-1"]; exists {
		t.Error("vol-1 should not be tracked after UntrackVolume")
	}
	if _, exists := d.tracked["vol-2"]; !exists {
		t.Error("vol-2 should still be tracked")
	}
	if len(d.tracked) != 1 {
		t.Errorf("tracked map length = %d, want 1", len(d.tracked))
	}
	d.mu.Unlock()

	// Untrack vol-2.
	d.UntrackVolume("vol-2")

	d.mu.Lock()
	if len(d.tracked) != 0 {
		t.Errorf("tracked map length = %d, want 0", len(d.tracked))
	}
	d.mu.Unlock()
}

func TestTrackVolume_Idempotent(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	d := NewDaemon(bm, nil, nil, 60*time.Second)

	d.TrackVolume("vol-1", "", "")
	d.TrackVolume("vol-1", "", "")
	d.TrackVolume("vol-1", "", "")

	d.mu.Lock()
	count := len(d.tracked)
	d.mu.Unlock()

	if count != 1 {
		t.Errorf("tracking same volume 3 times resulted in %d entries, want 1", count)
	}
}

func TestUntrackVolume_NotTracked(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	d := NewDaemon(bm, nil, nil, 60*time.Second)

	// Untracking a volume that was never tracked should not panic.
	d.UntrackVolume("nonexistent")

	d.mu.Lock()
	count := len(d.tracked)
	d.mu.Unlock()

	if count != 0 {
		t.Errorf("tracked map length = %d, want 0", count)
	}
}

func TestSyncVolume_NotTracked(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	d := NewDaemon(bm, nil, nil, 60*time.Second)

	err := d.SyncVolume(context.Background(), "vol-not-tracked")
	if err == nil {
		t.Fatal("expected error when syncing untracked volume")
	}

	wantMsg := `volume "vol-not-tracked" is not tracked for sync`
	if err.Error() != wantMsg {
		t.Errorf("error message = %q, want %q", err.Error(), wantMsg)
	}
}

func TestTrackVolume_SetsVolumeID(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	d := NewDaemon(bm, nil, nil, 60*time.Second)

	d.TrackVolume("my-special-vol", "nodejs", "abc123hash")

	d.mu.Lock()
	tv, exists := d.tracked["my-special-vol"]
	d.mu.Unlock()

	if !exists {
		t.Fatal("volume should be tracked")
	}
	if tv.volumeID != "my-special-vol" {
		t.Errorf("volumeID = %q, want %q", tv.volumeID, "my-special-vol")
	}
	if tv.templateName != "nodejs" {
		t.Errorf("templateName = %q, want %q", tv.templateName, "nodejs")
	}
	if tv.templateHash != "abc123hash" {
		t.Errorf("templateHash = %q, want %q", tv.templateHash, "abc123hash")
	}
	if tv.lastSnapPath != "" {
		t.Errorf("lastSnapPath = %q, want empty", tv.lastSnapPath)
	}
	if !tv.lastSyncAt.IsZero() {
		t.Errorf("lastSyncAt should be zero time, got %v", tv.lastSyncAt)
	}
}

func TestStart_ContextCancel(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	d := NewDaemon(bm, nil, nil, 60*time.Second)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel immediately

	done := make(chan struct{})
	go func() {
		d.Start(ctx)
		close(done)
	}()

	select {
	case <-done:
		// Start returned promptly — success.
	case <-time.After(2 * time.Second):
		t.Fatal("Start did not return within 2 seconds after context cancellation")
	}
}

func TestDrainAll_Empty(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	d := NewDaemon(bm, nil, nil, 60*time.Second)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := d.DrainAll(ctx); err != nil {
		t.Fatalf("DrainAll on empty daemon: %v", err)
	}

	if len(d.GetTrackedState()) != 0 {
		t.Error("tracked state should be empty after drain")
	}
}

func TestDrainAll_ContextCancellation(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	d := NewDaemon(bm, nil, nil, 60*time.Second)

	// Track several volumes — SyncVolume will fail (no real btrfs) but
	// context cancellation should stop the drain.
	for i := 0; i < 10; i++ {
		d.TrackVolume(fmt.Sprintf("vol-%d", i), "", "")
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // Cancel immediately.

	err := d.DrainAll(ctx)
	if err == nil {
		t.Fatal("expected context error from cancelled DrainAll")
	}
	if err != context.Canceled {
		t.Fatalf("expected context.Canceled, got: %v", err)
	}
}
