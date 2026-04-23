package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"runtime/debug"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/driver"
	"k8s.io/klog/v2"
)

func init() {
	// Set GOMEMLIMIT from the container's cgroup memory limit so Go's GC
	// gets aggressive before the OOM killer fires. Leaves 10% headroom
	// for non-heap allocations (goroutine stacks, mmap, etc.).
	//
	// This replaces what GOMEMLIMIT=auto would do in Go 1.24+, but works
	// on all versions and doesn't require env var configuration in K8s.
	if limit := readCgroupMemoryLimit(); limit > 0 {
		softLimit := int64(float64(limit) * 0.9)
		debug.SetMemoryLimit(softLimit)
		klog.Infof("GOMEMLIMIT set to %d MiB (cgroup limit: %d MiB)",
			softLimit/(1024*1024), limit/(1024*1024))
	}
}

// readCgroupMemoryLimit reads the container memory limit from cgroup v2/v1.
func readCgroupMemoryLimit() int64 {
	// cgroup v2
	if data, err := os.ReadFile("/sys/fs/cgroup/memory.max"); err == nil {
		s := strings.TrimSpace(string(data))
		if s != "max" {
			if v, err := strconv.ParseInt(s, 10, 64); err == nil {
				return v
			}
		}
	}
	// cgroup v1
	if data, err := os.ReadFile("/sys/fs/cgroup/memory/memory.limit_in_bytes"); err == nil {
		if v, err := strconv.ParseInt(strings.TrimSpace(string(data)), 10, 64); err == nil {
			// cgroup v1 reports a huge number when unlimited
			if v < 1<<62 {
				return v
			}
		}
	}
	return 0
}

var (
	version = "0.1.0"
	commit  = "unknown"
)

