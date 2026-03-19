package nodeops

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"

	"github.com/klauspost/compress/zstd"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/encoding"
	"google.golang.org/grpc/status"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
)

func init() {
	encoding.RegisterCodec(jsonCodec{})
}

// Server exposes btrfs operations over gRPC for controller delegation.
// It runs on each node alongside the CSI node plugin.
type Server struct {
	btrfs   *btrfs.Manager
	syncer  *bsync.Daemon
	tmplMgr *template.Manager
	cas     *cas.Store
	srv     *grpc.Server
}

// NewServer creates a nodeops Server.
func NewServer(btrfs *btrfs.Manager, syncer *bsync.Daemon, tmplMgr *template.Manager, casStore *cas.Store) *Server {
	return &Server{
		btrfs:   btrfs,
		syncer:  syncer,
		tmplMgr: tmplMgr,
		cas:     casStore,
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

	// ForceServerCodec makes all RPCs use JSON regardless of content-type.
	// 64MB message limits for large peer transfer chunks.
	opts = append(opts,
		grpc.ForceServerCodec(jsonCodec{}),
		grpc.MaxRecvMsgSize(64*1024*1024),
		grpc.MaxSendMsgSize(64*1024*1024),
	)
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
		Uid      int    `json:"uid,omitempty"`
		Gid      int    `json:"gid,omitempty"`
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
		VolumeID     string `json:"volume_id"`
		TemplateName string `json:"template_name,omitempty"`
		TemplateHash string `json:"template_hash,omitempty"`
	}

	TemplateRequest struct {
		Name string `json:"name"`
	}

	PromoteTemplateRequest struct {
		VolumeID     string `json:"volume_id"`
		TemplateName string `json:"template_name"`
	}

	SetOwnershipRequest struct {
		Name string `json:"name"`
		Uid  int    `json:"uid"`
		Gid  int    `json:"gid"`
	}

	DeleteVolumeCASRequest struct {
		VolumeID string `json:"volume_id"`
	}

	GetSyncStateResponse struct {
		Volumes []TrackedVolumeState `json:"volumes"`
	}

	SendVolumeToRequest struct {
		VolumeID   string `json:"volume_id"`
		TargetAddr string `json:"target_addr"`
	}

	SendTemplateToRequest struct {
		TemplateName string `json:"template_name"`
		TargetAddr   string `json:"target_addr"`
	}

	// ReceiveStreamChunk is sent by the client in a client-streaming RPC.
	ReceiveStreamChunk struct {
		VolumeID       string `json:"volume_id,omitempty"`        // set on first chunk
		TemplateParent string `json:"template_parent,omitempty"`  // template name if incremental from template
		Data           []byte `json:"data"`
		Final          bool   `json:"final,omitempty"` // set on last chunk
	}

	HasBlobsRequest struct {
		Hashes []string `json:"hashes"`
	}

	HasBlobsResponse struct {
		Exists []bool `json:"exists"`
	}

	CreateUserSnapshotRequest struct {
		VolumeID string `json:"volume_id"`
		Label    string `json:"label"`
	}

	CreateUserSnapshotResponse struct {
		Hash string `json:"hash"`
	}

	RestoreFromSnapshotRequest struct {
		VolumeID   string `json:"volume_id"`
		TargetHash string `json:"target_hash"`
	}

	GetVolumeMetadataRequest struct {
		VolumeID string `json:"volume_id"`
	}

	QgroupLimitRequest struct {
		Name  string `json:"name"`
		Bytes int64  `json:"bytes"`
	}

	QgroupUsageResponse struct {
		Exclusive int64 `json:"exclusive"`
		Limit     int64 `json:"limit"`
	}

	Empty struct{}
)

// jsonCodec implements gRPC's encoding.Codec for JSON serialization.
type jsonCodec struct{}

func (jsonCodec) Marshal(v interface{}) ([]byte, error)     { return json.Marshal(v) }
func (jsonCodec) Unmarshal(data []byte, v interface{}) error { return json.Unmarshal(data, v) }
func (jsonCodec) Name() string                              { return "json" }

// registerNodeOpsServer registers all RPC handlers on the gRPC server.
// nodeOpsServiceServer is the interface type required by gRPC's RegisterService.
type nodeOpsServiceServer interface{}

