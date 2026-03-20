package volumehub

import (
	"context"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/encoding"
	"google.golang.org/grpc/status"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/nodeops"
)

func init() {
	encoding.RegisterCodec(jsonCodec{})
}

// NodeClientFactory creates a nodeops client for a given node name.
// The Hub uses this to delegate operations to compute nodes.
type NodeClientFactory func(nodeName string) (*nodeops.Client, error)

// NodeAddrResolver resolves a K8s node name to a gRPC address (podIP:port).
// Returns empty string if the node is unknown.
type NodeAddrResolver func(nodeName string) string

// Server implements the VolumeHub gRPC service as a storageless orchestrator.
// It holds zero storage, zero btrfs — nodes handle all data. The Hub only
// coordinates: volume→owner_node mapping, template→cached_nodes, node→capacity.
type Server struct {
	registry    *NodeRegistry
	cas         *cas.Store // for manifest reads (ListSnapshots, EnsureCached)
	nodeClient  NodeClientFactory
	resolveAddr NodeAddrResolver
	srv         *grpc.Server
}

// NewServer creates a VolumeHub Server.
func NewServer(registry *NodeRegistry, casStore *cas.Store, nodeClient NodeClientFactory, resolveAddr NodeAddrResolver) *Server {
	return &Server{
		registry:    registry,
		cas:         casStore,
		nodeClient:  nodeClient,
		resolveAddr: resolveAddr,
	}
}

// TLSConfig holds paths for mTLS certificate files.
type TLSConfig struct {
	CertFile string // Server certificate
	KeyFile  string // Server private key
	CAFile   string // CA certificate for client verification
}

// Start begins serving VolumeHub gRPC on the given address (e.g., ":9750").
// If tlsCfg is non-nil and files exist, mTLS is used; otherwise plaintext
// (suitable for NetworkPolicy-protected cluster-internal traffic).
func (s *Server) Start(addr string, tlsCfg *TLSConfig) error {
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("volumehub listen on %s: %w", addr, err)
	}

	var opts []grpc.ServerOption
	if creds, tlsErr := loadServerTLS(tlsCfg); tlsErr != nil {
		return fmt.Errorf("volumehub TLS: %w", tlsErr)
	} else if creds != nil {
		opts = append(opts, grpc.Creds(creds))
		klog.Info("VolumeHub gRPC server using mTLS")
	} else {
		klog.Info("VolumeHub gRPC server using plaintext (cluster-internal, NetworkPolicy protected)")
	}

	// ForceServerCodec makes all RPCs use JSON regardless of content-type.
	opts = append(opts, grpc.ForceServerCodec(jsonCodec{}))
	s.srv = grpc.NewServer(opts...)
	registerVolumeHubServer(s.srv, s)

	klog.Infof("VolumeHub gRPC server listening on %s", addr)
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

// Stop gracefully stops the VolumeHub server.
func (s *Server) Stop() {
	if s.srv != nil {
		s.srv.GracefulStop()
	}
}

// --- gRPC service implementation using manual service descriptors ---

// Request and response types for the volumehub service.
type (
	CreateVolumeRequest struct {
		Template string `json:"template,omitempty"`
		HintNode string `json:"hint_node,omitempty"`
	}
	CreateVolumeResponse struct {
		VolumeID string `json:"volume_id"`
		NodeName string `json:"node_name"`
	}

	DeleteVolumeRequest struct {
		VolumeID string `json:"volume_id"`
	}

	EnsureCachedRequest struct {
		VolumeID string `json:"volume_id"`
		HintNode string `json:"hint_node,omitempty"`
	}
	EnsureCachedResponse struct {
		NodeName string `json:"node_name"`
	}

	TriggerSyncRequest struct {
		VolumeID string `json:"volume_id"`
	}

	VolumeStatusRequest struct {
		VolumeID string `json:"volume_id"`
	}
	VolumeStatusResponse = VolumeStatus

	CreateServiceVolumeRequest struct {
		BaseVolumeID string `json:"base_volume_id"`
		ServiceName  string `json:"service_name"`
	}
	CreateServiceVolumeResponse struct {
		VolumeID string `json:"volume_id"`
	}

	CreateSnapshotRequest struct {
		VolumeID string `json:"volume_id"`
		Label    string `json:"label,omitempty"`
	}
	CreateSnapshotResponse struct {
		Hash string `json:"hash"`
	}

	ListSnapshotsRequest struct {
		VolumeID string `json:"volume_id"`
	}
	ListSnapshotsResponse struct {
		Snapshots []cas.Layer `json:"snapshots"`
	}

	RestoreToSnapshotRequest struct {
		VolumeID   string `json:"volume_id"`
		TargetHash string `json:"target_hash"`
	}

	Empty struct{}
)

