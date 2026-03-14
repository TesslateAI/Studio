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
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/nodeops"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/s3"
	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
)

// Mode determines which CSI services the driver registers.
type Mode string

const (
	ModeController Mode = "controller"
	ModeNode       Mode = "node"
	ModeAll        Mode = "all" // For single-node testing (e.g., minikube)
)

// Driver is the top-level CSI driver struct that ties together all subsystems.
type Driver struct {
	name     string
	version  string
	nodeID   string
	poolPath string
	endpoint string
	mode     Mode

	s3Endpoint  string
	s3Bucket    string
	s3AccessKey string
	s3SecretKey string
	s3Region    string

	syncInterval time.Duration
	nodeOpsAddr  string // Address of nodeops gRPC server (for controller mode)
	nodeOpsPort  int    // Port for nodeops gRPC server (for node mode)

	// Node-mode subsystems (nil in controller mode).
	btrfs   *btrfs.Manager
	s3c     *s3.Client
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

func WithS3Config(endpoint, bucket, accessKey, secretKey, region string) Option {
	return func(d *Driver) {
		d.s3Endpoint = endpoint
		d.s3Bucket = bucket
		d.s3AccessKey = accessKey
		d.s3SecretKey = secretKey
		d.s3Region = region
	}
}

func WithSyncInterval(interval time.Duration) Option {
	return func(d *Driver) { d.syncInterval = interval }
}

// NewDriver creates a new Driver with the given options applied.
func NewDriver(opts ...Option) *Driver {
	d := &Driver{
		name:         "btrfs.csi.tesslate.io",
		version:      "0.1.0",
		syncInterval: 60 * time.Second,
		mode:         ModeAll,
		nodeOpsPort:  9741,
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

	// Initialize S3 client if configured.
	if d.s3Endpoint != "" && d.s3Bucket != "" {
		useSSL := !strings.Contains(d.s3Endpoint, "localhost") && !strings.Contains(d.s3Endpoint, "127.0.0.1")
		client, err := s3.NewClient(d.s3Endpoint, d.s3AccessKey, d.s3SecretKey, d.s3Bucket, d.s3Region, useSSL)
		if err != nil {
			klog.Errorf("Failed to create S3 client: %v", err)
		} else {
			d.s3c = client
		}
	}

	// Start sync daemon if S3 is configured.
	if d.s3c != nil {
		d.syncer = bsync.NewDaemon(d.btrfs, d.s3c, d.syncInterval)
		go d.syncer.Start(ctx)
		klog.Info("Sync daemon started")
	}

	d.tmplMgr = template.NewManager(d.btrfs, d.s3c, d.poolPath)

	// Start nodeops gRPC server for controller delegation.
	d.nodeOpsSrv = nodeops.NewServer(d.btrfs, d.syncer, d.tmplMgr)
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
