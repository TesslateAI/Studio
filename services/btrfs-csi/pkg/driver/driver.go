package driver

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	stdsync "sync"
	"time"

	"github.com/container-storage-interface/spec/lib/go/csi"
	"google.golang.org/grpc"
	"k8s.io/client-go/informers"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/fileops"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/gc"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/metrics"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/nodeops"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/objstore"
	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/volumehub"
)

// Mode determines which CSI services the driver registers.
type Mode string

const (
	ModeNode Mode = "node"
	ModeAll  Mode = "all" // For single-node testing (e.g., minikube)
	ModeHub  Mode = "hub" // Volume Hub + CSI Controller — orchestrates nodes, serves CSI
)

// drainSentinelPath is written after a successful drain to signal the preStop
// hook that all volumes have been synced.  Placed inside the CSI socket
// directory (a dedicated hostPath volume), not /tmp, to avoid CWE-377.
const drainSentinelPath = "/run/csi/drain-complete"

// Driver is the top-level CSI driver struct that ties together all subsystems.
type Driver struct {
	name     string
	version  string
	nodeID   string
	poolPath string
	endpoint string
	mode     Mode

	storageProvider string
	storageBucket   string
	storageEnv      map[string]string

	syncInterval           time.Duration
	consolidationInterval  int
	consolidationRetention int
	nodeOpsPort    int    // Port for nodeops gRPC server (for node mode)
	hubGRPCPort     int // VolumeHub gRPC listen port (hub mode)
	orchestratorURL            string
	orchestratorInternalSecret string // X-Internal-Secret for /api/internal/* endpoints
	drainPort       int
	drainSrv        *http.Server
	defaultQuota    int64 // Default per-volume storage quota in bytes (0 = unlimited)

	// Node-mode subsystems (nil in hub mode).
	btrfs          *btrfs.Manager
	store          objstore.ObjectStorage
	casStore       *cas.Store
	syncer         *bsync.Daemon
	tmplMgr        *template.Manager
	hubAddress     string // VolumeHub gRPC address for safety-net materialization (node mode)
	unpublishWg    stdsync.WaitGroup // tracks async SyncVolume goroutines fired from NodeUnpublishVolume

	// Controller-mode subsystem (nil in node mode).
	nodeOps nodeops.NodeOps

	// Hub-mode subsystem: in-process Hub server for CSI controller delegation.
	hubServer *volumehub.Server

	srv        *grpc.Server
	nodeOpsSrv *nodeops.Server
	fileOpsSrv *fileops.Server
}

// Option configures the Driver via the functional options pattern.
type Option func(*Driver)

func WithName(name string) Option        { return func(d *Driver) { d.name = name } }
func WithVersion(version string) Option  { return func(d *Driver) { d.version = version } }
func WithNodeID(nodeID string) Option    { return func(d *Driver) { d.nodeID = nodeID } }
func WithPoolPath(poolPath string) Option { return func(d *Driver) { d.poolPath = poolPath } }
func WithEndpoint(endpoint string) Option { return func(d *Driver) { d.endpoint = endpoint } }
func WithMode(mode string) Option        { return func(d *Driver) { d.mode = Mode(mode) } }
func WithNodeOpsPort(port int) Option    { return func(d *Driver) { d.nodeOpsPort = port } }

func WithStorageConfig(provider, bucket string, env map[string]string) Option {
	return func(d *Driver) {
		d.storageProvider = provider
		d.storageBucket = bucket
		d.storageEnv = env
	}
}

// Deprecated: Use WithStorageConfig instead.
func WithS3Config(endpoint, bucket, accessKey, secretKey, region string) Option {
	return func(d *Driver) {
		d.storageProvider = "s3"
		d.storageBucket = bucket
		d.storageEnv = map[string]string{
			"RCLONE_S3_PROVIDER":          "AWS",
			"RCLONE_S3_ENDPOINT":          endpoint,
			"RCLONE_S3_ACCESS_KEY_ID":     accessKey,
			"RCLONE_S3_SECRET_ACCESS_KEY": secretKey,
			"RCLONE_S3_REGION":            region,
		}
	}
}