// jsonCodec implements gRPC's encoding.Codec for JSON serialization.
type jsonCodec struct{}

func (jsonCodec) Marshal(v interface{}) ([]byte, error)     { return json.Marshal(v) }
func (jsonCodec) Unmarshal(data []byte, v interface{}) error { return json.Unmarshal(data, v) }
func (jsonCodec) Name() string                              { return "json" }

// volumeHubServiceServer is the interface type required by gRPC's RegisterService.
type volumeHubServiceServer interface{}

func registerVolumeHubServer(srv *grpc.Server, s *Server) {
	srv.RegisterService(&grpc.ServiceDesc{
		ServiceName: "volumehub.VolumeHub",
		HandlerType: (*volumeHubServiceServer)(nil),
		Methods: []grpc.MethodDesc{
			{MethodName: "CreateVolume", Handler: s.handleCreateVolume},
			{MethodName: "DeleteVolume", Handler: s.handleDeleteVolume},
			{MethodName: "EnsureCached", Handler: s.handleEnsureCached},
			{MethodName: "TriggerSync", Handler: s.handleTriggerSync},
			{MethodName: "VolumeStatus", Handler: s.handleVolumeStatus},
			{MethodName: "CreateServiceVolume", Handler: s.handleCreateServiceVolume},
			{MethodName: "CreateSnapshot", Handler: s.handleCreateSnapshot},
			{MethodName: "ListSnapshots", Handler: s.handleListSnapshots},
			{MethodName: "RestoreToSnapshot", Handler: s.handleRestoreToSnapshot},
		},
		Streams: []grpc.StreamDesc{},
	}, s)
}

// ---------------------------------------------------------------------------
// Handler implementations — all delegate to nodes via nodeClient
// ---------------------------------------------------------------------------

func (s *Server) handleCreateVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req CreateVolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	volumeID, err := generateVolumeID()
	if err != nil {
		return nil, status.Errorf(codes.Internal, "generate volume id: %v", err)
	}

	nodeName, err := s.CreateVolumeOnNode(ctx, volumeID, req.Template, req.HintNode)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "%v", err)
	}
	return &CreateVolumeResponse{VolumeID: volumeID, NodeName: nodeName}, nil
}

func (s *Server) handleDeleteVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req DeleteVolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	if err := s.DeleteVolumeFromNode(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "%v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleEnsureCached(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req EnsureCachedRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	// If hint_node already has it cached, return immediately.
	if req.HintNode != "" && s.registry.IsCached(req.VolumeID, req.HintNode) {
		return &EnsureCachedResponse{NodeName: req.HintNode}, nil
	}

	// Check if any node already has it cached.
	cachedNodes := s.registry.GetCachedNodes(req.VolumeID)
	if len(cachedNodes) > 0 {
		for _, n := range cachedNodes {
			if n == req.HintNode {
				return &EnsureCachedResponse{NodeName: n}, nil
			}
		}
		return &EnsureCachedResponse{NodeName: cachedNodes[0]}, nil
	}

	// Volume not cached anywhere — need to transfer.
	ownerNode := s.registry.GetOwner(req.VolumeID)

	targetNode := req.HintNode
	if targetNode == "" {
		registeredNodes := s.registry.RegisteredNodes()
		if len(registeredNodes) == 0 {
			return nil, status.Error(codes.FailedPrecondition, "no compute nodes registered")
		}
		targetNode = registeredNodes[0]
	}

	if ownerNode != "" && ownerNode != targetNode {
		// Peer transfer: tell owner node to send volume to target.
		ownerClient, err := s.nodeClient(ownerNode)
		if err != nil {
			klog.Warningf("EnsureCached: owner %s unavailable (%v), trying CAS restore", ownerNode, err)
		} else {
			defer ownerClient.Close()
			targetAddr := s.resolveAddr(targetNode)
			if targetAddr == "" {
				klog.Warningf("EnsureCached: cannot resolve address for target %s, trying CAS restore", targetNode)
			} else if err := ownerClient.SendVolumeTo(ctx, req.VolumeID, targetAddr); err != nil {
				klog.Warningf("EnsureCached: peer transfer from %s to %s failed: %v, trying CAS restore", ownerNode, targetNode, err)
			} else {
				s.registry.SetCached(req.VolumeID, targetNode)
				klog.Infof("EnsureCached: peer-transferred volume %s from %s to %s", req.VolumeID, ownerNode, targetNode)
				return &EnsureCachedResponse{NodeName: targetNode}, nil
			}
		}
	}

	// Fallback: restore from CAS on target node.
	targetClient, err := s.nodeClient(targetNode)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "connect to target %s: %v", targetNode, err)
	}
	defer targetClient.Close()

	if err := targetClient.RestoreVolume(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "restore volume %s on %s: %v", req.VolumeID, targetNode, err)
	}

	s.registry.SetCached(req.VolumeID, targetNode)
	klog.Infof("EnsureCached: restored volume %s from CAS on %s", req.VolumeID, targetNode)
	return &EnsureCachedResponse{NodeName: targetNode}, nil
}

