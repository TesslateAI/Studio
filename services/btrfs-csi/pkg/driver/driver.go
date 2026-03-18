package driver

import (
	"context"
	"fmt"
	"net"
	"os"
	"strings"
	"time"

	"github.com/container-storage-interface/spec/lib/go/csi"
	"google.golang.org/grpc"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
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
	ModeController Mode = "controller"
	ModeNode       Mode = "node"
	ModeAll        Mode = "all" // For single-node testing (e.g., minikube)
	ModeHub        Mode = "hub" // Volume Hub — canonical store, S3 gateway, cache orchestrator
)

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

	syncInterval   time.Duration
	nodeOpsAddr    string // Address of nodeops gRPC server (for controller mode)
	nodeOpsPort    int    // Port for nodeops gRPC server (for node mode)
	hubGRPCPort int // VolumeHub gRPC listen port (hub mode)

	// Node-mode subsystems (nil in controller mode).
	btrfs   *btrfs.Manager
	store   objstore.ObjectStorage
	syncer  *bsync.Daemon
	tmplMgr *template.Manager

	// Controller-mode subsystem (nil in node mode).
	nodeOps nodeops.NodeOps

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
func WithNodeOpsAddr(addr string) Option { return func(d *Driver) { d.nodeOpsAddr = addr } }
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

func WithSyncInterval(interval time.Duration) Option {
	return func(d *Driver) { d.syncInterval = interval }
}

func WithHubGRPCPort(grpcPort int) Option {
	return func(d *Driver) {
		d.hubGRPCPort = grpcPort
	}
}

