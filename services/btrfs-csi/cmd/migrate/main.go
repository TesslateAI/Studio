// migrate upgrades CAS manifests and on-disk state from the legacy
// template-based sync format to the incremental-chain snapshot model.
//
// Usage:
//
//	migrate --dry-run              # preview changes
//	migrate --execute              # perform migration
//	migrate --validate             # verify post-migration state
//	migrate --execute --skip-disk  # S3-only (no btrfs access needed)
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/objstore"
)

func main() {
	klog.InitFlags(nil)

	var (
		storageProvider = flag.String("storage-provider", "", "Object storage provider (s3, gcs, azureblob)")
		storageBucket   = flag.String("storage-bucket", "", "Object storage bucket")
		poolPath        = flag.String("pool-path", "/mnt/tesslate-pool", "btrfs pool mount path")
		dryRun          = flag.Bool("dry-run", false, "Preview changes without writing")
		execute         = flag.Bool("execute", false, "Perform migration")
		validate        = flag.Bool("validate", false, "Verify post-migration state")
		_               = flag.Bool("skip-blobs", false, "Skip blob integrity check (reserved for future use)")
		skipDisk        = flag.Bool("skip-disk", false, "Skip on-disk cleanup (S3-only)")
	)
	flag.Parse()

	// Env var fallbacks.
	if *storageProvider == "" {
		*storageProvider = os.Getenv("STORAGE_PROVIDER")
	}
	if *storageBucket == "" {
		*storageBucket = os.Getenv("STORAGE_BUCKET")
	}

	modeCount := 0
	if *dryRun {
		modeCount++
	}
	if *execute {
		modeCount++
	}
	if *validate {
		modeCount++
	}
	if modeCount != 1 {
		fmt.Fprintln(os.Stderr, "exactly one of --dry-run, --execute, or --validate is required")
		os.Exit(2)
	}

	if *storageProvider == "" || *storageBucket == "" {
		fmt.Fprintln(os.Stderr, "--storage-provider and --storage-bucket are required (or STORAGE_PROVIDER/STORAGE_BUCKET env vars)")
		os.Exit(2)
	}

	// Collect RCLONE_* env vars.
	storageEnv := make(map[string]string)
	for _, env := range os.Environ() {
		if strings.HasPrefix(env, "RCLONE_") {
			parts := strings.SplitN(env, "=", 2)
			if len(parts) == 2 {
				storageEnv[parts[0]] = parts[1]
			}
		}
	}

	store, err := objstore.NewRcloneStorage(*storageProvider, *storageBucket, storageEnv)
	if err != nil {
		klog.Fatalf("Failed to create object storage: %v", err)
	}

	casStore := cas.NewStore(store)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()

	var bm *btrfs.Manager
	if !*skipDisk {
		bm = btrfs.NewManager(*poolPath)
	}

	switch {
	case *dryRun:
		os.Exit(runMigration(ctx, casStore, store, bm, true))
	case *execute:
		os.Exit(runMigration(ctx, casStore, store, bm, false))
	case *validate:
		os.Exit(runValidation(ctx, casStore, store))
	}
}

// stats tracks migration progress.
type stats struct {
	total             int
	migrated          int // consolidation marked
	normalized        int // format-only (layers→snapshots)
	alreadyCurrent    int
	errors            int
	syntheticsCleaned int
	blobsMissing      int
	blobsChecked      int
}

func (s stats) String() string {
	return fmt.Sprintf(
		"total=%d migrated=%d normalized=%d current=%d errors=%d synthetics=%d blobs_checked=%d blobs_missing=%d",
		s.total, s.migrated, s.normalized, s.alreadyCurrent, s.errors,
		s.syntheticsCleaned, s.blobsChecked, s.blobsMissing,
	)
}