func (s *Server) handleTriggerSync(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req TriggerSyncRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	ownerNode := s.registry.GetOwner(req.VolumeID)
	if ownerNode == "" {
		return nil, status.Errorf(codes.NotFound, "no owner node for volume %q", req.VolumeID)
	}

	client, err := s.nodeClient(ownerNode)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "connect to owner %s: %v", ownerNode, err)
	}
	defer client.Close()

	if err := client.SyncVolume(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "sync volume %s on %s: %v", req.VolumeID, ownerNode, err)
	}

	s.registry.MarkSynced(req.VolumeID)
	klog.Infof("TriggerSync: synced volume %s on %s", req.VolumeID, ownerNode)
	return &Empty{}, nil
}

func (s *Server) handleVolumeStatus(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req VolumeStatusRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	regStatus := s.registry.GetVolumeStatus(req.VolumeID)
	if regStatus == nil {
		return nil, status.Errorf(codes.NotFound, "volume %q not registered", req.VolumeID)
	}

	// Enrich with manifest data if CAS is available.
	if s.cas != nil {
		manifest, err := s.cas.GetManifest(ctx, req.VolumeID)
		if err == nil {
			regStatus.LatestHash = manifest.LatestHash()
			regStatus.LayerCount = len(manifest.Layers)
			for _, l := range manifest.Layers {
				if l.Type == "snapshot" {
					regStatus.Snapshots = append(regStatus.Snapshots, l)
				}
			}
		}
	}

	return regStatus, nil
}

func (s *Server) handleCreateServiceVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req CreateServiceVolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.BaseVolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "base_volume_id is required")
	}
	if req.ServiceName == "" {
		return nil, status.Error(codes.InvalidArgument, "service_name is required")
	}

	ownerNode := s.registry.GetOwner(req.BaseVolumeID)
	if ownerNode == "" {
		return nil, status.Errorf(codes.NotFound, "no owner for base volume %q", req.BaseVolumeID)
	}

	client, err := s.nodeClient(ownerNode)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "connect to owner %s: %v", ownerNode, err)
	}
	defer client.Close()

	serviceVolumeID := req.BaseVolumeID + "-" + req.ServiceName
	volumePath := "volumes/" + serviceVolumeID

	exists, err := client.SubvolumeExists(ctx, volumePath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check service volume: %v", err)
	}
	if exists {
		klog.V(2).Infof("Service volume %s already exists on %s", serviceVolumeID, ownerNode)
		return &CreateServiceVolumeResponse{VolumeID: serviceVolumeID}, nil
	}

	if err := client.CreateSubvolume(ctx, volumePath); err != nil {
		return nil, status.Errorf(codes.Internal, "create service subvolume: %v", err)
	}

	if err := client.SetOwnership(ctx, volumePath, 1000, 1000); err != nil {
		klog.Warningf("SetOwnership for service volume %s: %v", serviceVolumeID, err)
	}

	klog.Infof("Created service volume %s on %s (base=%s, service=%s)", serviceVolumeID, ownerNode, req.BaseVolumeID, req.ServiceName)
	return &CreateServiceVolumeResponse{VolumeID: serviceVolumeID}, nil
}