// createObjectStorage builds the appropriate ObjectStorage backend. For S3
// providers it uses the native minio-go client (connection pooling, no process
// overhead). Other providers fall back to rclone.
func createObjectStorage(provider, bucket string, env map[string]string) (objstore.ObjectStorage, error) {
	if provider == "s3" {
		endpoint := env["RCLONE_S3_ENDPOINT"]
		if endpoint == "" {
			return nil, fmt.Errorf("S3 endpoint not configured (set RCLONE_S3_ENDPOINT)")
		}
		cfg := objstore.S3Config{
			Endpoint:       endpoint,
			AccessKeyID:    env["RCLONE_S3_ACCESS_KEY_ID"],
			SecretAccessKey: env["RCLONE_S3_SECRET_ACCESS_KEY"],
			Region:         env["RCLONE_S3_REGION"],
			Bucket:         bucket,
			UseSSL:         objstore.DetectSSL(endpoint),
		}
		return objstore.NewS3Storage(cfg)
	}
	return objstore.NewRcloneStorage(provider, bucket, env)
}

func WithSyncInterval(interval time.Duration) Option {
	return func(d *Driver) { d.syncInterval = interval }
}

func WithConsolidationInterval(n int) Option {
	return func(d *Driver) { d.consolidationInterval = n }
}

func WithConsolidationRetention(n int) Option {
	return func(d *Driver) { d.consolidationRetention = n }
}

func WithHubGRPCPort(grpcPort int) Option {
	return func(d *Driver) {
		d.hubGRPCPort = grpcPort
	}
}

func WithHubAddress(addr string) Option                   { return func(d *Driver) { d.hubAddress = addr } }
func WithOrchestratorURL(url string) Option               { return func(d *Driver) { d.orchestratorURL = url } }
func WithOrchestratorInternalSecret(s string) Option      { return func(d *Driver) { d.orchestratorInternalSecret = s } }
func WithDrainPort(port int) Option         { return func(d *Driver) { d.drainPort = port } }
func WithDefaultQuota(bytes int64) Option   { return func(d *Driver) { d.defaultQuota = bytes } }

// NewDriver creates a new Driver with the given options applied.
func NewDriver(opts ...Option) *Driver {
	d := &Driver{
		name:           "btrfs.csi.tesslate.io",
		version:        "0.1.0",
		syncInterval:           5 * time.Minute,
		consolidationInterval:  10,
		consolidationRetention: 3,
		mode:           ModeAll,
		nodeOpsPort:    9741,
		hubGRPCPort: 9750,
		drainPort:   9743,
	}

	for _, opt := range opts {
		opt(d)
	}

	return d
}

// Run starts the driver in the configured mode.
func (d *Driver) Run(ctx context.Context) error {
	switch d.mode {
	case ModeNode, ModeAll:
		return d.runNode(ctx)
	case ModeHub:
		return d.runHub(ctx)
	default:
		return fmt.Errorf("unknown mode: %s", d.mode)
	}
}