func main() {
	klog.InitFlags(nil)

	var (
		endpoint     = flag.String("endpoint", "/run/csi/socket", "CSI Unix socket path")
		nodeID       = flag.String("node-id", "", "Node hostname / identifier")
		poolPath     = flag.String("pool-path", "/mnt/tesslate-pool", "Path to btrfs pool mount")
		driverName   = flag.String("driver-name", "btrfs.csi.tesslate.io", "CSI driver name")
		mode         = flag.String("mode", "all", "Driver mode: node, hub, or all")
		nodeOpsPort  = flag.Int("nodeops-port", 9741, "NodeOps gRPC listen port (node mode)")
		storageProvider = flag.String("storage-provider", "", "Object storage provider (s3, gcs, azureblob)")
		storageBucket   = flag.String("storage-bucket", "", "Object storage bucket name")
		// Deprecated: use --storage-provider/--storage-bucket + RCLONE_* env vars
		s3Endpoint  = flag.String("s3-endpoint", "", "(deprecated) S3-compatible endpoint")
		s3Bucket    = flag.String("s3-bucket", "", "(deprecated) S3 bucket for snapshot storage")
		s3AccessKey = flag.String("s3-access-key", "", "(deprecated) S3 access key")
		s3SecretKey = flag.String("s3-secret-key", "", "(deprecated) S3 secret key")
		s3Region    = flag.String("s3-region", "us-east-1", "(deprecated) S3 region")
		syncInterval           = flag.Duration("sync-interval", 5*time.Minute, "Safety-net periodic sync interval")
		consolidationInterval  = flag.Int("consolidation-interval", 10, "Create consolidation every N snapshots (0 to disable)")
		consolidationRetention = flag.Int("consolidation-retention", 3, "Keep last N consolidation blobs (0 = keep all)")
		hubGRPCPort     = flag.Int("hub-grpc-port", 9750, "VolumeHub gRPC listen port (hub mode)")
		orchestratorURL            = flag.String("orchestrator-url", "", "Orchestrator base URL for GC known-volumes (e.g., http://tesslate-backend:8000)")
		orchestratorInternalSecret = flag.String("orchestrator-internal-secret", "", "X-Internal-Secret value for /api/internal/* endpoints (required in k8s)")
		drainPort       = flag.Int("drain-port", 9743, "HTTP port for drain endpoint (preStop hook)")
		hubAddress     = flag.String("hub-address", "tesslate-volume-hub.kube-system.svc:9750", "VolumeHub gRPC address for CSI safety-net materialization (node mode)")
		defaultQuota   = flag.String("default-quota", "", "Default per-volume storage quota (e.g., 5Gi, 500Mi)")
		showVersion    = flag.Bool("version", false, "Print version and exit")
	)

	flag.Parse()

	if *showVersion {
		fmt.Printf("tesslate-btrfs-csi %s (commit: %s)\n", version, commit)
		os.Exit(0)
	}

	// Env var fallbacks for storage configuration.
	if *storageProvider == "" {
		if v := os.Getenv("STORAGE_PROVIDER"); v != "" {
			*storageProvider = v
		}
	}
	if *storageBucket == "" {
		if v := os.Getenv("STORAGE_BUCKET"); v != "" {
			*storageBucket = v
		}
	}

	if *orchestratorURL == "" {
		if v := os.Getenv("ORCHESTRATOR_URL"); v != "" {
			*orchestratorURL = v
		}
	}
	if *orchestratorInternalSecret == "" {
		if v := os.Getenv("ORCHESTRATOR_INTERNAL_SECRET"); v != "" {
			*orchestratorInternalSecret = v
		}
	}

	// Deprecated S3 flag compatibility: map old flags to new config.
	if *storageProvider == "" && *s3Endpoint != "" {
		klog.Warning("--s3-* flags are deprecated; use --storage-provider + RCLONE_* env vars")
		*storageProvider = "s3"
		if *storageBucket == "" {
			*storageBucket = *s3Bucket
		}
	}

	// Collect RCLONE_* env vars for object storage configuration.
	storageEnvMap := make(map[string]string)
	for _, env := range os.Environ() {
		if strings.HasPrefix(env, "RCLONE_") {
			parts := strings.SplitN(env, "=", 2)
			if len(parts) == 2 {
				storageEnvMap[parts[0]] = parts[1]
			}
		}
	}

	// If using deprecated S3 flags and no RCLONE_* vars set, map them.
	if *s3Endpoint != "" && len(storageEnvMap) == 0 {
		storageEnvMap["RCLONE_S3_PROVIDER"] = "AWS"
		storageEnvMap["RCLONE_S3_ENDPOINT"] = *s3Endpoint
		storageEnvMap["RCLONE_S3_ACCESS_KEY_ID"] = *s3AccessKey
		storageEnvMap["RCLONE_S3_SECRET_ACCESS_KEY"] = *s3SecretKey
		storageEnvMap["RCLONE_S3_REGION"] = *s3Region
	}

	if *nodeID == "" {
		hostname, err := os.Hostname()
		if err != nil {
			klog.Fatalf("Failed to get hostname and --node-id not set: %v", err)
		}
		*nodeID = hostname
	}

	klog.Infof("Starting tesslate-btrfs-csi driver %s (commit: %s, mode: %s)", version, commit, *mode)
	klog.Infof("Node ID: %s, Pool: %s, Endpoint: %s", *nodeID, *poolPath, *endpoint)

	drv := driver.NewDriver(
		driver.WithName(*driverName),
		driver.WithVersion(version),
		driver.WithNodeID(*nodeID),
		driver.WithPoolPath(*poolPath),
		driver.WithEndpoint(*endpoint),
		driver.WithMode(*mode),
		driver.WithNodeOpsPort(*nodeOpsPort),
		driver.WithStorageConfig(*storageProvider, *storageBucket, storageEnvMap),
		driver.WithSyncInterval(*syncInterval),
		driver.WithConsolidationInterval(*consolidationInterval),
		driver.WithConsolidationRetention(*consolidationRetention),
		driver.WithHubGRPCPort(*hubGRPCPort),
		driver.WithHubAddress(*hubAddress),
		driver.WithOrchestratorURL(*orchestratorURL),
		driver.WithOrchestratorInternalSecret(*orchestratorInternalSecret),
		driver.WithDrainPort(*drainPort),
		driver.WithDefaultQuota(driver.ParseQuota(*defaultQuota)),
	)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)

	errCh := make(chan error, 1)
	go func() {
		errCh <- drv.Run(ctx)
	}()

	select {
	case sig := <-sigCh:
		klog.Infof("Received signal %v, shutting down", sig)
		cancel()   // Cancel context first — propagates to all goroutines
		drv.Stop() // Then shut down servers with bounded timeouts
	case err := <-errCh:
		if err != nil {
			klog.Fatalf("Driver exited with error: %v", err)
		}
	}
	cancel()

	klog.Info("Driver stopped")
	klog.Flush()
}

