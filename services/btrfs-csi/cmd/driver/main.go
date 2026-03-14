package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
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
		mode         = flag.String("mode", "all", "Driver mode: controller, node, or all")
		nodeOpsAddr  = flag.String("nodeops-addr", "", "NodeOps gRPC address (controller mode, e.g., node-svc:9741)")
		nodeOpsPort  = flag.Int("nodeops-port", 9741, "NodeOps gRPC listen port (node mode)")
		s3Endpoint   = flag.String("s3-endpoint", "", "S3-compatible endpoint for snapshot offload")
		s3Bucket     = flag.String("s3-bucket", "", "S3 bucket for snapshot storage")
		s3AccessKey  = flag.String("s3-access-key", "", "S3 access key")
		s3SecretKey  = flag.String("s3-secret-key", "", "S3 secret key")
		s3Region     = flag.String("s3-region", "us-east-1", "S3 region")
		syncInterval = flag.Duration("sync-interval", 60*time.Second, "Interval between sync daemon runs")
		showVersion  = flag.Bool("version", false, "Print version and exit")
	)

	flag.Parse()

	if *showVersion {
		fmt.Printf("tesslate-btrfs-csi %s (commit: %s)\n", version, commit)
		os.Exit(0)
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
		driver.WithNodeOpsAddr(*nodeOpsAddr),
		driver.WithNodeOpsPort(*nodeOpsPort),
		driver.WithS3Config(*s3Endpoint, *s3Bucket, *s3AccessKey, *s3SecretKey, *s3Region),
		driver.WithSyncInterval(*syncInterval),
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