// runNode initializes btrfs subsystems, starts the nodeops server, and
// registers CSI Identity + Node services.
func (d *Driver) runNode(ctx context.Context) error {
	// Initialize btrfs subsystems.
	d.btrfs = btrfs.NewManager(d.poolPath)

	// Ensure pool directories exist (including layers for CAS layer snapshots).
	for _, sub := range []string{"volumes", "snapshots", "templates", "layers"} {
		dir := fmt.Sprintf("%s/%s", d.poolPath, sub)
		if err := os.MkdirAll(dir, 0755); err != nil {
			return fmt.Errorf("failed to create pool directory %s: %w", dir, err)
		}
	}

	// Enable btrfs quotas for per-volume storage limits.
	if err := d.btrfs.EnableQuotas(ctx); err != nil {
		klog.Warningf("Failed to enable btrfs quotas (non-fatal): %v", err)
	}

	// Initialize object storage if configured.
	if d.storageProvider != "" && d.storageBucket != "" {
		store, err := createObjectStorage(d.storageProvider, d.storageBucket, d.storageEnv)
		if err != nil {
			klog.Errorf("Failed to create object storage: %v", err)
		} else {
			if err := store.EnsureBucket(ctx); err != nil {
				klog.Warningf("EnsureBucket: %v (may already exist)", err)
			}
			d.store = store
		}
	}

	// Create CAS store from object storage.
	if d.store != nil {
		d.casStore = cas.NewStore(d.store)
	}

	// Create template manager backed by CAS store.
	d.tmplMgr = template.NewManager(d.btrfs, d.casStore, d.poolPath)

	// Start sync daemon if CAS store is available.
	if d.casStore != nil {
		cfg := bsync.DaemonConfig{
			SafetyInterval:         d.syncInterval,
			ConsolidationInterval:  d.consolidationInterval,
			ConsolidationRetention: d.consolidationRetention,
			NodeID:                 d.nodeID,
		}
		// Hub client for manifest writes (single-writer model).
		// "all" mode: Hub runs in-process → use direct CAS adapter.
		// "node" mode: Hub is a separate pod → use gRPC client.
		if d.mode == ModeAll {
			cfg.Hub = bsync.NewLocalHubOps(d.casStore)
			klog.Info("Sync daemon: using local Hub (all mode)")
		} else if d.hubAddress != "" {
			hubClient, err := volumehub.NewHubClient(d.hubAddress)
			if err != nil {
				klog.Errorf("Failed to create Hub client at %s: %v", d.hubAddress, err)
			} else {
				cfg.Hub = hubClient
				klog.Infof("Sync daemon: using remote Hub at %s", d.hubAddress)
			}
		}
		d.syncer = bsync.NewDaemonWithConfig(d.btrfs, d.casStore, d.tmplMgr, cfg)
		go d.syncer.Start(ctx)
		klog.Info("Sync daemon started (CAS mode)")
	}

	// Start nodeops gRPC server for controller delegation.
	d.nodeOpsSrv = nodeops.NewServer(d.btrfs, d.syncer, d.tmplMgr, d.casStore)

	// Wire the peer transfer send function into the sync daemon so the
	// actor can send volumes to other nodes via the nodeops server's
	// gRPC streaming infrastructure.
	if d.syncer != nil {
		d.syncer.SetSendVolumeFn(d.nodeOpsSrv.SendSubvolumeTo)
	}

	go func() {
		addr := fmt.Sprintf(":%d", d.nodeOpsPort)
		if err := d.nodeOpsSrv.Start(addr, nil); err != nil {
			klog.Errorf("NodeOps server failed: %v", err)
		}
	}()

	// Start FileOps gRPC server for Tier 0 file operations.
	// Pass the sync daemon so writes mark volumes as dirty for sync.
	// Guard: typed nil *Daemon passed to DirtySyncer interface creates a
	// non-nil interface with nil underlying pointer, bypassing nil checks.
	var fileOpsSyncer fileops.DirtySyncer
	if d.syncer != nil {
		fileOpsSyncer = d.syncer
	}
	d.fileOpsSrv = fileops.NewServer(d.poolPath, fileOpsSyncer)
	go func() {
		if err := d.fileOpsSrv.Start(":9742", nil); err != nil {
			klog.Errorf("FileOps server failed: %v", err)
		}
	}()

	// Start Prometheus metrics server.
	go metrics.StartMetricsServer(":9090", "", "")

	// Start garbage collector for orphaned subvolumes and stale snapshots.
	gcCollector := gc.NewCollector(d.btrfs, d.store, gc.Config{
		Interval:    10 * time.Minute,
		GracePeriod: 24 * time.Hour,
		DryRun:      false,
	})
	if d.orchestratorURL != "" {
		gcCollector.SetOrchestratorURL(d.orchestratorURL, d.orchestratorInternalSecret)
		klog.Infof("GC collector wired to orchestrator at %s", d.orchestratorURL)
	}
	go gcCollector.Start(ctx)

	// Start drain HTTP server for preStop hook.
	// Always starts regardless of syncer — when syncer is nil (no CAS/S3),
	// the handler writes the sentinel immediately so the preStop loop exits
	// in seconds instead of polling for 580s.
	{
		// Clean up stale sentinel from a previous run (container restart).
		_ = os.Remove(drainSentinelPath)

		mux := http.NewServeMux()
		mux.HandleFunc("POST /drain", func(w http.ResponseWriter, r *http.Request) {
			klog.Info("Drain request received via HTTP")
			if d.syncer != nil {
				// Use background context — the HTTP client (wget in preStop) may
				// disconnect before drain completes, which would cancel r.Context().
				// Background context ensures drain runs to completion even if the
				// process receives SIGTERM during drain (best-effort data safety).
				// Timeout matches K8s terminationGracePeriodSeconds (600s) as a
				// hard safety net. Parallel drain + 15s sync interval means this
				// should never be hit. Future: replace with per-volume stall detection.
				drainCtx, drainCancel := context.WithTimeout(context.Background(), 10*time.Minute)
				defer drainCancel()
				// Wait for any in-flight async syncs from NodeUnpublishVolume
				// to complete before draining, so their SyncVolume calls don't
				// race with DrainAll on the same volumes.
				d.unpublishWg.Wait()
				if err := d.syncer.DrainAll(drainCtx); err != nil {
					klog.Errorf("Drain failed: %v", err)
					http.Error(w, err.Error(), http.StatusInternalServerError)
					return
				}
			} else {
				klog.Info("Drain: no syncer configured, nothing to drain")
			}
			// Write sentinel file for preStop polling.  Path is inside the CSI
			// socket directory (mounted volume, not shared /tmp).
			_ = os.WriteFile(drainSentinelPath, []byte("ok"), 0600)
			w.WriteHeader(http.StatusOK)
			_, _ = io.WriteString(w, "drain complete\n")
		})
		mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusOK)
			_, _ = io.WriteString(w, "ok\n")
		})
		d.drainSrv = &http.Server{
			Addr:    fmt.Sprintf(":%d", d.drainPort),
			Handler: mux,
		}
		go func() {
			if err := d.drainSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
				klog.Errorf("Drain HTTP server failed: %v", err)
			}
		}()
		klog.Infof("Drain HTTP server listening on :%d", d.drainPort)
	}

	// In "all" mode, also register the CSI controller (for minikube/testing).
	// Uses a local nodeOps implementation that calls btrfs directly.
	if d.mode == ModeAll {
		d.nodeOps = &localNodeOps{
			btrfs:   d.btrfs,
			syncer:  d.syncer,
			tmplMgr: d.tmplMgr,
			cas:     d.casStore,
		}
	}

	// Start CSI gRPC server.
	return d.startCSIServer(ctx)
}