// ---------------------------------------------------------------------------
// New snapshot CRUD handlers
// ---------------------------------------------------------------------------

func (s *Server) handleCreateSnapshot(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req CreateSnapshotRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	hash, err := s.CreateSnapshotForVolume(ctx, req.VolumeID, req.Label)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "%v", err)
	}
	return &CreateSnapshotResponse{Hash: hash}, nil
}

func (s *Server) handleListSnapshots(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req ListSnapshotsRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	if s.cas == nil {
		return nil, status.Error(codes.FailedPrecondition, "CAS store not available")
	}

	manifest, err := s.cas.GetManifest(ctx, req.VolumeID)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "get manifest for %s: %v", req.VolumeID, err)
	}

	var snapshots []cas.Layer
	for _, l := range manifest.Layers {
		if l.Type == "snapshot" {
			snapshots = append(snapshots, l)
		}
	}

	return &ListSnapshotsResponse{Snapshots: snapshots}, nil
}

func (s *Server) handleRestoreToSnapshot(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req RestoreToSnapshotRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.VolumeID == "" || req.TargetHash == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and target_hash required")
	}

	ownerNode := s.registry.GetOwner(req.VolumeID)
	if ownerNode == "" {
		return nil, status.Errorf(codes.NotFound, "no owner node for volume %q", req.VolumeID)
	}

	client, err := s.nodeClient(ownerNode)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "connect to owner %s: %v", ownerNode, err)
	}
	defer client.Close()

	if err := client.RestoreFromSnapshot(ctx, req.VolumeID, req.TargetHash); err != nil {
		return nil, status.Errorf(codes.Internal, "restore snapshot for %s: %v", req.VolumeID, err)
	}

	s.registry.SetLatestHash(req.VolumeID, req.TargetHash)
	klog.Infof("RestoreToSnapshot: volume %s → %s", req.VolumeID, cas.ShortHash(req.TargetHash))
	return &Empty{}, nil
}

// ---------------------------------------------------------------------------
// Exported methods for in-process CSI controller delegation
// ---------------------------------------------------------------------------

// CreateVolumeOnNode creates a volume with the given ID on the best available
// node. If hintNode is non-empty it is preferred, otherwise the least-loaded
// registered node is chosen. Returns the node the volume was placed on.
func (s *Server) CreateVolumeOnNode(ctx context.Context, volumeID, template, hintNode string) (string, error) {
	targetNode := hintNode
	if targetNode == "" {
		targetNode = s.registry.LeastLoadedNode()
		if targetNode == "" {
			return "", fmt.Errorf("no compute nodes registered")
		}
	}

	client, err := s.nodeClient(targetNode)
	if err != nil {
		return "", fmt.Errorf("connect to node %s: %v", targetNode, err)
	}
	defer client.Close()

	volumePath := "volumes/" + volumeID
	var templateHash string

	if template != "" {
		if err := client.EnsureTemplate(ctx, template); err != nil {
			return "", fmt.Errorf("ensure template %q on %s: %v", template, targetNode, err)
		}
		if err := client.SnapshotSubvolume(ctx, "templates/"+template, volumePath, false); err != nil {
			return "", fmt.Errorf("snapshot template to volume: %v", err)
		}
		if s.cas != nil {
			if h, hashErr := s.cas.GetTemplateHash(ctx, template); hashErr == nil {
				templateHash = h
			}
		}
	} else {
		if err := client.CreateSubvolume(ctx, volumePath); err != nil {
			return "", fmt.Errorf("create subvolume: %v", err)
		}
		if err := client.SetOwnership(ctx, volumePath, 1000, 1000); err != nil {
			return "", fmt.Errorf("set ownership: %v", err)
		}
	}

	if s.cas != nil {
		manifest := &cas.Manifest{
			VolumeID:     volumeID,
			Base:         templateHash,
			TemplateName: template,
		}
		if putErr := s.cas.PutManifest(ctx, manifest); putErr != nil {
			klog.Warningf("CreateVolumeOnNode: manifest write for %s: %v", volumeID, putErr)
		}
	}

	if err := client.TrackVolume(ctx, volumeID, template, templateHash); err != nil {
		klog.Warningf("CreateVolumeOnNode: track %s on %s: %v", volumeID, targetNode, err)
	}

	s.registry.RegisterVolume(volumeID)
	s.registry.SetOwner(volumeID, targetNode)
	s.registry.SetCached(volumeID, targetNode)
	s.registry.SetVolumeTemplate(volumeID, template, templateHash)

	if template != "" {
		s.registry.RegisterTemplate(template, targetNode)
	}

	klog.Infof("Created volume %s on node %s (template=%q, base=%s)", volumeID, targetNode, template, cas.ShortHash(templateHash))
	return targetNode, nil
}

