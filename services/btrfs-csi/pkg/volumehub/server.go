package volumehub

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/encoding"
	"google.golang.org/grpc/keepalive"
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

// LiveNodesFn returns the names of all K8s nodes that currently have a CSI
// pod running (i.e. they appear in the Endpoints watch). Used by EnsureCached
// to filter out stale registry entries for terminated nodes.
type LiveNodesFn func() []string

// inflightRestore tracks a background CAS restore so concurrent callers can
// wait on the same channel instead of spawning duplicate restores.
type inflightRestore struct {
	done chan struct{}
	node string
	err  error
}

// Server implements the VolumeHub gRPC service as a storageless orchestrator.
// It holds zero storage, zero btrfs — nodes handle all data. The Hub only
// coordinates: volume→owner_node mapping, template→cached_nodes, node→capacity.
type Server struct {
	registry        *NodeRegistry
	cas             *cas.Store // for manifest reads (ListSnapshots, EnsureCached)
	nodeClient      NodeClientFactory
	resolveAddr     NodeAddrResolver
	liveNodes       LiveNodesFn
	resWatcher      *ResourceWatcher // standalone resource headroom (no registry dependency)
	orchestratorURL string           // base URL for volume event callbacks (fire-and-forget)
	srv             *grpc.Server

	mu       sync.Mutex
	inflight map[string]*inflightRestore

	// Per-volume write locks for manifest mutations (AppendSnapshot, SetManifestHead).
	volMu    sync.Mutex
	volLocks map[string]*sync.Mutex

	// registryWarmed is set after the first successful RebuildRegistry.
	// RPCs that hit an empty owner use this to decide whether to attempt
	// a rebuild before returning NOT_FOUND.
	registryWarmed atomic.Bool
}

// NewServer creates a VolumeHub Server.
func NewServer(registry *NodeRegistry, casStore *cas.Store, nodeClient NodeClientFactory, resolveAddr NodeAddrResolver, liveNodes LiveNodesFn, resWatcher *ResourceWatcher) *Server {
	return &Server{
		registry:    registry,
		cas:         casStore,
		nodeClient:  nodeClient,
		resolveAddr: resolveAddr,
		liveNodes:   liveNodes,
		resWatcher:  resWatcher,
		inflight:    make(map[string]*inflightRestore),
		volLocks:    make(map[string]*sync.Mutex),
	}
}

// SetOrchestratorURL enables volume event callbacks to the orchestrator.
// The Hub POSTs to {url}/api/internal/volume-events after completing async
// operations (EnsureCached, DeleteVolume) so the frontend can be notified
// in real time via WebSocket.
func (s *Server) SetOrchestratorURL(url string) {
	s.orchestratorURL = url
}