func registerNodeOpsServer(srv *grpc.Server, s *Server) {
	srv.RegisterService(&grpc.ServiceDesc{
		ServiceName: "nodeops.NodeOps",
		HandlerType: (*nodeOpsServiceServer)(nil),
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
			{MethodName: "SyncVolume", Handler: s.handleSyncVolume},
			{MethodName: "PromoteToTemplate", Handler: s.handlePromoteToTemplate},
			{MethodName: "SetOwnership", Handler: s.handleSetOwnership},
			{MethodName: "DeleteVolumeCAS", Handler: s.handleDeleteVolumeCAS},
			{MethodName: "GetSyncState", Handler: s.handleGetSyncState},
			{MethodName: "SendVolumeTo", Handler: s.handleSendVolumeTo},
			{MethodName: "SendTemplateTo", Handler: s.handleSendTemplateTo},
			{MethodName: "HasBlobs", Handler: s.handleHasBlobs},
			{MethodName: "CreateUserSnapshot", Handler: s.handleCreateUserSnapshot},
			{MethodName: "RestoreFromSnapshot", Handler: s.handleRestoreFromSnapshot},
			{MethodName: "GetVolumeMetadata", Handler: s.handleGetVolumeMetadata},
			{MethodName: "SetQgroupLimit", Handler: s.handleSetQgroupLimit},
			{MethodName: "GetQgroupUsage", Handler: s.handleGetQgroupUsage},
		},
		Streams: []grpc.StreamDesc{
			{
				StreamName:    "ReceiveVolumeStream",
				Handler:       s.handleReceiveVolumeStream,
				ClientStreams:  true,
				ServerStreams:  false,
			},
		},
	}, s)
}

// ---------------------------------------------------------------------------
// Existing handler implementations
// ---------------------------------------------------------------------------