func runMigration(ctx context.Context, casStore *cas.Store, obj objstore.ObjectStorage, bm *btrfs.Manager, dryRun bool) int {
	mode := "EXECUTE"
	if dryRun {
		mode = "DRY-RUN"
	}
	klog.Infof("[%s] Starting CAS manifest migration", mode)

	var st stats

	// --- Step 1: List all manifests ---
	manifests, err := obj.List(ctx, "manifests/")
	if err != nil {
		klog.Errorf("Failed to list manifests: %v", err)
		return 1
	}

	var volumeIDs []string
	for _, m := range manifests {
		name := m.Key
		name = strings.TrimPrefix(name, "manifests/")
		name = strings.TrimSuffix(name, ".json")
		if name == "" || strings.HasPrefix(name, "_backup/") {
			continue
		}
		volumeIDs = append(volumeIDs, name)
	}
	st.total = len(volumeIDs)
	klog.Infof("[%s] Found %d manifests to process", mode, st.total)

	// --- Step 2: Backup manifests ---
	if !dryRun {
		klog.Info("[EXECUTE] Backing up manifests to manifests/_backup/...")
		for _, volID := range volumeIDs {
			src := fmt.Sprintf("manifests/%s.json", volID)
			dst := fmt.Sprintf("manifests/_backup/%s.json", volID)
			if err := obj.Copy(ctx, src, dst); err != nil {
				klog.Warningf("  Backup %s: %v (continuing)", volID, err)
			}
		}
		klog.Infof("[EXECUTE] Backed up %d manifests", len(volumeIDs))
	}

	// --- Step 3: Migrate each manifest ---
	for _, volID := range volumeIDs {
		manifest, err := casStore.GetManifest(ctx, volID)
		if err != nil {
			klog.Errorf("  %s: failed to read manifest: %v", volID, err)
			st.errors++
			continue
		}

		migrated := manifest.Migrate()
		if migrated {
			st.migrated++
			klog.Infof("  %s: MIGRATE — %d layers, marked latest as consolidation", volID, len(manifest.Snapshots))
			if !dryRun {
				if err := casStore.PutManifest(ctx, manifest); err != nil {
					klog.Errorf("  %s: failed to write migrated manifest: %v", volID, err)
					st.errors++
					continue
				}
			}
		} else if len(manifest.Snapshots) > 0 {
			// GetManifest normalized the format in memory. Check if the
			// manifest had legacy format by trying to write — PutManifest
			// always writes the new format.
			// We detect this by re-reading the raw JSON.
			rawNeedsNormalize := false
			if raw, err := obj.Download(ctx, fmt.Sprintf("manifests/%s.json", volID)); err == nil {
				buf := make([]byte, 256)
				n, _ := raw.Read(buf)
				raw.Close()
				if strings.Contains(string(buf[:n]), `"layers"`) {
					rawNeedsNormalize = true
				}
			}

			if rawNeedsNormalize {
				st.normalized++
				klog.Infof("  %s: NORMALIZE — format only (layers→snapshots)", volID)
				if !dryRun {
					if err := casStore.PutManifest(ctx, manifest); err != nil {
						klog.Errorf("  %s: failed to write normalized manifest: %v", volID, err)
						st.errors++
					}
				}
			} else {
				st.alreadyCurrent++
				klog.V(2).Infof("  %s: current (%d snapshots)", volID, len(manifest.Snapshots))
			}
		} else {
			st.alreadyCurrent++
			klog.V(2).Infof("  %s: current (empty)", volID)
		}
	}

	// --- Step 4: Clean synthetic templates ---
	if bm != nil {
		klog.Infof("[%s] Checking for synthetic templates...", mode)
		subs, err := bm.ListSubvolumes(ctx, "templates/")
		if err != nil {
			klog.Warningf("  Failed to list templates: %v", err)
		} else {
			for _, sub := range subs {
				name := strings.TrimPrefix(sub.Path, "templates/")
				if !strings.HasPrefix(name, "_vol_") {
					continue
				}
				klog.Infof("  %s: synthetic template", sub.Path)
				if !dryRun {
					if err := bm.DeleteSubvolume(ctx, sub.Path); err != nil {
						klog.Warningf("  %s: failed to delete: %v", sub.Path, err)
					} else {
						st.syntheticsCleaned++
					}
				} else {
					st.syntheticsCleaned++
				}
			}
		}
	} else {
		klog.Info("[SKIP] Disk cleanup skipped (--skip-disk)")
	}

	// --- Step 5: Report ---
	klog.Infof("")
	klog.Infof("=== MIGRATION %s REPORT ===", mode)
	klog.Infof("  Manifests total:      %d", st.total)
	klog.Infof("  Migrated (consol):    %d", st.migrated)
	klog.Infof("  Normalized (format):  %d", st.normalized)
	klog.Infof("  Already current:      %d", st.alreadyCurrent)
	klog.Infof("  Synthetic templates:  %d", st.syntheticsCleaned)
	klog.Infof("  Errors:               %d", st.errors)

	if st.errors > 0 {
		klog.Errorf("Migration completed with %d errors", st.errors)
		return 1
	}
	klog.Infof("Migration %s completed successfully", mode)
	return 0
}

func runValidation(ctx context.Context, casStore *cas.Store, obj objstore.ObjectStorage) int {
	klog.Info("[VALIDATE] Verifying all manifests are in current format")

	manifests, err := obj.List(ctx, "manifests/")
	if err != nil {
		klog.Errorf("Failed to list manifests: %v", err)
		return 1
	}

	issues := 0
	checked := 0

	for _, m := range manifests {
		name := strings.TrimPrefix(m.Key, "manifests/")
		name = strings.TrimSuffix(name, ".json")
		if name == "" || strings.HasPrefix(name, "_backup/") {
			continue
		}

		checked++

		// Check raw format (should have "snapshots", not "layers").
		raw, err := obj.Download(ctx, m.Key)
		if err != nil {
			klog.Errorf("  %s: failed to download: %v", name, err)
			issues++
			continue
		}
		buf := make([]byte, 512)
		n, _ := raw.Read(buf)
		raw.Close()
		content := string(buf[:n])

		if strings.Contains(content, `"layers"`) {
			klog.Errorf("  %s: FAIL — still has legacy 'layers' key", name)
			issues++
			continue
		}
		if strings.Contains(content, `"type"`) && !strings.Contains(content, `"item_type"`) {
			klog.Errorf("  %s: FAIL — still has legacy 'type' field", name)
			issues++
			continue
		}

		// Parse and check structure.
		manifest, err := casStore.GetManifest(ctx, name)
		if err != nil {
			klog.Errorf("  %s: FAIL — cannot parse: %v", name, err)
			issues++
			continue
		}

		if manifest.NeedsMigration() {
			klog.Errorf("  %s: FAIL — needs consolidation migration (%d layers, all parent=base)", name, len(manifest.Snapshots))
			issues++
			continue
		}

		klog.V(2).Infof("  %s: OK (%d snapshots)", name, len(manifest.Snapshots))
	}

	klog.Infof("")
	klog.Infof("=== VALIDATION REPORT ===")
	klog.Infof("  Manifests checked: %d", checked)
	klog.Infof("  Issues found:      %d", issues)

	if issues > 0 {
		klog.Errorf("Validation FAILED — %d manifests need attention", issues)
		return 1
	}
	klog.Info("Validation PASSED — all manifests are current")
	return 0
}
