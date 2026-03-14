package gc

import (
	"context"
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
)

func TestNewCollector(t *testing.T) {
	mgr := btrfs.NewManager("/pool")
	cfg := Config{
		Interval:    5 * time.Minute,
		GracePeriod: 10 * time.Minute,
		DryRun:      true,
	}

	c := NewCollector(mgr, nil, cfg)

	if c.btrfs != mgr {
		t.Fatalf("expected btrfs manager %p, got %p", mgr, c.btrfs)
	}
	if c.store != nil {
		t.Fatalf("expected nil object storage, got %v", c.store)
	}
	if c.config.Interval != 5*time.Minute {
		t.Fatalf("expected interval 5m, got %v", c.config.Interval)
	}
	if c.config.GracePeriod != 10*time.Minute {
		t.Fatalf("expected grace period 10m, got %v", c.config.GracePeriod)
	}
	if !c.config.DryRun {
		t.Fatal("expected DryRun true, got false")
	}
	if c.knownVolumes != nil {
		t.Fatal("expected knownVolumes to be nil initially")
	}
}

func TestSetKnownVolumesFunc(t *testing.T) {
	mgr := btrfs.NewManager("/pool")
	c := NewCollector(mgr, nil, Config{
		Interval:    time.Minute,
		GracePeriod: time.Minute,
	})

	expectedVols := map[string]bool{
		"vol-aaa": true,
		"vol-bbb": true,
	}

	fn := func(ctx context.Context) (map[string]bool, error) {
		return expectedVols, nil
	}
	c.SetKnownVolumesFunc(fn)

	if c.knownVolumes == nil {
		t.Fatal("expected knownVolumes to be set, got nil")
	}

	got, err := c.knownVolumes(context.Background())
	if err != nil {
		t.Fatalf("unexpected error from knownVolumes: %v", err)
	}
	if len(got) != len(expectedVols) {
		t.Fatalf("expected %d volumes, got %d", len(expectedVols), len(got))
	}
	for k, v := range expectedVols {
		if got[k] != v {
			t.Fatalf("expected volume %q=%v, got %v", k, v, got[k])
		}
	}
}

func TestCleanOrphanedSubvolumes_NilCallback(t *testing.T) {
	mgr := btrfs.NewManager("/pool")
	c := NewCollector(mgr, nil, Config{
		Interval:    time.Minute,
		GracePeriod: time.Minute,
	})
	// knownVolumes is nil by default; should short-circuit.

	count, err := c.cleanOrphanedSubvolumes(context.Background())
	if err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
	if count != 0 {
		t.Fatalf("expected 0 deleted, got %d", count)
	}
}

func TestCleanOrphanedS3Snapshots_NilStore(t *testing.T) {
	mgr := btrfs.NewManager("/pool")
	c := NewCollector(mgr, nil, Config{
		Interval:    time.Minute,
		GracePeriod: time.Minute,
	})

	// Set a knownVolumes func so only the nil-store guard triggers.
	c.SetKnownVolumesFunc(func(ctx context.Context) (map[string]bool, error) {
		return map[string]bool{"vol-1": true}, nil
	})

	count, err := c.cleanOrphanedS3Snapshots(context.Background())
	if err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
	if count != 0 {
		t.Fatalf("expected 0 deleted, got %d", count)
	}
}

func TestCleanOrphanedS3Snapshots_NilCallback(t *testing.T) {
	// Both store and knownVolumes are nil. The guard checks store == nil || knownVolumes == nil.
	mgr := btrfs.NewManager("/pool")
	c := NewCollector(mgr, nil, Config{
		Interval:    time.Minute,
		GracePeriod: time.Minute,
	})

	count, err := c.cleanOrphanedS3Snapshots(context.Background())
	if err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
	if count != 0 {
		t.Fatalf("expected 0 deleted, got %d", count)
	}
}

func TestCleanStaleLocalSnapshots_FailsGracefully(t *testing.T) {
	// Uses a nonexistent pool path so btrfs.ListSubvolumes will fail
	// (the btrfs binary won't be present or the path won't exist).
	mgr := btrfs.NewManager("/nonexistent-pool-path")
	c := NewCollector(mgr, nil, Config{
		Interval:    time.Minute,
		GracePeriod: time.Minute,
	})

	count, err := c.cleanStaleLocalSnapshots(context.Background())
	if err == nil {
		t.Fatal("expected error from ListSubvolumes on invalid pool, got nil")
	}
	if count != 0 {
		t.Fatalf("expected 0 deleted on error, got %d", count)
	}
}

func TestStart_ContextCancel(t *testing.T) {
	mgr := btrfs.NewManager("/pool")
	c := NewCollector(mgr, nil, Config{
		Interval:    time.Hour, // long interval so ticker won't fire
		GracePeriod: time.Minute,
	})

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel immediately

	done := make(chan struct{})
	go func() {
		c.Start(ctx)
		close(done)
	}()

	select {
	case <-done:
		// Start returned promptly after cancellation.
	case <-time.After(2 * time.Second):
		t.Fatal("Start did not return within 2 seconds after context cancellation")
	}
}

func TestRunOnce_NilCallbacks(t *testing.T) {
	// knownVolumes is nil and store is nil.
	// cleanOrphanedSubvolumes -> (0, nil)  [nil callback guard]
	// cleanOrphanedS3Snapshots -> (0, nil) [nil store/callback guard]
	// cleanStaleLocalSnapshots -> (0, err) [btrfs command fails]
	// RunOnce logs errors but always returns nil.
	mgr := btrfs.NewManager("/nonexistent-pool-path")
	c := NewCollector(mgr, nil, Config{
		Interval:    time.Minute,
		GracePeriod: time.Minute,
	})

	err := c.RunOnce(context.Background())
	if err != nil {
		t.Fatalf("expected RunOnce to return nil, got %v", err)
	}
}
