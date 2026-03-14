// Package gc implements garbage collection for orphaned btrfs subvolumes
// and expired snapshots in object storage.
package gc

import (
	"context"
	"fmt"
	"strings"
	"time"

	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	s3client "github.com/TesslateAI/tesslate-btrfs-csi/pkg/s3"
)

// Config holds configuration for the garbage collector.
type Config struct {
	// Interval between GC runs.
	Interval time.Duration

	// GracePeriod is the minimum age before an orphan is eligible for deletion.
	// Prevents race conditions with in-progress operations.
	GracePeriod time.Duration

	// DryRun logs what would be cleaned without actually deleting.
	DryRun bool
}

// Collector periodically scans for orphaned subvolumes and expired S3 snapshots.
type Collector struct {
	btrfs  *btrfs.Manager
	s3     *s3client.Client
	config Config

	// knownVolumes is a callback that returns the set of volume IDs currently
	// referenced by projects. Subvolumes not in this set are considered orphans.
	// If nil, orphan detection is skipped.
	knownVolumes func(ctx context.Context) (map[string]bool, error)
}

// NewCollector creates a new garbage collector.
func NewCollector(btrfs *btrfs.Manager, s3 *s3client.Client, cfg Config) *Collector {
	return &Collector{
		btrfs:  btrfs,
		s3:     s3,
		config: cfg,
	}
}

// SetKnownVolumesFunc sets the callback for determining which volumes are in use.
func (c *Collector) SetKnownVolumesFunc(fn func(ctx context.Context) (map[string]bool, error)) {
	c.knownVolumes = fn
}

// Start begins the periodic GC loop. Blocks until context is cancelled.
func (c *Collector) Start(ctx context.Context) {
	klog.Infof("GC collector starting (interval=%v, grace=%v, dryRun=%v)",
		c.config.Interval, c.config.GracePeriod, c.config.DryRun)

	ticker := time.NewTicker(c.config.Interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			klog.Info("GC collector stopped")
			return
		case <-ticker.C:
			if err := c.RunOnce(ctx); err != nil {
				klog.Errorf("GC cycle error: %v", err)
			}
		}
	}
}

// RunOnce performs a single GC cycle.
func (c *Collector) RunOnce(ctx context.Context) error {
	klog.V(2).Info("Starting GC cycle")

	orphansDeleted, err := c.cleanOrphanedSubvolumes(ctx)
	if err != nil {
		klog.Errorf("GC orphan cleanup error: %v", err)
	}

	snapshotsDeleted, err := c.cleanOrphanedS3Snapshots(ctx)
	if err != nil {
		klog.Errorf("GC S3 cleanup error: %v", err)
	}

	staleSnaps, err := c.cleanStaleLocalSnapshots(ctx)
	if err != nil {
		klog.Errorf("GC stale snapshot cleanup error: %v", err)
	}

	klog.V(2).Infof("GC cycle complete: orphans=%d, s3_snapshots=%d, stale_local=%d",
		orphansDeleted, snapshotsDeleted, staleSnaps)
	return nil
}

// cleanOrphanedSubvolumes finds volume subvolumes not referenced by any project.
func (c *Collector) cleanOrphanedSubvolumes(ctx context.Context) (int, error) {
	if c.knownVolumes == nil {
		return 0, nil // No way to determine orphans.
	}

	known, err := c.knownVolumes(ctx)
	if err != nil {
		return 0, fmt.Errorf("get known volumes: %w", err)
	}

	subvolumes, err := c.btrfs.ListSubvolumes(ctx, "volumes/")
	if err != nil {
		return 0, fmt.Errorf("list subvolumes: %w", err)
	}

	deleted := 0
	for _, sub := range subvolumes {
		volID := sub.Name
		if known[volID] {
			continue
		}

		// Check grace period. Only delete if older than the grace period.
		if !sub.CreatedAt.IsZero() && time.Since(sub.CreatedAt) < c.config.GracePeriod {
			klog.V(4).Infof("GC: skipping young orphan %q (age=%v)", volID, time.Since(sub.CreatedAt))
			continue
		}

		if c.config.DryRun {
			klog.Infof("GC [dry-run]: would delete orphaned volume %q", volID)
		} else {
			klog.Infof("GC: deleting orphaned volume %q", volID)
			if delErr := c.btrfs.DeleteSubvolume(ctx, sub.Path); delErr != nil {
				klog.Errorf("GC: failed to delete orphan %q: %v", volID, delErr)
				continue
			}
		}
		deleted++
	}

	return deleted, nil
}

// cleanOrphanedS3Snapshots removes S3 objects for volumes that no longer exist.
func (c *Collector) cleanOrphanedS3Snapshots(ctx context.Context) (int, error) {
	if c.s3 == nil || c.knownVolumes == nil {
		return 0, nil
	}

	known, err := c.knownVolumes(ctx)
	if err != nil {
		return 0, fmt.Errorf("get known volumes: %w", err)
	}

	// List all volume prefixes in S3.
	objects, err := c.s3.List(ctx, "volumes/")
	if err != nil {
		return 0, fmt.Errorf("list S3 objects: %w", err)
	}

	// Group by volume ID.
	orphanKeys := make([]string, 0)
	for _, obj := range objects {
		// Key format: volumes/{volumeID}/full-*.zst or incremental-*.zst
		parts := strings.SplitN(strings.TrimPrefix(obj.Key, "volumes/"), "/", 2)
		if len(parts) < 2 {
			continue
		}
		volID := parts[0]
		if !known[volID] {
			orphanKeys = append(orphanKeys, obj.Key)
		}
	}

	deleted := 0
	for _, key := range orphanKeys {
		if c.config.DryRun {
			klog.Infof("GC [dry-run]: would delete S3 object %q", key)
		} else {
			klog.V(4).Infof("GC: deleting S3 object %q", key)
			if delErr := c.s3.Delete(ctx, key); delErr != nil {
				klog.Errorf("GC: failed to delete S3 object %q: %v", key, delErr)
				continue
			}
		}
		deleted++
	}

	return deleted, nil
}

// cleanStaleLocalSnapshots removes local snapshots in the snapshots/ directory
// that are older than the grace period and not associated with active sync tracking.
func (c *Collector) cleanStaleLocalSnapshots(ctx context.Context) (int, error) {
	snapshots, err := c.btrfs.ListSubvolumes(ctx, "snapshots/")
	if err != nil {
		return 0, fmt.Errorf("list snapshots: %w", err)
	}

	deleted := 0
	for _, snap := range snapshots {
		// Skip recent snapshots.
		if !snap.CreatedAt.IsZero() && time.Since(snap.CreatedAt) < c.config.GracePeriod {
			continue
		}

		// Skip active sync snapshots (they contain "@sync-new" in the name).
		if strings.Contains(snap.Name, "@sync-new") {
			continue
		}

		// Skip template upload snapshots.
		if strings.Contains(snap.Name, "-tmpl-upload") {
			continue
		}

		if c.config.DryRun {
			klog.Infof("GC [dry-run]: would delete stale snapshot %q", snap.Name)
		} else {
			klog.V(4).Infof("GC: deleting stale snapshot %q", snap.Name)
			if delErr := c.btrfs.DeleteSubvolume(ctx, snap.Path); delErr != nil {
				klog.Errorf("GC: failed to delete stale snapshot %q: %v", snap.Name, delErr)
				continue
			}
		}
		deleted++
	}

	return deleted, nil
}
