package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/driver"
	"k8s.io/klog/v2"
)

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
		syncInterval   = flag.Duration("sync-interval", 60*time.Second, "Interval between sync daemon runs")
		hubGRPCPort     = flag.Int("hub-grpc-port", 9750, "VolumeHub gRPC listen port (hub mode)")
		orchestratorURL = flag.String("orchestrator-url", "", "Orchestrator base URL for GC known-volumes (e.g., http://tesslate-backend:8000)")
		drainPort       = flag.Int("drain-port", 9743, "HTTP port for drain endpoint (preStop hook)")
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
		driver.WithHubGRPCPort(*hubGRPCPort),
		driver.WithOrchestratorURL(*orchestratorURL),
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
		drv.Stop()
	case err := <-errCh:
		if err != nil {
			klog.Fatalf("Driver exited with error: %v", err)
		}
	}
	cancel()

	klog.Info("Driver stopped")
	klog.Flush()
}