// runHub initializes the Volume Hub — a storageless orchestrator that
// coordinates nodes for volume lifecycle, cache placement, and CAS sync.
// Hub mode serves both the VolumeHub gRPC (TCP :9750) for the Python
// orchestrator and the CSI Controller gRPC (unix socket) for the K8s
// csi-provisioner and csi-snapshotter sidecars.
func (d *Driver) runHub(ctx context.Context) error {
	// Build the node registry and populate with known CSI nodes.
	registry := volumehub.NewNodeRegistry()

	// Initialize object storage for Hub's CAS manifest reads.
	var casStore *cas.Store
	if d.storageProvider != "" && d.storageBucket != "" {
		store, err := createObjectStorage(d.storageProvider, d.storageBucket, d.storageEnv)
		if err != nil {
			klog.Warningf("Hub: failed to create object storage: %v", err)
		} else {
			if err := store.EnsureBucket(ctx); err != nil {
				klog.Warningf("Hub: EnsureBucket: %v (may already exist)", err)
			}
			casStore = cas.NewStore(store)
		}
	}

	// Build in-cluster K8s client. rest.InClusterConfig handles projected
	// service-account token rotation, CA bundle reloading, and TLS — client-go's
	// bearer-token transport re-reads the token file before expiry, so we do
	// not cache any credential material ourselves.
	restCfg, err := rest.InClusterConfig()
	if err != nil {
		return fmt.Errorf("in-cluster config: %w", err)
	}
	restCfg.UserAgent = "tesslate-volumehub/1.0"
	k8sClient, err := kubernetes.NewForConfig(restCfg)
	if err != nil {
		return fmt.Errorf("kubernetes clientset: %w", err)
	}

	// Two informer factories share the same client (and auth transport):
	//   - namespaced (kube-system) for the headless service's Endpoints object
	//   - cluster-scoped for Nodes + Pods (resource headroom math)
	nsFactory := informers.NewSharedInformerFactoryWithOptions(k8sClient, 10*time.Minute,
		informers.WithNamespace("kube-system"))
	clusterFactory := informers.NewSharedInformerFactory(k8sClient, 10*time.Minute)

	resolver := volumehub.NewNodeResolver(nsFactory, "tesslate-btrfs-csi-node-svc", "kube-system", 9741)
	resWatcher := volumehub.NewResourceWatcher(clusterFactory, 30*time.Second)

	// Start factories and block until caches are hot before serving any RPC.
	// This replaces the old "read once at startup" list call — informers
	// manage list+watch with correct bookmarks, 410 Gone handling, and auth.
	nsFactory.Start(ctx.Done())
	clusterFactory.Start(ctx.Done())
	if !resolver.WaitForCacheSync(ctx) {
		return fmt.Errorf("endpoints informer cache never synced")
	}
	if !resWatcher.WaitForCacheSync(ctx) {
		return fmt.Errorf("node/pod informer cache never synced")
	}

	// nodeClientFactory resolves K8s node name → pod IP at connection time.
	// Cache is authoritative once synced; the WaitForCacheSync below is a
	// defensive no-op in the hot path (returns immediately).
	nodeClientFactory := func(nodeName string) (*nodeops.Client, error) {
		addr := resolver.Resolve(nodeName)
		if addr == "" {
			resolver.WaitForCacheSync(ctx)
			addr = resolver.Resolve(nodeName)
			if addr == "" {
				return nil, fmt.Errorf("node %s not found in endpoints", nodeName)
			}
		}
		return nodeops.NewClient(addr, nil)
	}

	go resWatcher.Start(ctx)

	// Start VolumeHub gRPC server with CAS store for manifest reads.
	hubSrv := volumehub.NewServer(registry, casStore, nodeClientFactory, resolver.Resolve, resolver.NodeNames, resWatcher)
	if d.orchestratorURL != "" {
		hubSrv.SetOrchestratorURL(d.orchestratorURL, d.orchestratorInternalSecret)
	}
	d.hubServer = hubSrv // store for CSI controller access

	// Watch K8s Endpoints for CSI node pod changes (~1s latency vs 30s polling).
	// The watch loop's first iteration lists current state and calls onNodeChange,
	// which handles initial discovery — no separate startup goroutine needed.
	//
	// RebuildRegistry runs on each callback to discover new volumes and update
	// cache tracking. Ownership is only set for volumes with no current owner
	// (cold start recovery). Volumes that already have an owner are never
	// reassigned by RebuildRegistry — ownership changes go through
	// CreateVolume, EnsureCached, and DeleteVolume exclusively.
	resolver.StartWatch(ctx, func() {
		if discoverErr := hubSrv.DiscoverNodes(resolver); discoverErr != nil {
			klog.Warningf("DiscoverNodes after watch event: %v", discoverErr)
		}
		if rebuildErr := hubSrv.RebuildRegistry(ctx); rebuildErr != nil {
			klog.Warningf("RebuildRegistry: %v", rebuildErr)
		}
	})

	// Start CacheEvictor — periodically evicts stale cached volumes
	// from non-owner nodes after a grace period.
	evictor := volumehub.NewCacheEvictor(registry, nodeClientFactory)
	go evictor.Start(ctx)

	go func() {
		addr := fmt.Sprintf(":%d", d.hubGRPCPort)
		if err := hubSrv.Start(addr, nil); err != nil {
			klog.Errorf("VolumeHub gRPC server failed: %v", err)
		}
	}()
	hubSrv.StartBackground(ctx) // lease reaper + dead node cleanup
	klog.Infof("VolumeHub gRPC server on :%d", d.hubGRPCPort)

	// Start CSI Controller gRPC on unix socket (for csi-provisioner/snapshotter sidecars).
	if d.endpoint != "" {
		go func() {
			if err := d.startCSIServer(ctx); err != nil {
				klog.Errorf("CSI Controller gRPC server failed: %v", err)
			}
		}()
	}

	// Start Prometheus metrics server.
	go metrics.StartMetricsServer(":9090", "", "")

	// Block until context is cancelled (signal handler in main.go).
	<-ctx.Done()
	hubSrv.Stop()
	// Don't call d.srv.GracefulStop() here — driver.Stop() owns shutdown
	// with a bounded timeout to prevent zombie states.
	klog.Info("Hub mode stopped")
	return nil
}