// NewDriver creates a new Driver with the given options applied.
func NewDriver(opts ...Option) *Driver {
	d := &Driver{
		name:           "btrfs.csi.tesslate.io",
		version:        "0.1.0",
		syncInterval:   60 * time.Second,
		mode:           ModeAll,
		nodeOpsPort:    9741,
		hubGRPCPort: 9750,
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
	case ModeController:
		return d.runController(ctx)
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

	// Ensure pool directories exist.
	for _, sub := range []string{"volumes", "snapshots", "templates"} {
		dir := fmt.Sprintf("%s/%s", d.poolPath, sub)
		if err := os.MkdirAll(dir, 0755); err != nil {
			return fmt.Errorf("failed to create pool directory %s: %w", dir, err)
		}
	}

	// Initialize object storage if configured.
	if d.storageProvider != "" && d.storageBucket != "" {
		store, err := objstore.NewRcloneStorage(d.storageProvider, d.storageBucket, d.storageEnv)
		if err != nil {
			klog.Errorf("Failed to create object storage: %v", err)
		} else {
			d.store = store
		}
	}

	// Start sync daemon if object storage is configured.
	if d.store != nil {
		d.syncer = bsync.NewDaemon(d.btrfs, d.store, d.syncInterval)
		go d.syncer.Start(ctx)
		klog.Info("Sync daemon started")
	}

	d.tmplMgr = template.NewManager(d.btrfs, d.store, d.poolPath)

	// Start nodeops gRPC server for controller delegation.
	d.nodeOpsSrv = nodeops.NewServer(d.btrfs, d.syncer, d.tmplMgr, d.store)
	go func() {
		addr := fmt.Sprintf(":%d", d.nodeOpsPort)
		if err := d.nodeOpsSrv.Start(addr, nil); err != nil {
			klog.Errorf("NodeOps server failed: %v", err)
		}
	}()

	// Start FileOps gRPC server for Tier 0 file operations.
	d.fileOpsSrv = fileops.NewServer(d.poolPath)
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
	go gcCollector.Start(ctx)

	// In "all" mode, also register the controller (for minikube/testing).
	// The controller uses a local nodeops implementation that calls btrfs directly.
	if d.mode == ModeAll {
		d.nodeOps = &localNodeOps{
			btrfs:   d.btrfs,
			syncer:  d.syncer,
			tmplMgr: d.tmplMgr,
		}
	}

	// Start CSI gRPC server.
	return d.startCSIServer(ctx)
}

// runController initializes the nodeops client for delegation and registers
// CSI Identity + Controller services.
func (d *Driver) runController(ctx context.Context) error {
	if d.nodeOpsAddr == "" {
		return fmt.Errorf("--nodeops-addr is required in controller mode")
	}

	client, err := nodeops.NewClient(d.nodeOpsAddr, nil)
	if err != nil {
		return fmt.Errorf("connect to nodeops: %w", err)
	}
	d.nodeOps = client
	klog.Infof("Controller connected to nodeops at %s", d.nodeOpsAddr)

	return d.startCSIServer(ctx)
}

// runHub initializes the Volume Hub — a storageless orchestrator that
// coordinates nodes for volume lifecycle, cache placement, and S3 sync.
// Hub mode has ZERO storage, ZERO btrfs — it only serves VolumeHub gRPC.
func (d *Driver) runHub(ctx context.Context) error {
	// Build the node registry and populate with known CSI nodes.
	registry := volumehub.NewNodeRegistry()

	// NodeResolver discovers CSI node pods via K8s Endpoints API and maps
	// stable K8s node names → current pod IPs.
	resolver, err := volumehub.NewNodeResolver("tesslate-btrfs-csi-node-svc", "kube-system", 9741)
	if err != nil {
		return fmt.Errorf("create node resolver: %w", err)
	}

	// nodeClientFactory resolves K8s node name → pod IP at connection time.
	nodeClientFactory := func(nodeName string) (*nodeops.Client, error) {
		addr := resolver.Resolve(nodeName)
		if addr == "" {
			// Stale mapping — try a refresh and resolve again.
			if refreshErr := resolver.Refresh(ctx); refreshErr != nil {
				return nil, fmt.Errorf("resolve node %s (refresh failed: %w)", nodeName, refreshErr)
			}
			addr = resolver.Resolve(nodeName)
			if addr == "" {
				return nil, fmt.Errorf("node %s not found in endpoints", nodeName)
			}
		}
		return nodeops.NewClient(addr, nil)
	}

	// Start VolumeHub gRPC server.
	hubSrv := volumehub.NewServer(registry, nodeClientFactory)

	// Initial discovery + periodic refresh (30s) of node endpoints.
	go func() {
		for i := 0; i < 10; i++ {
			if refreshErr := resolver.Refresh(ctx); refreshErr != nil {
				klog.Warningf("Node discovery attempt %d: %v", i+1, refreshErr)
				time.Sleep(3 * time.Second)
				continue
			}
			break
		}
		if discoverErr := hubSrv.DiscoverNodes(resolver); discoverErr != nil {
			klog.Warningf("DiscoverNodes: %v", discoverErr)
		}
		if rebuildErr := hubSrv.RebuildRegistry(ctx); rebuildErr != nil {
			klog.Warningf("Registry rebuild: %v", rebuildErr)
		}
	}()
	resolver.StartPeriodicRefresh(ctx, 30*time.Second)

	go func() {
		addr := fmt.Sprintf(":%d", d.hubGRPCPort)
		if err := hubSrv.Start(addr, nil); err != nil {
			klog.Errorf("VolumeHub gRPC server failed: %v", err)
		}
	}()
	klog.Infof("VolumeHub gRPC server on :%d", d.hubGRPCPort)

	// Start Prometheus metrics server.
	go metrics.StartMetricsServer(":9090", "", "")

	// Block until context is cancelled (signal handler in main.go).
	<-ctx.Done()
	hubSrv.Stop()
	klog.Info("Hub mode stopped")
	return nil
}

// startCSIServer starts the gRPC server with the appropriate CSI services.
func (d *Driver) startCSIServer(ctx context.Context) error {
	socketPath := d.endpoint
	if strings.HasPrefix(socketPath, "unix://") {
		socketPath = strings.TrimPrefix(socketPath, "unix://")
	}
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
	case ModeController:
		csi.RegisterControllerServer(d.srv, NewControllerServer(d))
		klog.Info("Registered CSI Identity + Controller services")
	case ModeNode:
		csi.RegisterNodeServer(d.srv, NewNodeServer(d))
		klog.Info("Registered CSI Identity + Node services")
	case ModeAll:
		csi.RegisterControllerServer(d.srv, NewControllerServer(d))
		csi.RegisterNodeServer(d.srv, NewNodeServer(d))
		klog.Info("Registered CSI Identity + Controller + Node services")
	}

	klog.Infof("CSI driver %q listening on %s (mode=%s)", d.name, socketPath, d.mode)

	errCh := make(chan error, 1)
	go func() {
		errCh <- d.srv.Serve(listener)
	}()

	select {
	case <-ctx.Done():
		klog.Info("Context cancelled, stopping gRPC server")
		d.srv.GracefulStop()
		return nil
	case err := <-errCh:
		return err
	}
}