func (s *Server) handleCreateSubvolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SubvolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if err := s.btrfs.CreateSubvolume(ctx, req.Name); err != nil {
		return nil, status.Errorf(codes.Internal, "create subvolume: %v", err)
	}
	if req.Uid > 0 || req.Gid > 0 {
		target, err := s.btrfs.SafePath(req.Name)
		if err != nil {
			return nil, status.Errorf(codes.Internal, "resolve subvolume path: %v", err)
		}
		if err := os.Chown(target, req.Uid, req.Gid); err != nil {
			return nil, status.Errorf(codes.Internal, "chown new subvolume: %v", err)
		}
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

func (s *Server) handleTrackVolume(_ interface{}, _ context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req VolumeTrackRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if s.syncer != nil {
		s.syncer.TrackVolume(req.VolumeID, req.TemplateName, req.TemplateHash)
	}
	return &Empty{}, nil
}

func (s *Server) handleUntrackVolume(_ interface{}, _ context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
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

func (s *Server) handleSyncVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req VolumeTrackRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if s.syncer == nil {
		return nil, status.Errorf(codes.FailedPrecondition, "CAS sync not configured")
	}
	if err := s.syncer.SyncVolume(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "sync volume: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleRestoreVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req VolumeTrackRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if s.syncer == nil {
		return nil, status.Errorf(codes.FailedPrecondition, "CAS sync not configured")
	}
	if err := s.syncer.RestoreVolume(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "restore volume: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handlePromoteToTemplate(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req PromoteTemplateRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if !s.btrfs.SubvolumeExists(ctx, "volumes/"+req.VolumeID) {
		return nil, status.Errorf(codes.NotFound, "volume %q does not exist", req.VolumeID)
	}
	// Delete existing template if present (refresh case).
	tmplPath := "templates/" + req.TemplateName
	if s.btrfs.SubvolumeExists(ctx, tmplPath) {
		if err := s.btrfs.DeleteSubvolume(ctx, tmplPath); err != nil {
			return nil, status.Errorf(codes.Internal, "delete existing template: %v", err)
		}
	}
	// Snapshot volume as read-only template.
	if err := s.btrfs.SnapshotSubvolume(ctx, "volumes/"+req.VolumeID, tmplPath, true); err != nil {
		return nil, status.Errorf(codes.Internal, "snapshot to template: %v", err)
	}
	// Upload to CAS and record hash.
	if _, err := s.tmplMgr.UploadTemplate(ctx, req.TemplateName); err != nil {
		return nil, status.Errorf(codes.Internal, "upload template: %v", err)
	}
	// Cleanup build volume.
	if err := s.btrfs.DeleteSubvolume(ctx, "volumes/"+req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "cleanup build volume: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleSetOwnership(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SetOwnershipRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.Name == "" {
		return nil, status.Error(codes.InvalidArgument, "name is required")
	}
	if req.Uid == 0 && req.Gid == 0 {
		return &Empty{}, nil
	}
	if err := s.btrfs.SetOwnership(ctx, req.Name, req.Uid, req.Gid); err != nil {
		return nil, status.Errorf(codes.Internal, "set ownership: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleDeleteVolumeCAS(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req DeleteVolumeCASRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}
	if s.syncer == nil {
		klog.V(2).Infof("DeleteVolumeCAS: no syncer configured, skipping for %s", req.VolumeID)
		return &Empty{}, nil
	}
	if err := s.syncer.DeleteVolume(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "delete volume CAS data: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleGetSyncState(_ interface{}, _ context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req Empty
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if s.syncer == nil {
		return &GetSyncStateResponse{}, nil
	}
	states := s.syncer.GetTrackedState()
	result := make([]TrackedVolumeState, len(states))
	for i, st := range states {
		result[i] = TrackedVolumeState{
			VolumeID:     st.VolumeID,
			TemplateHash: st.TemplateHash,
			LastSyncAt:   st.LastSyncAt,
		}
	}
	return &GetSyncStateResponse{Volumes: result}, nil
}

// ---------------------------------------------------------------------------
// New CAS-aware handlers
// ---------------------------------------------------------------------------

func (s *Server) handleHasBlobs(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req HasBlobsRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	results := make([]bool, len(req.Hashes))
	for i, hash := range req.Hashes {
		// Check if this hash exists as a local subvolume (template or layer).
		shortHash := cas.ShortHash(hash)
		// Check templates — iterate local templates to see if any match.
		// Also check if CAS store has it.
		if s.cas != nil {
			exists, err := s.cas.HasBlob(ctx, hash)
			if err == nil && exists {
				results[i] = true
				continue
			}
		}
		// Check local layers.
		layers, err := s.btrfs.ListSubvolumes(ctx, "layers/")
		if err == nil {
			for _, sub := range layers {
				if len(sub.Name) >= len(shortHash) && sub.Name[len(sub.Name)-len(shortHash):] == shortHash {
					results[i] = true
					break
				}
			}
		}
	}
	return &HasBlobsResponse{Exists: results}, nil
}

func (s *Server) handleCreateUserSnapshot(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req CreateUserSnapshotRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}
	if s.syncer == nil {
		return nil, status.Errorf(codes.FailedPrecondition, "CAS sync not configured")
	}
	hash, err := s.syncer.CreateSnapshot(ctx, req.VolumeID, req.Label)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "create snapshot: %v", err)
	}
	return &CreateUserSnapshotResponse{Hash: hash}, nil
}

func (s *Server) handleRestoreFromSnapshot(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req RestoreFromSnapshotRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.TargetHash == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and target_hash required")
	}
	if s.syncer == nil {
		return nil, status.Errorf(codes.FailedPrecondition, "CAS sync not configured")
	}
	if err := s.syncer.RestoreToSnapshot(ctx, req.VolumeID, req.TargetHash); err != nil {
		return nil, status.Errorf(codes.Internal, "restore to snapshot: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleGetVolumeMetadata(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req GetVolumeMetadataRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}
	if s.syncer == nil {
		return nil, status.Errorf(codes.FailedPrecondition, "CAS sync not configured")
	}
	manifest, err := s.syncer.GetManifest(ctx, req.VolumeID)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "get manifest: %v", err)
	}

	meta := &VolumeMetadata{
		VolumeID:     manifest.VolumeID,
		TemplateName: manifest.TemplateName,
		TemplateHash: manifest.Base,
		LatestHash:   manifest.LatestHash(),
		LayerCount:   len(manifest.Layers),
	}
	for _, l := range manifest.Layers {
		if l.Type == "snapshot" {
			meta.Snapshots = append(meta.Snapshots, l)
		}
	}
	return meta, nil
}

// ---------------------------------------------------------------------------
// Quota group handlers
// ---------------------------------------------------------------------------

func (s *Server) handleSetQgroupLimit(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req QgroupLimitRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.Name == "" {
		return nil, status.Error(codes.InvalidArgument, "name is required")
	}
	if err := s.btrfs.SetQgroupLimit(ctx, req.Name, req.Bytes); err != nil {
		return nil, status.Errorf(codes.Internal, "set qgroup limit: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleGetQgroupUsage(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SubvolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.Name == "" {
		return nil, status.Error(codes.InvalidArgument, "name is required")
	}
	excl, limit, err := s.btrfs.GetQgroupUsage(ctx, req.Name)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "get qgroup usage: %v", err)
	}
	return &QgroupUsageResponse{Exclusive: excl, Limit: limit}, nil
}