// startCSIServer starts the gRPC server with the appropriate CSI services.
func (d *Driver) startCSIServer(ctx context.Context) error {
	socketPath := strings.TrimPrefix(d.endpoint, "unix://")
	if err := os.Remove(socketPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("failed to remove stale socket %s: %w", socketPath, err)
	}

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		return fmt.Errorf("failed to listen on %s: %w", socketPath, err)
	}

	d.srv = grpc.NewServer(
		grpc.UnaryInterceptor(loggingInterceptor),
	)

	// Always register Identity.
	csi.RegisterIdentityServer(d.srv, NewIdentityServer(d))

	// Register services based on mode.
	switch d.mode {
	case ModeHub:
		csi.RegisterControllerServer(d.srv, NewControllerServer(d, d.hubServer))
		klog.Info("Registered CSI Identity + Controller services (Hub-delegated)")
	case ModeNode:
		csi.RegisterNodeServer(d.srv, NewNodeServer(d))
		klog.Info("Registered CSI Identity + Node services")
	case ModeAll:
		csi.RegisterControllerServer(d.srv, NewControllerServer(d, nil))
		csi.RegisterNodeServer(d.srv, NewNodeServer(d))
		klog.Info("Registered CSI Identity + Controller + Node services")
	}

	klog.Infof("CSI driver %q listening on %s (mode=%s)", d.name, socketPath, d.mode)

	errCh := make(chan error, 1)
	go func() {
		errCh <- d.srv.Serve(listener)
	}()

	// Socket watchdog: Serve() keeps running on the open fd even if the
	// socket inode is deleted externally (kubelet cleanup, node maintenance).
	// Kubelet can no longer dial the path, so all volume mounts fail silently.
	// Detect this and force-stop so the container restarts with a fresh socket.
	go func() {
		ticker := time.NewTicker(5 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if _, err := os.Stat(socketPath); os.IsNotExist(err) {
					klog.Errorf("CSI socket %s disappeared — forcing shutdown so kubelet restarts the container", socketPath)
					d.srv.Stop() // causes Serve() to return → errCh fires → process exits
					return
				}
			}
		}
	}()

	select {
	case <-ctx.Done():
		klog.Info("Context cancelled, CSI server will be stopped by driver.Stop()")
		<-errCh // Wait for Serve() to return after Stop() kills it
		return nil
	case err := <-errCh:
		return err
	}
}

