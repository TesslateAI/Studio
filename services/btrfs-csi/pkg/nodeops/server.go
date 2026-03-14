package nodeops

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/status"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
)

// Server exposes btrfs operations over gRPC for controller delegation.
// It runs on each node alongside the CSI node plugin.
type Server struct {
	btrfs   *btrfs.Manager
	syncer  *bsync.Daemon
	tmplMgr *template.Manager
	srv     *grpc.Server
}

// NewServer creates a nodeops Server.
func NewServer(btrfs *btrfs.Manager, syncer *bsync.Daemon, tmplMgr *template.Manager) *Server {
	return &Server{
		btrfs:   btrfs,
		syncer:  syncer,
		tmplMgr: tmplMgr,
	}
}

// TLSConfig holds paths for mTLS certificate files.
type TLSConfig struct {
	CertFile string // Server certificate
	KeyFile  string // Server private key
	CAFile   string // CA certificate for client verification
}

// Start begins serving nodeops gRPC on the given address (e.g., ":9741").
// If tlsCfg is non-nil and files exist, mTLS is used; otherwise plaintext
// (suitable for NetworkPolicy-protected cluster-internal traffic).
func (s *Server) Start(addr string, tlsCfg *TLSConfig) error {
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("nodeops listen on %s: %w", addr, err)
	}

	var opts []grpc.ServerOption
	if creds, tlsErr := loadServerTLS(tlsCfg); tlsErr != nil {
		return fmt.Errorf("nodeops TLS: %w", tlsErr)
	} else if creds != nil {
		opts = append(opts, grpc.Creds(creds))
		klog.Info("NodeOps gRPC server using mTLS")
	} else {
		klog.Info("NodeOps gRPC server using plaintext (cluster-internal, NetworkPolicy protected)")
	}

	s.srv = grpc.NewServer(opts...)
	registerNodeOpsServer(s.srv, s)

	klog.Infof("NodeOps gRPC server listening on %s", addr)
	return s.srv.Serve(listener)
}

// loadServerTLS returns TLS credentials if config is provided and cert files
// exist. Returns (nil, nil) if TLS is not configured.
func loadServerTLS(cfg *TLSConfig) (credentials.TransportCredentials, error) {
	if cfg == nil || cfg.CertFile == "" {
		return nil, nil
	}
	if _, err := os.Stat(cfg.CertFile); os.IsNotExist(err) {
		return nil, nil
	}

	cert, err := tls.LoadX509KeyPair(cfg.CertFile, cfg.KeyFile)
	if err != nil {
		return nil, fmt.Errorf("load key pair: %w", err)
	}

	tlsConfig := &tls.Config{
		Certificates: []tls.Certificate{cert},
		MinVersion:   tls.VersionTLS13,
	}

	if cfg.CAFile != "" {
		caPEM, err := os.ReadFile(cfg.CAFile)
		if err != nil {
			return nil, fmt.Errorf("read CA file: %w", err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(caPEM) {
			return nil, fmt.Errorf("failed to parse CA certificate")
		}
		tlsConfig.ClientCAs = pool
		tlsConfig.ClientAuth = tls.RequireAndVerifyClientCert
	}

	return credentials.NewTLS(tlsConfig), nil
}

// Stop gracefully stops the nodeops server.
func (s *Server) Stop() {
	if s.srv != nil {
		s.srv.GracefulStop()
	}
}

// --- gRPC service implementation using manual service descriptors ---
// This avoids protobuf compilation while still using proper gRPC transport.
// Request/response bodies are JSON-encoded in a wrapper message.

// Request and response types for the nodeops service.
type (
	SubvolumeRequest struct {
		Name     string `json:"name"`
		Source   string `json:"source,omitempty"`
		Dest     string `json:"dest,omitempty"`
		ReadOnly bool   `json:"read_only,omitempty"`
		Prefix   string `json:"prefix,omitempty"`
	}

	SubvolumeExistsResponse struct {
		Exists bool `json:"exists"`
	}

	CapacityResponse struct {
		Total     int64 `json:"total"`
		Available int64 `json:"available"`
	}

	ListSubvolumesResponse struct {
		Subvolumes []SubvolumeInfo `json:"subvolumes"`
	}

	VolumeTrackRequest struct {
		VolumeID string `json:"volume_id"`
	}

	TemplateRequest struct {
		Name string `json:"name"`
	}

	Empty struct{}
)

// jsonCodec implements gRPC's encoding.Codec for JSON serialization.
type jsonCodec struct{}

func (jsonCodec) Marshal(v interface{}) ([]byte, error)     { return json.Marshal(v) }
func (jsonCodec) Unmarshal(data []byte, v interface{}) error { return json.Unmarshal(data, v) }
func (jsonCodec) Name() string                              { return "json" }

// registerNodeOpsServer registers all RPC handlers on the gRPC server.
func registerNodeOpsServer(srv *grpc.Server, s *Server) {
	srv.RegisterService(&grpc.ServiceDesc{
		ServiceName: "nodeops.NodeOps",
		HandlerType: (*Server)(nil),
		Methods: []grpc.MethodDesc{
			{MethodName: "CreateSubvolume", Handler: s.handleCreateSubvolume},
			{MethodName: "DeleteSubvolume", Handler: s.handleDeleteSubvolume},
			{MethodName: "SnapshotSubvolume", Handler: s.handleSnapshotSubvolume},
			{MethodName: "SubvolumeExists", Handler: s.handleSubvolumeExists},
			{MethodName: "GetCapacity", Handler: s.handleGetCapacity},
			{MethodName: "ListSubvolumes", Handler: s.handleListSubvolumes},
			{MethodName: "TrackVolume", Handler: s.handleTrackVolume},
			{MethodName: "UntrackVolume", Handler: s.handleUntrackVolume},
			{MethodName: "EnsureTemplate", Handler: s.handleEnsureTemplate},
			{MethodName: "RestoreVolume", Handler: s.handleRestoreVolume},
		},
		Streams: []grpc.StreamDesc{},
	}, s)
}

func (s *Server) handleCreateSubvolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SubvolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if err := s.btrfs.CreateSubvolume(ctx, req.Name); err != nil {
		return nil, status.Errorf(codes.Internal, "create subvolume: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleDeleteSubvolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SubvolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if err := s.btrfs.DeleteSubvolume(ctx, req.Name); err != nil {
		return nil, status.Errorf(codes.Internal, "delete subvolume: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleSnapshotSubvolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SubvolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if err := s.btrfs.SnapshotSubvolume(ctx, req.Source, req.Dest, req.ReadOnly); err != nil {
		return nil, status.Errorf(codes.Internal, "snapshot subvolume: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleSubvolumeExists(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SubvolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	exists := s.btrfs.SubvolumeExists(ctx, req.Name)
	return &SubvolumeExistsResponse{Exists: exists}, nil
}

func (s *Server) handleGetCapacity(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req Empty
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	total, available, err := s.btrfs.GetCapacity(ctx)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "get capacity: %v", err)
	}
	return &CapacityResponse{Total: total, Available: available}, nil
}

func (s *Server) handleListSubvolumes(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SubvolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	subs, err := s.btrfs.ListSubvolumes(ctx, req.Prefix)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "list subvolumes: %v", err)
	}
	var infos []SubvolumeInfo
	for _, sub := range subs {
		infos = append(infos, SubvolumeInfo{
			ID: sub.ID, Name: sub.Name, Path: sub.Path, ReadOnly: sub.ReadOnly,
		})
	}
	return &ListSubvolumesResponse{Subvolumes: infos}, nil
}

func (s *Server) handleTrackVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req VolumeTrackRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if s.syncer != nil {
		s.syncer.TrackVolume(req.VolumeID)
	}
	return &Empty{}, nil
}