// ---------------------------------------------------------------------------
// Peer transfer handlers
// ---------------------------------------------------------------------------

func (s *Server) handleSendVolumeTo(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SendVolumeToRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.TargetAddr == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and target_addr required")
	}

	snapPath := fmt.Sprintf("snapshots/%s@transfer", req.VolumeID)
	volumePath := fmt.Sprintf("volumes/%s", req.VolumeID)

	if !s.btrfs.SubvolumeExists(ctx, volumePath) {
		return nil, status.Errorf(codes.NotFound, "volume %q not found", req.VolumeID)
	}

	// Clean up any stale transfer snapshot.
	if s.btrfs.SubvolumeExists(ctx, snapPath) {
		_ = s.btrfs.DeleteSubvolume(ctx, snapPath)
	}

	// Create read-only snapshot for transfer.
	if err := s.btrfs.SnapshotSubvolume(ctx, volumePath, snapPath, true); err != nil {
		return nil, status.Errorf(codes.Internal, "snapshot for transfer: %v", err)
	}
	defer func() {
		bg := context.Background()
		_ = s.btrfs.DeleteSubvolume(bg, snapPath)
	}()

	if err := s.sendSubvolumeTo(ctx, snapPath, req.VolumeID, req.TargetAddr, ""); err != nil {
		return nil, status.Errorf(codes.Internal, "send volume to %s: %v", req.TargetAddr, err)
	}

	klog.Infof("SendVolumeTo: sent volume %s to %s", req.VolumeID, req.TargetAddr)
	return &Empty{}, nil
}

func (s *Server) handleSendTemplateTo(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SendTemplateToRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.TemplateName == "" || req.TargetAddr == "" {
		return nil, status.Error(codes.InvalidArgument, "template_name and target_addr required")
	}

	tmplPath := "templates/" + req.TemplateName
	if !s.btrfs.SubvolumeExists(ctx, tmplPath) {
		return nil, status.Errorf(codes.NotFound, "template %q not found", req.TemplateName)
	}

	// Templates are already read-only — send directly.
	if err := s.sendSubvolumeTo(ctx, tmplPath, req.TemplateName, req.TargetAddr, ""); err != nil {
		return nil, status.Errorf(codes.Internal, "send template to %s: %v", req.TargetAddr, err)
	}

	klog.Infof("SendTemplateTo: sent template %s to %s", req.TemplateName, req.TargetAddr)
	return &Empty{}, nil
}

// sendSubvolumeTo streams a btrfs send | zstd to the target node's ReceiveVolumeStream RPC.
// If templateParent is non-empty, it's included in the header so the receiver can
// ensure the template exists before btrfs receive.
func (s *Server) sendSubvolumeTo(ctx context.Context, subvolPath, identifier, targetAddr, templateParent string) error {
	// CAS-aware incremental: try to use template as parent for smaller transfer.
	parentPath := ""
	if templateParent != "" {
		tmplPath := fmt.Sprintf("templates/%s", templateParent)
		if s.btrfs.SubvolumeExists(ctx, tmplPath) {
			parentPath = tmplPath
		}
	}

	sendReader, err := s.btrfs.Send(ctx, subvolPath, parentPath)
	if err != nil {
		return fmt.Errorf("btrfs send %q: %w", subvolPath, err)
	}
	defer sendReader.Close()

	target, err := NewClient(targetAddr, nil)
	if err != nil {
		return fmt.Errorf("connect to target %s: %w", targetAddr, err)
	}
	defer target.Close()

	stream, err := target.conn.NewStream(ctx, &grpc.StreamDesc{
		StreamName:   "ReceiveVolumeStream",
		ClientStreams: true,
	}, "/nodeops.NodeOps/ReceiveVolumeStream", grpc.ForceCodecCallOption{Codec: jsonCodec{}})
	if err != nil {
		return fmt.Errorf("open receive stream on %s: %w", targetAddr, err)
	}

	// Send metadata header with template parent info.
	header := &ReceiveStreamChunk{VolumeID: identifier, TemplateParent: templateParent}
	if err := stream.SendMsg(header); err != nil {
		return fmt.Errorf("stream header: %w", err)
	}

	// Streaming pipeline: btrfs send → zstd compress → pipe → chunk → gRPC
	const chunkSize = 2 * 1024 * 1024 // 2 MiB
	pr, pw := io.Pipe()

	go func() {
		encoder, encErr := zstd.NewWriter(pw)
		if encErr != nil {
			pw.CloseWithError(encErr)
			return
		}
		_, copyErr := io.Copy(encoder, sendReader)
		closeErr := encoder.Close()
		if copyErr != nil {
			pw.CloseWithError(copyErr)
			return
		}
		if closeErr != nil {
			pw.CloseWithError(closeErr)
			return
		}
		pw.Close()
	}()

	buf := make([]byte, chunkSize)
	for {
		n, readErr := io.ReadFull(pr, buf)
		if n > 0 {
			if sendErr := stream.SendMsg(&ReceiveStreamChunk{Data: buf[:n]}); sendErr != nil {
				pr.CloseWithError(sendErr)
				return fmt.Errorf("stream send: %w", sendErr)
			}
		}
		if readErr != nil {
			if readErr == io.EOF || readErr == io.ErrUnexpectedEOF {
				break
			}
			return fmt.Errorf("read compressed stream: %w", readErr)
		}
	}

	if err := stream.SendMsg(&ReceiveStreamChunk{Final: true}); err != nil {
		return fmt.Errorf("stream final: %w", err)
	}
	var resp Empty
	if err := stream.RecvMsg(&resp); err != nil {
		return fmt.Errorf("receive response: %w", err)
	}
	return nil
}