// Stop performs a graceful shutdown of the driver. Each gRPC server gets a
// bounded grace period before being force-killed to prevent zombie states
// where the Unix socket is deleted but the process hangs on in-flight RPCs.
func (d *Driver) Stop() {
	if d.drainSrv != nil {
		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer shutdownCancel()
		d.drainSrv.Shutdown(shutdownCtx)
	}
	const grpcTimeout = 10 * time.Second
	if d.fileOpsSrv != nil {
		gracefulStopWithTimeout(d.fileOpsSrv.GrpcServer(), grpcTimeout)
	}
	if d.nodeOpsSrv != nil {
		gracefulStopWithTimeout(d.nodeOpsSrv.GrpcServer(), grpcTimeout)
	}
	gracefulStopWithTimeout(d.srv, grpcTimeout)
	klog.Info("Driver stopped")
}

// gracefulStopWithTimeout attempts GracefulStop on a gRPC server. If it
// doesn't complete within the timeout, it calls Stop() to force-kill all
// connections. This prevents zombie states where GracefulStop deletes the
// Unix socket file (via listener.Close) but blocks indefinitely waiting
// for in-flight RPCs.
func gracefulStopWithTimeout(srv *grpc.Server, timeout time.Duration) {
	if srv == nil {
		return
	}
	done := make(chan struct{})
	go func() {
		srv.GracefulStop()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(timeout):
		klog.Warningf("gRPC GracefulStop did not complete in %v, forcing Stop()", timeout)
		srv.Stop()
		<-done // Wait for GracefulStop goroutine to return (Stop unblocks it)
	}
}