func (s *Server) handleUntrackVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req VolumeTrackRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if s.syncer != nil {
		s.syncer.UntrackVolume(req.VolumeID)
	}
	return &Empty{}, nil
}

func (s *Server) handleEnsureTemplate(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req TemplateRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if err := s.tmplMgr.EnsureTemplate(ctx, req.Name); err != nil {
		return nil, status.Errorf(codes.Internal, "ensure template: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleRestoreVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req VolumeTrackRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if err := s.restoreVolumeFromS3(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "restore volume: %v", err)
	}
	return &Empty{}, nil
}

// restoreVolumeFromS3 downloads the latest snapshot chain from S3 and
// reconstructs the volume via btrfs receive.
func (s *Server) restoreVolumeFromS3(ctx context.Context, volumeID string) error {
	if s.syncer == nil {
		return fmt.Errorf("S3 sync not configured, cannot restore volume %q", volumeID)
	}

	// The sync daemon uploads to s3://bucket/volumes/{volumeID}/full-*.zst or incremental-*.zst.
	// For restore, we download the latest full send stream and apply it.
	s3Prefix := fmt.Sprintf("volumes/%s/", volumeID)

	// List all snapshots for this volume to find the latest full send.
	objects, err := s.syncer.ListS3Objects(ctx, s3Prefix)
	if err != nil {
		return fmt.Errorf("list S3 objects for volume %q: %w", volumeID, err)
	}

	if len(objects) == 0 {
		return fmt.Errorf("no snapshots found in S3 for volume %q", volumeID)
	}

	// Find the latest full send (we need a full send for initial restore).
	var latestFullKey string
	for i := len(objects) - 1; i >= 0; i-- {
		if strings.Contains(objects[i], "full-") {
			latestFullKey = objects[i]
			break
		}
	}

	if latestFullKey == "" {
		// No full send — use the latest object (could be incremental, but it's
		// better than nothing; the sync daemon should always create an initial full).
		latestFullKey = objects[len(objects)-1]
		klog.Warningf("No full send found for volume %q, using latest: %s", volumeID, latestFullKey)
	}

	klog.Infof("Restoring volume %q from S3: %s", volumeID, latestFullKey)

	if err := s.syncer.RestoreFromS3(ctx, volumeID, latestFullKey); err != nil {
		return fmt.Errorf("restore from S3: %w", err)
	}

	klog.Infof("Volume %q restored successfully from S3", volumeID)
	return nil
}
