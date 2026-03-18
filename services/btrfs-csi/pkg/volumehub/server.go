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

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/encoding"
	"google.golang.org/grpc/status"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/nodeops"
)

func init() {
	encoding.RegisterCodec(jsonCodec{})
}

// NodeClientFactory creates a nodeops client for a given node name.
// The Hub uses this to delegate operations to compute nodes.
type NodeClientFactory func(nodeName string) (*nodeops.Client, error)

// Server implements the VolumeHub gRPC service as a storageless orchestrator.
// It holds zero storage, zero btrfs — nodes handle all data. The Hub only
// coordinates: volume→owner_node mapping, template→cached_nodes, node→capacity.
type Server struct {
	registry   *NodeRegistry
	nodeClient NodeClientFactory
	srv        *grpc.Server
}

// NewServer creates a VolumeHub Server.
func NewServer(registry *NodeRegistry, nodeClient NodeClientFactory) *Server {
	return &Server{
		registry:   registry,
		nodeClient: nodeClient,
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
// This avoids protobuf compilation while still using proper gRPC transport.
// Request/response bodies are JSON-encoded in a wrapper message.

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
	VolumeStatusResponse struct {
		VolumeID    string   `json:"volume_id"`
		OwnerNode   string   `json:"owner_node"`
		CachedNodes []string `json:"cached_nodes"`
		LastSync    string   `json:"last_sync,omitempty"`
	}

	CreateServiceVolumeRequest struct {
		BaseVolumeID string `json:"base_volume_id"`
		ServiceName  string `json:"service_name"`
	}
	CreateServiceVolumeResponse struct {
		VolumeID string `json:"volume_id"`
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

	// Pick target node: prefer hint, then least loaded registered node.
	targetNode := req.HintNode
	if targetNode == "" {
		registeredNodes := s.registry.RegisteredNodes()
		if len(registeredNodes) == 0 {
			return nil, status.Error(codes.FailedPrecondition, "no compute nodes registered")
		}
		targetNode = registeredNodes[0]
	}

	client, err := s.nodeClient(targetNode)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "connect to node %s: %v", targetNode, err)
	}
	defer client.Close()

	volumePath := "volumes/" + volumeID

	if req.Template != "" {
		// Ensure the template exists on the target node.
		if err := client.EnsureTemplate(ctx, req.Template); err != nil {
			return nil, status.Errorf(codes.Internal, "ensure template %q on %s: %v", req.Template, targetNode, err)
		}
		// Snapshot the template into the new volume (writable).
		if err := client.SnapshotSubvolume(ctx, "templates/"+req.Template, volumePath, false); err != nil {
			return nil, status.Errorf(codes.Internal, "snapshot template to volume: %v", err)
		}
	} else {
		// Create an empty subvolume.
		if err := client.CreateSubvolume(ctx, volumePath); err != nil {
			return nil, status.Errorf(codes.Internal, "create subvolume: %v", err)
		}
		// Set ownership to uid/gid 1000 (non-root user in devserver).
		if err := client.SetOwnership(ctx, volumePath, 1000, 1000); err != nil {
			return nil, status.Errorf(codes.Internal, "set ownership: %v", err)
		}
	}

	// Track volume for periodic S3 sync on the node.
	if err := client.TrackVolume(ctx, volumeID); err != nil {
		klog.Warningf("TrackVolume failed for %s on %s: %v", volumeID, targetNode, err)
	}

	// Register in Hub registry with owner.
	s.registry.RegisterVolume(volumeID)
	s.registry.SetOwner(volumeID, targetNode)
	s.registry.SetCached(volumeID, targetNode)

	if req.Template != "" {
		s.registry.RegisterTemplate(req.Template, targetNode)
	}

	klog.Infof("Created volume %s on node %s (template=%q)", volumeID, targetNode, req.Template)
	return &CreateVolumeResponse{VolumeID: volumeID, NodeName: targetNode}, nil
}