// loggingInterceptor logs all gRPC calls with their method name and duration.
func loggingInterceptor(
	ctx context.Context,
	req any,
	info *grpc.UnaryServerInfo,
	handler grpc.UnaryHandler,
) (any, error) {
	start := time.Now()
	resp, err := handler(ctx, req)
	duration := time.Since(start)

	if err != nil {
		klog.Errorf("%s failed after %v: %v", info.FullMethod, duration, err)
	} else {
		klog.V(4).Infof("%s completed in %v", info.FullMethod, duration)
	}

	return resp, err
}

// localNodeOps implements NodeOps by calling btrfs directly (for "all" mode).
type localNodeOps struct {
	btrfs   *btrfs.Manager
	syncer  *bsync.Daemon
	tmplMgr *template.Manager
	cas     *cas.Store
}

func (l *localNodeOps) CreateSubvolume(ctx context.Context, name string) error {
	return l.btrfs.CreateSubvolume(ctx, name)
}

func (l *localNodeOps) DeleteSubvolume(ctx context.Context, name string) error {
	return l.btrfs.DeleteSubvolume(ctx, name)
}

func (l *localNodeOps) SnapshotSubvolume(ctx context.Context, source, dest string, readOnly bool) error {
	return l.btrfs.SnapshotSubvolume(ctx, source, dest, readOnly)
}

func (l *localNodeOps) SubvolumeExists(ctx context.Context, name string) (bool, error) {
	return l.btrfs.SubvolumeExists(ctx, name), nil
}

func (l *localNodeOps) GetCapacity(ctx context.Context) (int64, int64, error) {
	return l.btrfs.GetCapacity(ctx)
}

func (l *localNodeOps) ListSubvolumes(ctx context.Context, prefix string) ([]nodeops.SubvolumeInfo, error) {
	subs, err := l.btrfs.ListSubvolumes(ctx, prefix)
	if err != nil {
		return nil, err
	}
	var infos []nodeops.SubvolumeInfo
	for _, s := range subs {
		infos = append(infos, nodeops.SubvolumeInfo{
			ID: s.ID, Name: s.Name, Path: s.Path, ReadOnly: s.ReadOnly,
		})
	}
	return infos, nil
}

func (l *localNodeOps) TrackVolume(_ context.Context, volumeID, templateName, templateHash string) error {
	if l.syncer != nil {
		l.syncer.TrackVolume(volumeID, templateName, templateHash)
	}
	return nil
}

func (l *localNodeOps) UntrackVolume(_ context.Context, volumeID string) error {
	if l.syncer != nil {
		l.syncer.UntrackVolume(volumeID)
	}
	return nil
}

func (l *localNodeOps) EnsureTemplate(ctx context.Context, name string) error {
	return l.tmplMgr.EnsureTemplate(ctx, name)
}

func (l *localNodeOps) RestoreVolume(ctx context.Context, volumeID string) error {
	if l.syncer == nil {
		return fmt.Errorf("CAS sync not configured, cannot restore volume %q", volumeID)
	}
	return l.syncer.RestoreVolume(ctx, volumeID)
}

func (l *localNodeOps) PromoteToTemplate(ctx context.Context, volumeID, templateName string) error {
	volPath := fmt.Sprintf("volumes/%s", volumeID)
	tmplPath := fmt.Sprintf("templates/%s", templateName)
	if l.btrfs.SubvolumeExists(ctx, tmplPath) {
		if err := l.btrfs.DeleteSubvolume(ctx, tmplPath); err != nil {
			return fmt.Errorf("delete existing template: %w", err)
		}
	}
	if err := l.btrfs.SnapshotSubvolume(ctx, volPath, tmplPath, true); err != nil {
		return fmt.Errorf("snapshot to template: %w", err)
	}
	if _, err := l.tmplMgr.UploadTemplate(ctx, templateName); err != nil {
		return fmt.Errorf("upload template: %w", err)
	}
	if err := l.btrfs.DeleteSubvolume(ctx, volPath); err != nil {
		return fmt.Errorf("cleanup build volume: %w", err)
	}
	return nil
}