// Stop performs a graceful shutdown of the driver.
func (d *Driver) Stop() {
	if d.fileOpsSrv != nil {
		d.fileOpsSrv.Stop()
	}
	if d.nodeOpsSrv != nil {
		d.nodeOpsSrv.Stop()
	}
	if d.srv != nil {
		d.srv.GracefulStop()
	}
	klog.Info("Driver stopped")
}

// loggingInterceptor logs all gRPC calls with their method name and duration.
func loggingInterceptor(
	ctx context.Context,
	req interface{},
	info *grpc.UnaryServerInfo,
	handler grpc.UnaryHandler,
) (interface{}, error) {
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

func (l *localNodeOps) TrackVolume(ctx context.Context, volumeID string) error {
	if l.syncer != nil {
		l.syncer.TrackVolume(volumeID)
	}
	return nil
}

func (l *localNodeOps) UntrackVolume(ctx context.Context, volumeID string) error {
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
		return fmt.Errorf("object storage sync not configured, cannot restore volume %q", volumeID)
	}

	objects, err := l.syncer.ListObjects(ctx, fmt.Sprintf("volumes/%s/", volumeID))
	if err != nil {
		return err
	}
	if len(objects) == 0 {
		return fmt.Errorf("no snapshots in S3 for volume %q", volumeID)
	}

	// Use the latest object.
	return l.syncer.RestoreFromStorage(ctx, volumeID, objects[len(objects)-1])
}

func (l *localNodeOps) PromoteToTemplate(ctx context.Context, volumeID, templateName string) error {
	volPath := fmt.Sprintf("volumes/%s", volumeID)
	tmplPath := fmt.Sprintf("templates/%s", templateName)
	// Delete existing template if present (refresh case)
	if l.btrfs.SubvolumeExists(ctx, tmplPath) {
		if err := l.btrfs.DeleteSubvolume(ctx, tmplPath); err != nil {
			return fmt.Errorf("delete existing template: %w", err)
		}
	}
	// Snapshot volume as read-only template
	if err := l.btrfs.SnapshotSubvolume(ctx, volPath, tmplPath, true); err != nil {
		return fmt.Errorf("snapshot to template: %w", err)
	}
	// Upload to S3
	if err := l.tmplMgr.UploadTemplate(ctx, templateName); err != nil {
		return fmt.Errorf("upload template: %w", err)
	}
	// Cleanup build volume
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
		return fmt.Errorf("S3 sync not configured")
	}
	return l.syncer.SyncVolume(ctx, volumeID)
}

func (l *localNodeOps) DeleteFromS3(ctx context.Context, volumeID string) error {
	if l.syncer == nil {
		return nil
	}
	return l.syncer.DeleteS3Prefix(ctx, volumeID)
}

func (l *localNodeOps) GetSyncState(ctx context.Context) ([]nodeops.TrackedVolumeState, error) {
	if l.syncer == nil {
		return nil, nil
	}
	daemonStates := l.syncer.GetTrackedState()
	result := make([]nodeops.TrackedVolumeState, len(daemonStates))
	for i, s := range daemonStates {
		result[i] = nodeops.TrackedVolumeState{
			VolumeID:   s.VolumeID,
			LastSyncAt: s.LastSyncAt,
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