// handleReceiveVolumeStream is a client-streaming RPC handler.
// Receives a streaming zstd-compressed btrfs send stream from a peer node.
// Template parent awareness: if the header includes TemplateParent, the
// receiver ensures the template exists before btrfs receive.
func (s *Server) handleReceiveVolumeStream(srv interface{}, stream grpc.ServerStream) error {
	ctx := stream.Context()

	// Phase 1: receive header with volume ID and optional template parent.
	var header ReceiveStreamChunk
	if err := stream.RecvMsg(&header); err != nil {
		return status.Errorf(codes.InvalidArgument, "receive header: %v", err)
	}
	volumeID := header.VolumeID
	if volumeID == "" {
		return status.Error(codes.InvalidArgument, "first message must contain volume_id")
	}

	// Ensure template parent exists if specified.
	if header.TemplateParent != "" {
		if err := s.tmplMgr.EnsureTemplate(ctx, header.TemplateParent); err != nil {
			klog.Warningf("ReceiveVolumeStream: ensure template parent %s: %v", header.TemplateParent, err)
		}
	}

	// Phase 2: pipe gRPC chunks → streaming zstd decompress → btrfs receive.
	compressedPR, compressedPW := io.Pipe()

	recvErrCh := make(chan error, 1)
	go func() {
		defer compressedPW.Close()
		for {
			var chunk ReceiveStreamChunk
			if err := stream.RecvMsg(&chunk); err != nil {
				if err == io.EOF {
					recvErrCh <- nil
					return
				}
				compressedPW.CloseWithError(err)
				recvErrCh <- err
				return
			}
			if chunk.Final {
				recvErrCh <- nil
				return
			}
			if len(chunk.Data) > 0 {
				if _, writeErr := compressedPW.Write(chunk.Data); writeErr != nil {
					recvErrCh <- writeErr
					return
				}
			}
		}
	}()

	decoder, decErr := zstd.NewReader(compressedPR)
	if decErr != nil {
		compressedPR.Close()
		<-recvErrCh
		return status.Errorf(codes.Internal, "create zstd decoder: %v", decErr)
	}
	defer decoder.Close()

	if err := s.btrfs.Receive(ctx, "volumes", decoder); err != nil {
		compressedPR.Close()
		<-recvErrCh
		return status.Errorf(codes.Internal, "btrfs receive: %v", err)
	}
	compressedPR.Close()

	if recvErr := <-recvErrCh; recvErr != nil {
		return status.Errorf(codes.Internal, "stream receive: %v", recvErr)
	}

	// Rename received snapshot to canonical path.
	receivedPath := fmt.Sprintf("volumes/%s@transfer", volumeID)
	canonicalPath := fmt.Sprintf("volumes/%s", volumeID)

	if s.btrfs.SubvolumeExists(ctx, receivedPath) {
		if s.btrfs.SubvolumeExists(ctx, canonicalPath) {
			_ = s.btrfs.DeleteSubvolume(ctx, canonicalPath)
		}
		if err := s.btrfs.SnapshotSubvolume(ctx, receivedPath, canonicalPath, false); err != nil {
			return status.Errorf(codes.Internal, "snapshot received volume: %v", err)
		}
		_ = s.btrfs.DeleteSubvolume(ctx, receivedPath)
	}

	klog.Infof("ReceiveVolumeStream: received volume %s", volumeID)
	return stream.SendMsg(&Empty{})
}