// DeleteVolumeFromNode deletes a volume by finding its owner node in the
// registry. Idempotent: returns nil if the volume is unknown.
func (s *Server) DeleteVolumeFromNode(ctx context.Context, volumeID string) error {
	ownerNode := s.registry.GetOwner(volumeID)
	if ownerNode != "" {
		client, err := s.nodeClient(ownerNode)
		if err != nil {
			klog.Warningf("DeleteVolumeFromNode: connect to owner %s: %v", ownerNode, err)
		} else {
			defer client.Close()
			if err := client.UntrackVolume(ctx, volumeID); err != nil {
				klog.Warningf("DeleteVolumeFromNode: untrack %s on %s: %v", volumeID, ownerNode, err)
			}
			if err := client.DeleteSubvolume(ctx, "volumes/"+volumeID); err != nil {
				klog.Warningf("DeleteVolumeFromNode: delete %s on %s: %v", volumeID, ownerNode, err)
			}
			if err := client.DeleteVolumeCAS(ctx, volumeID); err != nil {
				klog.Warningf("DeleteVolumeFromNode: CAS cleanup %s: %v", volumeID, err)
			}
		}
	}

	s.registry.UnregisterVolume(volumeID)
	klog.Infof("Deleted volume %s", volumeID)
	return nil
}

// CreateSnapshotForVolume creates a CAS user snapshot for the given volume,
// delegating to the volume's owner node. Returns the snapshot layer hash.
func (s *Server) CreateSnapshotForVolume(ctx context.Context, volumeID, label string) (string, error) {
	ownerNode := s.registry.GetOwner(volumeID)
	if ownerNode == "" {
		return "", fmt.Errorf("no owner node for volume %q", volumeID)
	}

	client, err := s.nodeClient(ownerNode)
	if err != nil {
		return "", fmt.Errorf("connect to owner %s: %v", ownerNode, err)
	}
	defer client.Close()

	hash, err := client.CreateUserSnapshot(ctx, volumeID, label)
	if err != nil {
		return "", fmt.Errorf("create snapshot for %s: %v", volumeID, err)
	}

	s.registry.SetLatestHash(volumeID, hash)
	klog.Infof("CreateSnapshotForVolume: %s → %s (label=%s)", volumeID, cas.ShortHash(hash), label)
	return hash, nil
}

// NodeClientFor creates a nodeops client for the given node name. The caller
// is responsible for calling Close() on the returned client.
func (s *Server) NodeClientFor(nodeName string) (*nodeops.Client, error) {
	return s.nodeClient(nodeName)
}

// GetOwnerNode returns the owner node of a volume, or "" if unknown.
func (s *Server) GetOwnerNode(volumeID string) string {
	return s.registry.GetOwner(volumeID)
}

// VolumeRegistered returns true if the volume has an owner in the registry.
func (s *Server) VolumeRegistered(volumeID string) bool {
	return s.registry.GetOwner(volumeID) != ""
}

// AggregateCapacity returns the total available bytes across all registered
// compute nodes. Nodes that are unreachable are skipped.
func (s *Server) AggregateCapacity(ctx context.Context) (int64, error) {
	var totalAvailable int64
	for _, nodeName := range s.registry.RegisteredNodes() {
		client, err := s.nodeClient(nodeName)
		if err != nil {
			klog.Warningf("AggregateCapacity: skip node %s: %v", nodeName, err)
			continue
		}
		_, available, err := client.GetCapacity(ctx)
		client.Close()
		if err != nil {
			klog.Warningf("AggregateCapacity: GetCapacity on %s: %v", nodeName, err)
			continue
		}
		totalAvailable += available
	}
	return totalAvailable, nil
}