func (s *Server) handleDeleteVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req DeleteVolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	ownerNode := s.registry.GetOwner(req.VolumeID)
	if ownerNode != "" {
		client, err := s.nodeClient(ownerNode)
		if err != nil {
			klog.Warningf("DeleteVolume: connect to owner %s failed: %v", ownerNode, err)
		} else {
			defer client.Close()

			// Untrack from sync.
			if err := client.UntrackVolume(ctx, req.VolumeID); err != nil {
				klog.Warningf("DeleteVolume: untrack %s on %s: %v", req.VolumeID, ownerNode, err)
			}

			// Delete subvolume from node.
			volumePath := "volumes/" + req.VolumeID
			if err := client.DeleteSubvolume(ctx, volumePath); err != nil {
				klog.Warningf("DeleteVolume: delete subvolume %s on %s: %v", req.VolumeID, ownerNode, err)
			}

			// Delete from S3 (best-effort).
			if err := client.DeleteFromS3(ctx, req.VolumeID); err != nil {
				klog.Warningf("DeleteVolume: delete S3 for %s: %v", req.VolumeID, err)
			}
		}
	}

	// Remove from registry (idempotent).
	s.registry.UnregisterVolume(req.VolumeID)

	klog.Infof("Deleted volume %s", req.VolumeID)
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
		// Prefer hint_node if it's in the list.
		for _, n := range cachedNodes {
			if n == req.HintNode {
				return &EnsureCachedResponse{NodeName: n}, nil
			}
		}
		return &EnsureCachedResponse{NodeName: cachedNodes[0]}, nil
	}

	// Volume not cached anywhere — need to transfer.
	ownerNode := s.registry.GetOwner(req.VolumeID)

	// Determine target node.
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
			klog.Warningf("EnsureCached: owner %s unavailable (%v), trying S3 restore", ownerNode, err)
		} else {
			defer ownerClient.Close()
			// Get target's nodeops address for the transfer.
			targetAddr := targetNode + ":9741" // Node DaemonSet nodeops port
			if err := ownerClient.SendVolumeTo(ctx, req.VolumeID, targetAddr); err != nil {
				klog.Warningf("EnsureCached: peer transfer from %s to %s failed: %v, trying S3 restore", ownerNode, targetNode, err)
			} else {
				s.registry.SetCached(req.VolumeID, targetNode)
				klog.Infof("EnsureCached: peer-transferred volume %s from %s to %s", req.VolumeID, ownerNode, targetNode)
				return &EnsureCachedResponse{NodeName: targetNode}, nil
			}
		}
	}

	// Fallback: restore from S3 on target node.
	targetClient, err := s.nodeClient(targetNode)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "connect to target %s: %v", targetNode, err)
	}
	defer targetClient.Close()

	if err := targetClient.RestoreVolume(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "restore volume %s on %s: %v", req.VolumeID, targetNode, err)
	}

	s.registry.SetCached(req.VolumeID, targetNode)
	klog.Infof("EnsureCached: restored volume %s from S3 on %s", req.VolumeID, targetNode)
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

	// SyncVolume is already in the NodeOps interface — triggers immediate S3 sync.
	if err := client.SyncVolume(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "sync volume %s on %s: %v", req.VolumeID, ownerNode, err)
	}

	s.registry.MarkSynced(req.VolumeID)
	klog.Infof("TriggerSync: synced volume %s on %s", req.VolumeID, ownerNode)
	return &Empty{}, nil
}

func (s *Server) handleVolumeStatus(_ interface{}, _ context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
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

	return &VolumeStatusResponse{
		VolumeID:    regStatus.VolumeID,
		OwnerNode:   regStatus.OwnerNode,
		CachedNodes: regStatus.CachedNodes,
		LastSync:    regStatus.LastSync,
	}, nil
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

	// Find the owner node of the base volume.
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

	// Idempotent — check if already exists.
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

	// Set ownership to match project volumes (uid:gid 1000).
	if err := client.SetOwnership(ctx, volumePath, 1000, 1000); err != nil {
		klog.Warningf("SetOwnership for service volume %s: %v", serviceVolumeID, err)
	}

	klog.Infof("Created service volume %s on %s (base=%s, service=%s)", serviceVolumeID, ownerNode, req.BaseVolumeID, req.ServiceName)
	return &CreateServiceVolumeResponse{VolumeID: serviceVolumeID}, nil
}

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

		// Get sync state to find tracked volumes.
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
		}

		// List subvolumes to find cached volumes not in sync tracking.
		subs, err := client.ListSubvolumes(ctx, "volumes/")
		if err != nil {
			klog.Warningf("RebuildRegistry: ListSubvolumes on %s: %v", nodeName, err)
		} else {
			for _, sub := range subs {
				// Strip "volumes/" prefix to get volume ID.
				if len(sub.Name) > 8 {
					volID := sub.Name[8:]
					s.registry.RegisterVolume(volID)
					s.registry.SetCached(volID, nodeName)
					// If no owner set yet, this node is the owner.
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
				if len(sub.Name) > 10 {
					tmplName := sub.Name[10:]
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