func (l *localNodeOps) SetOwnership(ctx context.Context, name string, uid, gid int) error {
	return l.btrfs.SetOwnership(ctx, name, uid, gid)
}

func (l *localNodeOps) SyncVolume(ctx context.Context, volumeID string) error {
	if l.syncer == nil {
		return fmt.Errorf("CAS sync not configured")
	}
	return l.syncer.SyncVolume(ctx, volumeID)
}

func (l *localNodeOps) DeleteVolumeCAS(ctx context.Context, volumeID string) error {
	if l.syncer == nil {
		return nil
	}
	return l.syncer.DeleteVolume(ctx, volumeID)
}

func (l *localNodeOps) GetSyncState(_ context.Context) ([]nodeops.TrackedVolumeState, error) {
	if l.syncer == nil {
		return nil, nil
	}
	daemonStates := l.syncer.GetTrackedState()
	result := make([]nodeops.TrackedVolumeState, len(daemonStates))
	for i, s := range daemonStates {
		result[i] = nodeops.TrackedVolumeState{
			VolumeID:     s.VolumeID,
			TemplateHash: s.TemplateHash,
			LastSyncAt:   s.LastSyncAt,
			Dirty:        s.Dirty,
			HeadHash:     s.HeadHash,
		}
	}
	return result, nil
}

func (l *localNodeOps) SendVolumeTo(_ context.Context, _, _ string) error {
	return fmt.Errorf("SendVolumeTo not supported in all-in-one mode")
}

func (l *localNodeOps) SendTemplateTo(_ context.Context, _, _ string) error {
	return fmt.Errorf("SendTemplateTo not supported in all-in-one mode")
}

func (l *localNodeOps) HasBlobs(ctx context.Context, hashes []string) ([]bool, error) {
	results := make([]bool, len(hashes))
	if l.cas == nil {
		return results, nil
	}
	for i, hash := range hashes {
		exists, err := l.cas.HasBlob(ctx, hash)
		if err == nil && exists {
			results[i] = true
		}
	}
	return results, nil
}

func (l *localNodeOps) CreateUserSnapshot(ctx context.Context, volumeID, label string) (string, error) {
	if l.syncer == nil {
		return "", fmt.Errorf("CAS sync not configured")
	}
	return l.syncer.CreateSnapshot(ctx, volumeID, label)
}

func (l *localNodeOps) RestoreFromSnapshot(ctx context.Context, volumeID, targetHash string) error {
	if l.syncer == nil {
		return fmt.Errorf("CAS sync not configured")
	}
	return l.syncer.RestoreToSnapshot(ctx, volumeID, targetHash)
}

func (l *localNodeOps) GetVolumeMetadata(ctx context.Context, volumeID string) (*nodeops.VolumeMetadata, error) {
	if l.syncer == nil {
		return nil, fmt.Errorf("CAS sync not configured")
	}
	manifest, err := l.syncer.GetManifest(ctx, volumeID)
	if err != nil {
		return nil, err
	}
	meta := &nodeops.VolumeMetadata{
		VolumeID:     manifest.VolumeID,
		TemplateName: manifest.TemplateName,
		TemplateHash: manifest.Base,
		LatestHash:   manifest.LatestHash(),
		LayerCount:   manifest.SnapshotCount(),
	}
	meta.Snapshots = manifest.ListCheckpoints()
	return meta, nil
}

func (l *localNodeOps) SetQgroupLimit(ctx context.Context, name string, bytes int64) error {
	return l.btrfs.SetQgroupLimit(ctx, name, bytes)
}

func (l *localNodeOps) GetQgroupUsage(ctx context.Context, name string) (int64, int64, error) {
	return l.btrfs.GetQgroupUsage(ctx, name)
}