// RegisteredVolumeIDs returns all volume IDs known to the registry.
func (s *Server) RegisteredVolumeIDs() []string {
	return s.registry.AllVolumeIDs()
}

// Registry returns the Hub's NodeRegistry for direct access by the CSI
// controller (e.g. registering volumes created from snapshots).
func (s *Server) Registry() *NodeRegistry {
	return s.registry
}

// ---------------------------------------------------------------------------
// Discovery and registry rebuild
// ---------------------------------------------------------------------------

// DiscoverNodes uses the NodeResolver to find CSI nodes via K8s Endpoints API
// and registers them by their stable K8s node names.
func (s *Server) DiscoverNodes(resolver *NodeResolver) error {
	names := resolver.NodeNames()
	if len(names) == 0 {
		return fmt.Errorf("no CSI nodes found in endpoints")
	}
	for _, name := range names {
		s.registry.RegisterNode(name)
	}
	klog.Infof("DiscoverNodes: registered %d CSI nodes", len(names))
	return nil
}

// RebuildRegistry queries all known CSI nodes to rebuild the Hub's in-memory
// state. Called on startup to recover from restarts.
func (s *Server) RebuildRegistry(ctx context.Context) error {
	nodes := s.registry.RegisteredNodes()
	if len(nodes) == 0 {
		klog.Info("RebuildRegistry: no nodes registered, skipping")
		return nil
	}

	klog.Infof("RebuildRegistry: querying %d nodes", len(nodes))
	for _, nodeName := range nodes {
		client, err := s.nodeClient(nodeName)
		if err != nil {
			klog.Warningf("RebuildRegistry: skip node %s: %v", nodeName, err)
			continue
		}

		// Get sync state to find tracked volumes with template context.
		states, err := client.GetSyncState(ctx)
		if err != nil {
			klog.Warningf("RebuildRegistry: GetSyncState on %s: %v", nodeName, err)
			client.Close()
			continue
		}
		for _, st := range states {
			s.registry.RegisterVolume(st.VolumeID)
			s.registry.SetOwner(st.VolumeID, nodeName)
			s.registry.SetCached(st.VolumeID, nodeName)
			if st.TemplateHash != "" {
				s.registry.SetVolumeTemplate(st.VolumeID, "", st.TemplateHash)
			}
		}

		// List subvolumes to find cached volumes not in sync tracking.
		subs, err := client.ListSubvolumes(ctx, "volumes/")
		if err != nil {
			klog.Warningf("RebuildRegistry: ListSubvolumes on %s: %v", nodeName, err)
		} else {
			for _, sub := range subs {
				volID := strings.TrimPrefix(sub.Path, "volumes/")
				if volID != "" && volID != sub.Path {
					s.registry.RegisterVolume(volID)
					s.registry.SetCached(volID, nodeName)
					if s.registry.GetOwner(volID) == "" {
						s.registry.SetOwner(volID, nodeName)
					}
				}
			}
		}

		// List templates.
		tmpls, err := client.ListSubvolumes(ctx, "templates/")
		if err != nil {
			klog.Warningf("RebuildRegistry: ListSubvolumes templates on %s: %v", nodeName, err)
		} else {
			for _, sub := range tmpls {
				tmplName := strings.TrimPrefix(sub.Path, "templates/")
				if tmplName != "" && tmplName != sub.Path {
					s.registry.RegisterTemplate(tmplName, nodeName)
				}
			}
		}

		client.Close()
		klog.V(2).Infof("RebuildRegistry: processed node %s (%d volumes)", nodeName, len(states))
	}

	klog.Info("RebuildRegistry: complete")
	return nil
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// generateVolumeID creates a volume ID in the format "vol-{12 hex chars}".
func generateVolumeID() (string, error) {
	b := make([]byte, 6)
	if _, err := rand.Read(b); err != nil {
		return "", fmt.Errorf("read crypto/rand: %w", err)
	}
	return "vol-" + hex.EncodeToString(b), nil
}