// notifyOrchestrator sends a fire-and-forget volume event to the orchestrator.
// Errors are logged but never block the caller.
func (s *Server) notifyOrchestrator(volumeID, event string) {
	if s.orchestratorURL == "" {
		return
	}
	go func() {
		body, _ := json.Marshal(map[string]string{
			"volume_id": volumeID,
			"event":     event,
		})
		client := &http.Client{Timeout: 5 * time.Second}
		resp, err := client.Post(
			s.orchestratorURL+"/api/internal/volume-events",
			"application/json",
			bytes.NewReader(body),
		)
		if err != nil {
			klog.V(2).Infof("notifyOrchestrator: %v (non-fatal)", err)
			return
		}
		resp.Body.Close()
	}()
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

	// Keepalive: the Python HubClient sends PINGs every 30s with
	// permit_without_calls=1. Without an explicit enforcement policy the
	// gRPC-Go default (5 min min-time, no pings without streams) causes
	// GOAWAY ENHANCE_YOUR_CALM → connection drops.
	opts = append(opts,
		grpc.KeepaliveEnforcementPolicy(keepalive.EnforcementPolicy{
			MinTime:             10 * time.Second, // allow pings as fast as 10s
			PermitWithoutStream: true,             // allow pings on idle connections
		}),
		grpc.KeepaliveParams(keepalive.ServerParameters{
			Time:    60 * time.Second, // server pings client after 60s idle
			Timeout: 10 * time.Second, // wait 10s for ping ack
		}),
	)

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
		VolumeID       string   `json:"volume_id"`
		CandidateNodes []string `json:"candidate_nodes,omitempty"`
		HintNode       string   `json:"hint_node,omitempty"` // deprecated, backward compat
		BudgetCPU      int64    `json:"budget_cpu,omitempty"`  // millicores needed (0 = skip headroom check)
		BudgetMem      int64    `json:"budget_mem,omitempty"`  // bytes needed (0 = skip headroom check)
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

	ResolveVolumeRequest struct {
		VolumeID string `json:"volume_id"`
	}
	ResolveVolumeResponse struct {
		NodeName       string `json:"node_name,omitempty"`
		FileopsAddress string `json:"fileops_address,omitempty"`
		NodeopsAddress string `json:"nodeops_address,omitempty"`
		State          string `json:"state"` // "cached", "restoring", "unavailable"
	}

	TransferOwnershipRequest struct {
		VolumeID string `json:"volume_id"`
		NewNode  string `json:"new_node"`
	}

	ForkVolumeRequest struct {
		SourceVolumeID string `json:"source_volume_id"`
	}
	ForkVolumeResponse struct {
		VolumeID string `json:"volume_id"`
		NodeName string `json:"node_name"`
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
			{MethodName: "ResolveVolume", Handler: s.handleResolveVolume},
			{MethodName: "TransferOwnership", Handler: s.handleTransferOwnership},
			{MethodName: "ForkVolume", Handler: s.handleForkVolume},
			{MethodName: "AppendSnapshot", Handler: s.handleAppendSnapshot},
			{MethodName: "SetManifestHead", Handler: s.handleSetManifestHead},
			{MethodName: "DeleteVolumeManifest", Handler: s.handleDeleteVolumeManifest},
			{MethodName: "DeleteTombstone", Handler: s.handleDeleteTombstoneRPC},
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

	// Backward compat: treat deprecated hint_node as single-element candidate list.
	candidates := req.CandidateNodes
	if len(candidates) == 0 && req.HintNode != "" {
		candidates = []string{req.HintNode}
	}

	// 1. Get live nodes from the K8s watch.
	liveSet := make(map[string]struct{})
	if s.liveNodes != nil {
		for _, n := range s.liveNodes() {
			liveSet[n] = struct{}{}
		}
	}

	// 2. Build candidate set = intersection(caller candidates, live nodes).
	//    If no candidates provided, all live nodes are candidates.
	candidateSet := make(map[string]struct{})
	if len(candidates) > 0 {
		for _, c := range candidates {
			if _, alive := liveSet[c]; alive {
				candidateSet[c] = struct{}{}
			}
		}
		if len(candidateSet) == 0 {
			// All caller-specified candidates are dead — fall back to any
			// live node.  This handles transient states like cordoned nodes
			// or CSI pods restarting.  The caller can still schedule the pod
			// on whatever node we pick (K8s treats unschedulable as a hint,
			// DaemonSet pods tolerate it).
			klog.Warningf("EnsureCached: all candidate nodes dead (candidates=%v) — falling back to any live node", candidates)
			for n := range liveSet {
				candidateSet[n] = struct{}{}
			}
		}
		if len(candidateSet) == 0 {
			return nil, status.Errorf(codes.FailedPrecondition, "no live compute nodes available (candidates=%v were dead, and no other live nodes)", candidates)
		}
	} else {
		// No candidates specified — all live nodes are candidates.
		for n := range liveSet {
			candidateSet[n] = struct{}{}
		}
		if len(candidateSet) == 0 {
			return nil, status.Error(codes.FailedPrecondition, "no live compute nodes available")
		}
	}

	// 2b. Filter candidates by resource headroom if a budget was provided.
	if (req.BudgetCPU > 0 || req.BudgetMem > 0) && s.resWatcher != nil {
		candidateNames := make([]string, 0, len(candidateSet))
		for n := range candidateSet {
			candidateNames = append(candidateNames, n)
		}
		withRoom := s.resWatcher.NodesWithHeadroom(candidateNames, req.BudgetCPU, req.BudgetMem)
		if len(withRoom) == 0 {
			// Soft filter: fall back to all candidates instead of hard-failing.
			// K8s autoscaler needs Pending pods to trigger scale-up — if we
			// reject here, no pod is created and autoscaler never sees demand.
			klog.Warningf("EnsureCached: no candidate has enough resources (need %dm CPU, %d bytes mem) — falling back to least-loaded",
				req.BudgetCPU, req.BudgetMem)
		} else {
			// Rebuild candidateSet to only include nodes with headroom.
			candidateSet = make(map[string]struct{}, len(withRoom))
			for _, n := range withRoom {
				candidateSet[n] = struct{}{}
			}
			klog.V(2).Infof("EnsureCached: budget filter reduced candidates to %d nodes (need %dm CPU, %d bytes mem)",
				len(candidateSet), req.BudgetCPU, req.BudgetMem)
		}
	}

	// 3. Get cached nodes from registry, filter to live-only.
	//    Proactively clean stale entries.
	cachedNodes := s.registry.GetCachedNodes(req.VolumeID)
	var liveCached []string
	for _, n := range cachedNodes {
		if _, alive := liveSet[n]; alive {
			liveCached = append(liveCached, n)
		} else {
			klog.Infof("EnsureCached: removing stale cache entry for volume %s on dead node %s", req.VolumeID, n)
			s.registry.RemoveCached(req.VolumeID, n)
		}
	}

	// 4. Fast path: if any live cached node is in the candidate set, verify
	//    the subvolume actually exists on disk before returning. This catches
	//    stale registry entries (e.g. volume deleted while node was live).
	volPath := fmt.Sprintf("volumes/%s", req.VolumeID)
	for _, n := range liveCached {
		if _, ok := candidateSet[n]; !ok {
			continue
		}
		// Skip nodes where the volume is being evicted — the subvolume
		// may exist momentarily but will be deleted.
		if s.registry.IsEvicting(req.VolumeID, n) {
			klog.V(2).Infof("EnsureCached: skipping %s for volume %s — eviction in progress", n, req.VolumeID)
			continue
		}
		// Quick verification via NodeOps SubvolumeExists (~5ms).
		client, cErr := s.nodeClient(n)
		if cErr != nil {
			klog.Warningf("EnsureCached: fast path verify — cannot connect to %s: %v, evicting", n, cErr)
			s.registry.RemoveCached(req.VolumeID, n)
			continue
		}
		exists, vErr := client.SubvolumeExists(ctx, volPath)
		client.Close()
		if vErr != nil || !exists {
			klog.Infof("EnsureCached: volume %s not on disk at %s (exists=%v, err=%v) — evicting stale cache entry", req.VolumeID, n, exists, vErr)
			s.registry.RemoveCached(req.VolumeID, n)
			continue
		}
		klog.V(2).Infof("EnsureCached: fast path — volume %s verified on candidate %s", req.VolumeID, n)
		return &EnsureCachedResponse{NodeName: n}, nil
	}

	// Re-check liveCached after evictions — some may have been removed above.
	liveCached = nil
	for _, n := range s.registry.GetCachedNodes(req.VolumeID) {
		if _, alive := liveSet[n]; alive {
			liveCached = append(liveCached, n)
		}
	}

	targetNode := s.pickBestCandidate(candidateSet)

	// 5. Volume cached on a live non-candidate node → peer transfer.
	if len(liveCached) > 0 {
		sourceNode := liveCached[0]
		sourceClient, err := s.nodeClient(sourceNode)
		if err != nil {
			klog.Warningf("EnsureCached: source %s unavailable (%v), trying CAS restore", sourceNode, err)
		} else {
			defer sourceClient.Close()
			targetAddr := s.resolveAddr(targetNode)
			if targetAddr == "" {
				klog.Warningf("EnsureCached: cannot resolve address for target %s, trying CAS restore", targetNode)
			} else if err := sourceClient.SendVolumeTo(ctx, req.VolumeID, targetAddr); err != nil {
				klog.Warningf("EnsureCached: peer transfer from %s to %s failed: %v, trying CAS restore", sourceNode, targetNode, err)
			} else {
				s.registry.SetCached(req.VolumeID, targetNode)
				klog.Infof("EnsureCached: peer-transferred volume %s from %s to %s", req.VolumeID, sourceNode, targetNode)
				s.notifyOrchestrator(req.VolumeID, "ready")
				return &EnsureCachedResponse{NodeName: targetNode}, nil
			}
		}
	}

	// 6. No live cache (or peer transfer failed) → restore from CAS (background).
	s.mu.Lock()
	if existing, ok := s.inflight[req.VolumeID]; ok {
		s.mu.Unlock()
		klog.Infof("EnsureCached: joining inflight restore for volume %s", req.VolumeID)
		select {
		case <-existing.done:
			if existing.err != nil {
				return nil, status.Errorf(codes.Internal, "restore volume %s: %v", req.VolumeID, existing.err)
			}
			return &EnsureCachedResponse{NodeName: existing.node}, nil
		case <-ctx.Done():
			return nil, status.Errorf(codes.DeadlineExceeded, "restore in progress for volume %s", req.VolumeID)
		}
	}

	entry := &inflightRestore{done: make(chan struct{})}
	s.inflight[req.VolumeID] = entry
	s.mu.Unlock()

	go func() {
		defer func() {
			if r := recover(); r != nil {
				s.mu.Lock()
				entry.err = fmt.Errorf("panic during restore: %v", r)
				close(entry.done)
				delete(s.inflight, req.VolumeID)
				s.mu.Unlock()
				klog.Errorf("EnsureCached: panic during background restore of %s: %v", req.VolumeID, r)
			}
		}()

		bgCtx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
		defer cancel()

		targetClient, cErr := s.nodeClient(targetNode)
		if cErr != nil {
			s.mu.Lock()
			entry.err = fmt.Errorf("connect to target %s: %w", targetNode, cErr)
			close(entry.done)
			delete(s.inflight, req.VolumeID)
			s.mu.Unlock()
			return
		}
		defer targetClient.Close()

		if rErr := targetClient.RestoreVolume(bgCtx, req.VolumeID); rErr != nil {
			s.mu.Lock()
			entry.err = fmt.Errorf("restore volume %s on %s: %w", req.VolumeID, targetNode, rErr)
			close(entry.done)
			delete(s.inflight, req.VolumeID)
			s.mu.Unlock()
			return
		}

		s.registry.SetCached(req.VolumeID, targetNode)
		klog.Infof("EnsureCached: restored volume %s from CAS on %s (background)", req.VolumeID, targetNode)

		s.mu.Lock()
		entry.node = targetNode
		close(entry.done)
		delete(s.inflight, req.VolumeID)
		s.mu.Unlock()
	}()

	select {
	case <-entry.done:
		if entry.err != nil {
			return nil, status.Errorf(codes.Internal, "restore volume %s: %v", req.VolumeID, entry.err)
		}
		s.notifyOrchestrator(req.VolumeID, "ready")
		return &EnsureCachedResponse{NodeName: entry.node}, nil
	case <-ctx.Done():
		return nil, status.Errorf(codes.DeadlineExceeded, "restore in progress for volume %s", req.VolumeID)
	}
}

// pickBestCandidate returns the candidate with the most resource headroom.
// Deterministic tie-break by lexicographic order.
func (s *Server) pickBestCandidate(candidateSet map[string]struct{}) string {
	candidates := make([]string, 0, len(candidateSet))
	for n := range candidateSet {
		candidates = append(candidates, n)
	}
	ranked := s.rankNodes(candidates)
	if len(ranked) == 0 {
		return ""
	}
	return ranked[0]
}

// rankNodes ranks nodes by headroom if ResourceWatcher is available,
// otherwise falls back to lexicographic order.
func (s *Server) rankNodes(nodes []string) []string {
	if s.resWatcher != nil {
		return s.resWatcher.RankByHeadroom(nodes)
	}
	// Fallback: lexicographic (deterministic, no headroom data).
	out := make([]string, len(nodes))
	copy(out, nodes)
	sort.Strings(out)
	return out
}

func (s *Server) handleTriggerSync(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req TriggerSyncRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	ownerNode, err := s.resolveOwner(ctx, req.VolumeID)
	if err != nil {
		return nil, err
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
			regStatus.LayerCount = manifest.SnapshotCount()
			regStatus.Snapshots = manifest.ListCheckpoints()
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

	// Register the service volume for CAS sync on the target node.
	// Without this, DrainAll would skip the volume and data would be lost
	// if the node is drained before the next periodic discovery cycle.
	if err := client.TrackVolume(ctx, serviceVolumeID, "", ""); err != nil {
		klog.Warningf("TrackVolume for service volume %s on %s: %v", serviceVolumeID, ownerNode, err)
		// Non-fatal: periodic discoverVolumes will pick it up eventually.
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

	snapshots := manifest.ListCheckpoints()

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

	ownerNode, err := s.resolveOwner(ctx, req.VolumeID)
	if err != nil {
		return nil, err
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

func (s *Server) handleResolveVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req ResolveVolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	// 1. Check inflight map — if a restore is already running, return immediately.
	s.mu.Lock()
	_, restoring := s.inflight[req.VolumeID]
	s.mu.Unlock()
	if restoring {
		return &ResolveVolumeResponse{State: "restoring"}, nil
	}

	// 2. Call EnsureCached internally with a 15s budget.
	internalCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()

	ecDec := func(v interface{}) error {
		b, _ := json.Marshal(EnsureCachedRequest{VolumeID: req.VolumeID})
		return json.Unmarshal(b, v)
	}
	resp, err := s.handleEnsureCached(nil, internalCtx, ecDec, nil)
	if err != nil {
		st, ok := status.FromError(err)
		if ok && st.Code() == codes.DeadlineExceeded {
			return &ResolveVolumeResponse{State: "restoring"}, nil
		}
		klog.Warningf("ResolveVolume: EnsureCached failed for %s: %v", req.VolumeID, err)
		return &ResolveVolumeResponse{State: "unavailable"}, nil
	}

	// 3. Build addresses from the returned node name.
	ecResp := resp.(*EnsureCachedResponse)
	nodeopsAddr := s.resolveAddr(ecResp.NodeName)
	fileopsAddr := ""
	if nodeopsAddr != "" {
		if idx := strings.LastIndex(nodeopsAddr, ":"); idx > 0 {
			fileopsAddr = nodeopsAddr[:idx] + ":9742"
		}
	}

	return &ResolveVolumeResponse{
		NodeName:       ecResp.NodeName,
		FileopsAddress: fileopsAddr,
		NodeopsAddress: nodeopsAddr,
		State:          "cached",
	}, nil
}

// ---------------------------------------------------------------------------
// Exported methods for in-process CSI controller delegation
// ---------------------------------------------------------------------------

// CreateVolumeOnNode creates a volume with the given ID on the best available
// node. Always uses live nodes from the resolver — never the registry. If
// hintNode is live it is preferred, otherwise (or on transient failure) the
// least-loaded live node is chosen. Retries once on a different node when a
// gRPC Unavailable / connection error indicates the target is draining.
func (s *Server) CreateVolumeOnNode(ctx context.Context, volumeID, template, hintNode string) (string, error) {
	liveNames := s.liveNodes()
	if len(liveNames) == 0 {
		return "", fmt.Errorf("no live compute nodes available")
	}

	// Build live set for O(1) lookups and least-loaded ranking.
	liveSet := make(map[string]struct{}, len(liveNames))
	for _, n := range liveNames {
		liveSet[n] = struct{}{}
	}

	// Rank all live nodes by resource headroom (most headroom first).
	ranked := s.rankNodes(liveNames)

	// Pick initial target: hintNode if it's live, otherwise least-loaded.
	targetNode := ""
	if hintNode != "" {
		if _, alive := liveSet[hintNode]; alive {
			targetNode = hintNode
		} else {
			klog.Warningf("CreateVolumeOnNode: hintNode %s is not live, ignoring", hintNode)
		}
	}
	if targetNode == "" {
		targetNode = ranked[0]
	}

	node, err := s.tryCreateOnNode(ctx, volumeID, template, targetNode)
	if err != nil && isNodeUnavailable(err) && len(ranked) > 1 {
		// Retry on the next best live node.
		klog.Warningf("CreateVolumeOnNode: %s failed on %s (%v), retrying on different node", volumeID, targetNode, err)
		for _, fallback := range ranked {
			if fallback == targetNode {
				continue
			}
			node, err = s.tryCreateOnNode(ctx, volumeID, template, fallback)
			if err == nil || !isNodeUnavailable(err) {
				break
			}
			klog.Warningf("CreateVolumeOnNode: %s also failed on %s (%v)", volumeID, fallback, err)
		}
	}
	return node, err
}

// isNodeUnavailable returns true for gRPC errors that indicate the node is
// draining, shutting down, or unreachable — i.e. retryable on a different node.
func isNodeUnavailable(err error) bool {
	st, ok := status.FromError(err)
	if ok {
		switch st.Code() {
		case codes.Unavailable, codes.DeadlineExceeded:
			return true
		}
	}
	// Wrapped errors from fmt.Errorf — check the message.
	msg := err.Error()
	return strings.Contains(msg, "Unavailable") ||
		strings.Contains(msg, "connection error") ||
		strings.Contains(msg, "goaway") ||
		strings.Contains(msg, "EOF") ||
		strings.Contains(msg, "graceful_stop")
}

// tryCreateOnNode attempts to create a volume on a specific node. Returns
// (nodeName, nil) on success or (empty, err) on failure.
func (s *Server) tryCreateOnNode(ctx context.Context, volumeID, template, targetNode string) (string, error) {
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

	// Write-through CAS sync for empty volumes (no template). Template-based
	// volumes are reconstructable from the template already in S3, so the
	// initial sync is redundant — the sync daemon will pick it up within 15s.
	// Skip when CAS is not configured (e.g. minikube / local-only mode).
	if s.cas != nil && template == "" {
		if err := client.SyncVolume(ctx, volumeID); err != nil {
			klog.Errorf("CreateVolumeOnNode: initial CAS sync failed for %s on %s: %v — rolling back", volumeID, targetNode, err)
			_ = client.UntrackVolume(ctx, volumeID)
			_ = client.DeleteSubvolume(ctx, "volumes/"+volumeID)
			return "", fmt.Errorf("initial CAS sync failed (volume rolled back): %w", err)
		}
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

// DeleteVolumeFromNode deletes a volume by writing a durable tombstone to S3,
// then performing best-effort cleanup on the owner node. The tombstone ensures
// that offline nodes self-heal on next restart via discoverVolumes.
//
// Returns an error only if the tombstone write fails — the caller should retry.
// Node-side cleanup errors are logged as warnings but do not fail the operation.
func (s *Server) DeleteVolumeFromNode(ctx context.Context, volumeID string) error {
	// Step 1: Write tombstone to S3 FIRST. This is the durable intent record.
	// Even if the Hub crashes after this point, every node's discoverVolumes
	// will see the tombstone and clean up locally.
	if s.cas != nil {
		if err := s.cas.PutTombstone(ctx, volumeID); err != nil {
			return fmt.Errorf("write tombstone for %s: %w", volumeID, err)
		}
	}

	// Step 2: Untrack on ALL cached nodes (not just owner) so no node keeps
	// trying to sync a deleted volume. Best-effort per node.
	cachedNodes := s.registry.GetCachedNodes(volumeID)
	ownerNode := s.registry.GetOwner(volumeID)

	// Include owner in the untrack set even if not in cachedNodes.
	untrackNodes := make(map[string]bool, len(cachedNodes)+1)
	for _, n := range cachedNodes {
		untrackNodes[n] = true
	}
	if ownerNode != "" {
		untrackNodes[ownerNode] = true
	}

	for nodeName := range untrackNodes {
		client, err := s.nodeClient(nodeName)
		if err != nil {
			klog.Warningf("DeleteVolumeFromNode: connect to %s: %v (tombstone written, will self-heal)", nodeName, err)
			continue
		}
		if err := client.UntrackVolume(ctx, volumeID); err != nil {
			klog.Warningf("DeleteVolumeFromNode: untrack %s on %s: %v", volumeID, nodeName, err)
		}
		// Only delete the actual subvolume + CAS data on the owner node.
		if nodeName == ownerNode {
			if err := client.DeleteSubvolume(ctx, "volumes/"+volumeID); err != nil {
				klog.Warningf("DeleteVolumeFromNode: delete %s on %s: %v", volumeID, nodeName, err)
			}
			if err := client.DeleteVolumeCAS(ctx, volumeID); err != nil {
				klog.Warningf("DeleteVolumeFromNode: CAS cleanup %s: %v", volumeID, err)
			}
		}
		client.Close()
	}

	// Step 3: Remove from in-memory registry.
	s.registry.UnregisterVolume(volumeID)

	s.notifyOrchestrator(volumeID, "deleted")
	klog.Infof("Deleted volume %s (tombstone written)", volumeID)
	return nil
}

// CreateSnapshotForVolume creates a CAS user snapshot for the given volume,
// delegating to the volume's owner node. Returns the snapshot layer hash.
func (s *Server) CreateSnapshotForVolume(ctx context.Context, volumeID, label string) (string, error) {
	ownerNode, err := s.resolveOwner(ctx, volumeID)
	if err != nil {
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

// resolveOwner returns the owner node for a volume, triggering a one-time
// registry rebuild if the registry hasn't been warmed yet. This closes the
// startup gap where the Hub restarts and RPCs arrive before the first
// RebuildRegistry completes.
func (s *Server) resolveOwner(ctx context.Context, volumeID string) (string, error) {
	owner := s.registry.GetOwner(volumeID)
	if owner != "" {
		return owner, nil
	}

	// Registry miss — if we haven't completed a rebuild yet, try now.
	if !s.registryWarmed.Load() {
		klog.Infof("resolveOwner: registry cold, triggering rebuild for %s", volumeID)
		if err := s.RebuildRegistry(ctx); err != nil {
			klog.Warningf("resolveOwner: rebuild failed: %v", err)
		}
		owner = s.registry.GetOwner(volumeID)
		if owner != "" {
			return owner, nil
		}
	}

	return "", status.Errorf(codes.NotFound, "no owner node for volume %q", volumeID)
}

// AggregateCapacity returns the total available bytes across all live
// compute nodes. Nodes that are unreachable are skipped.
func (s *Server) AggregateCapacity(ctx context.Context) (int64, error) {
	var totalAvailable int64
	for _, nodeName := range s.liveNodes() {
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

// LiveNodes returns the current set of live CSI node names from the resolver.
func (s *Server) LiveNodes() []string {
	return s.liveNodes()
}

// ---------------------------------------------------------------------------
// Discovery and registry rebuild
// ---------------------------------------------------------------------------

// DiscoverNodes uses the NodeResolver to find CSI nodes via K8s Endpoints API
// and cleans stale volume/template references pointing at dead nodes.
func (s *Server) DiscoverNodes(resolver *NodeResolver) error {
	names := resolver.NodeNames()
	if len(names) == 0 {
		return fmt.Errorf("no CSI nodes found in endpoints")
	}
	if cleaned := s.registry.CleanStaleReferences(names); cleaned > 0 {
		klog.Infof("DiscoverNodes: cleaned %d stale references", cleaned)
	}
	klog.Infof("DiscoverNodes: %d live CSI nodes", len(names))
	return nil
}

// RebuildRegistry queries all live CSI nodes to rebuild the Hub's in-memory
// state. Called on startup to recover from restarts. Uses live nodes from the
// resolver — never the registry — to avoid querying stale/dead nodes.
func (s *Server) RebuildRegistry(ctx context.Context) error {
	nodes := s.liveNodes()
	if len(nodes) == 0 {
		klog.Info("RebuildRegistry: no live nodes, skipping")
		return nil
	}

	klog.Infof("RebuildRegistry: querying %d nodes", len(nodes))
	for _, nodeName := range nodes {
		client, err := s.nodeClient(nodeName)
		if err != nil {
			klog.Warningf("RebuildRegistry: skip node %s: %v", nodeName, err)
			continue
		}

		// List subvolumes first to build the set of physically-present volumes.
		// Only volumes that exist on disk should be marked as cached.
		diskVolumes := make(map[string]struct{})
		subs, err := client.ListSubvolumes(ctx, "volumes/")
		if err != nil {
			klog.Warningf("RebuildRegistry: ListSubvolumes on %s: %v", nodeName, err)
		} else {
			for _, sub := range subs {
				volID := strings.TrimPrefix(sub.Path, "volumes/")
				if volID != "" && volID != sub.Path {
					diskVolumes[volID] = struct{}{}
					s.registry.RegisterVolume(volID)
					s.registry.SetCached(volID, nodeName)
					if s.registry.GetOwner(volID) == "" {
						s.registry.SetOwner(volID, nodeName)
					}
				}
			}
		}

		// Get sync state for template context and ownership, but only mark
		// cached if the subvolume physically exists on disk. A tracked volume
		// with no subvolume means the data was deleted — don't lie about it.
		states, err := client.GetSyncState(ctx)
		if err != nil {
			klog.Warningf("RebuildRegistry: GetSyncState on %s: %v", nodeName, err)
			client.Close()
			continue
		}
		for _, st := range states {
			s.registry.RegisterVolume(st.VolumeID)
			if _, onDisk := diskVolumes[st.VolumeID]; onDisk {
				s.registry.SetOwner(st.VolumeID, nodeName)
				s.registry.SetCached(st.VolumeID, nodeName)
			} else {
				klog.Infof("RebuildRegistry: volume %s tracked on %s but subvolume missing — not marking cached", st.VolumeID, nodeName)
				// Still set owner for sync/metadata purposes, just don't claim cached.
				s.registry.SetOwner(st.VolumeID, nodeName)
			}
			if st.TemplateHash != "" {
				s.registry.SetVolumeTemplate(st.VolumeID, "", st.TemplateHash)
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

	s.registryWarmed.Store(true)
	klog.Info("RebuildRegistry: complete")
	return nil
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// TransferOwnership — explicit ownership transfer (orchestrator-triggered)
// ---------------------------------------------------------------------------

func (s *Server) handleTransferOwnership(_ interface{}, _ context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req TransferOwnershipRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}
	if req.NewNode == "" {
		return nil, status.Error(codes.InvalidArgument, "new_node is required")
	}

	// Validate the volume is cached on the new node
	if !s.registry.IsCached(req.VolumeID, req.NewNode) {
		return nil, status.Errorf(codes.FailedPrecondition,
			"volume %s is not cached on node %s — cannot transfer ownership",
			req.VolumeID, req.NewNode)
	}

	oldOwner := s.registry.GetOwner(req.VolumeID)
	s.registry.SetOwner(req.VolumeID, req.NewNode)

	klog.Infof("TransferOwnership: volume %s ownership transferred %s → %s",
		req.VolumeID, oldOwner, req.NewNode)

	return &Empty{}, nil
}

func (s *Server) handleForkVolume(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req ForkVolumeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}

	if req.SourceVolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "source_volume_id is required")
	}

	newVolumeID, nodeName, err := s.ForkVolumeOnNode(ctx, req.SourceVolumeID)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "%v", err)
	}
	return &ForkVolumeResponse{VolumeID: newVolumeID, NodeName: nodeName}, nil
}

// ForkVolumeOnNode creates a new volume by snapshotting an existing one
// on the same node (btrfs CoW clone — instant, zero copy). The new volume
// gets its own manifest with the source's latest hash as its base.
func (s *Server) ForkVolumeOnNode(ctx context.Context, sourceVolumeID string) (string, string, error) {
	ownerNode := s.registry.GetOwner(sourceVolumeID)
	if ownerNode == "" {
		return "", "", fmt.Errorf("no owner for source volume %q", sourceVolumeID)
	}

	newVolumeID, err := generateVolumeID()
	if err != nil {
		return "", "", fmt.Errorf("generate volume id: %v", err)
	}

	client, err := s.nodeClient(ownerNode)
	if err != nil {
		return "", "", fmt.Errorf("connect to owner %s: %v", ownerNode, err)
	}
	defer client.Close()

	srcPath := "volumes/" + sourceVolumeID
	dstPath := "volumes/" + newVolumeID

	// btrfs snapshot (CoW clone — instant, no data copy)
	if err := client.SnapshotSubvolume(ctx, srcPath, dstPath, false); err != nil {
		return "", "", fmt.Errorf("snapshot %s → %s: %v", srcPath, dstPath, err)
	}

	// Register new volume + set ownership
	s.registry.RegisterVolume(newVolumeID)
	s.registry.SetCached(newVolumeID, ownerNode)
	s.registry.SetOwner(newVolumeID, ownerNode)

	// Track for sync with no template info. The first syncOne will do a
	// full send (captures entire forked state), then auto-promote creates a
	// synthetic template for future incremental syncs. No pre-created
	// manifest — an empty-layers manifest pointing to the source's template
	// would restore to the wrong base on node loss.
	if err := client.TrackVolume(ctx, newVolumeID, "", ""); err != nil {
		klog.Warningf("ForkVolume: TrackVolume for %s: %v (periodic discovery will pick it up)", newVolumeID, err)
	}

	klog.Infof("Forked volume %s → %s on node %s", sourceVolumeID, newVolumeID, ownerNode)
	return newVolumeID, ownerNode, nil
}

// Internal helpers
// ---------------------------------------------------------------------------

// manifestLock returns a per-volume mutex for serializing manifest writes.
func (s *Server) manifestLock(volumeID string) *sync.Mutex {
	s.volMu.Lock()
	defer s.volMu.Unlock()
	mu, ok := s.volLocks[volumeID]
	if !ok {
		mu = &sync.Mutex{}
		s.volLocks[volumeID] = mu
	}
	return mu
}

// ---------------------------------------------------------------------------
// Manifest-write RPCs (Hub = single writer for all coordination state)
// ---------------------------------------------------------------------------

func (s *Server) handleAppendSnapshot(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req AppendSnapshotRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.Snapshot.Hash == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and snapshot.hash are required")
	}
	if s.cas == nil {
		return nil, status.Error(codes.FailedPrecondition, "CAS store not configured")
	}

	vl := s.manifestLock(req.VolumeID)
	vl.Lock()
	defer vl.Unlock()

	manifest, err := s.cas.GetManifest(ctx, req.VolumeID)
	if err != nil {
		manifest = &cas.Manifest{VolumeID: req.VolumeID, Snapshots: make(map[string]cas.Snapshot)}
	}
	manifest.AppendSnapshot(req.Snapshot)
	if err := s.cas.PutManifest(ctx, manifest); err != nil {
		return nil, status.Errorf(codes.Internal, "put manifest: %v", err)
	}
	return &AppendSnapshotResponse{Head: manifest.Head}, nil
}

func (s *Server) handleSetManifestHead(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req SetManifestHeadRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.TargetHash == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and target_hash are required")
	}
	if s.cas == nil {
		return nil, status.Error(codes.FailedPrecondition, "CAS store not configured")
	}

	vl := s.manifestLock(req.VolumeID)
	vl.Lock()
	defer vl.Unlock()

	manifest, err := s.cas.GetManifest(ctx, req.VolumeID)
	if err != nil {
		return nil, status.Errorf(codes.NotFound, "manifest for %s: %v", req.VolumeID, err)
	}
	branchSaved := false
	if req.SaveBranchName != "" && manifest.Head != "" && manifest.Head != req.TargetHash {
		manifest.SaveBranch(req.SaveBranchName, manifest.Head)
		branchSaved = true
	}
	manifest.SetHead(req.TargetHash)
	if err := s.cas.PutManifest(ctx, manifest); err != nil {
		return nil, status.Errorf(codes.Internal, "put manifest: %v", err)
	}
	return &SetManifestHeadResponse{Head: manifest.Head, BranchSaved: branchSaved}, nil
}

func (s *Server) handleDeleteVolumeManifest(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req DeleteVolumeManifestRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}
	if s.cas == nil {
		return nil, status.Error(codes.FailedPrecondition, "CAS store not configured")
	}
	if err := s.cas.DeleteManifest(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "delete manifest: %v", err)
	}
	return &Empty{}, nil
}

func (s *Server) handleDeleteTombstoneRPC(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req DeleteTombstoneRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}
	if s.cas == nil {
		return nil, status.Error(codes.FailedPrecondition, "CAS store not configured")
	}
	if err := s.cas.DeleteTombstone(ctx, req.VolumeID); err != nil {
		return nil, status.Errorf(codes.Internal, "delete tombstone: %v", err)
	}
	return &Empty{}, nil
}

// generateVolumeID creates a volume ID in the format "vol-{12 hex chars}".
func generateVolumeID() (string, error) {
	b := make([]byte, 6)
	if _, err := rand.Read(b); err != nil {
		return "", fmt.Errorf("read crypto/rand: %w", err)
	}
	return "vol-" + hex.EncodeToString(b), nil
}
