package volumehub

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/nodeops"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

// newTestServer creates a Server with a registry, no CAS, and a nodeClient
// factory that always returns an error (no real nodes). liveNodeNames controls
// what liveNodes() returns.
func newTestServer(liveNodeNames []string) (*Server, *NodeRegistry) {
	registry := NewNodeRegistry()
	srv := NewServer(
		registry,
		nil, // no CAS
		func(nodeName string) (*nodeops.Client, error) {
			return nil, fmt.Errorf("no test node %q", nodeName)
		},
		func(nodeName string) string { return "" },
		func() []string { return liveNodeNames },
	)
	return srv, registry
}

// callEnsureCached invokes handleEnsureCached via the Server's method with
// a synthetic decoder, simulating a gRPC call.
func callEnsureCached(s *Server, req EnsureCachedRequest) (*EnsureCachedResponse, error) {
	dec := func(v interface{}) error {
		// Round-trip through JSON to match real gRPC codec behaviour.
		b, _ := json.Marshal(req)
		return json.Unmarshal(b, v)
	}
	resp, err := s.handleEnsureCached(nil, context.Background(), dec, nil)
	if err != nil {
		return nil, err
	}
	return resp.(*EnsureCachedResponse), nil
}

// ---------------------------------------------------------------------------
// NodeVolumeCount
// ---------------------------------------------------------------------------

func TestNodeVolumeCount(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterNode("node-a")
	r.SetCached("vol-1", "node-a")
	r.SetCached("vol-2", "node-a")
	r.RegisterNode("node-b")

	if got := r.NodeVolumeCount("node-a"); got != 2 {
		t.Errorf("NodeVolumeCount(node-a) = %d, want 2", got)
	}
	if got := r.NodeVolumeCount("node-b"); got != 0 {
		t.Errorf("NodeVolumeCount(node-b) = %d, want 0", got)
	}
	if got := r.NodeVolumeCount("unknown"); got != 0 {
		t.Errorf("NodeVolumeCount(unknown) = %d, want 0", got)
	}
}

// ---------------------------------------------------------------------------
// EnsureCached — liveness-aware placement
// ---------------------------------------------------------------------------

func TestEnsureCached_FastPath_LiveCachedCandidate(t *testing.T) {
	srv, reg := newTestServer([]string{"node-a", "node-b"})
	reg.RegisterNode("node-a")
	reg.RegisterNode("node-b")
	reg.RegisterVolume("vol-1")
	reg.SetOwner("vol-1", "node-a")
	reg.SetCached("vol-1", "node-a")

	resp, err := callEnsureCached(srv, EnsureCachedRequest{
		VolumeID:       "vol-1",
		CandidateNodes: []string{"node-a", "node-b"},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.NodeName != "node-a" {
		t.Errorf("got node %q, want node-a (fast path)", resp.NodeName)
	}
}

func TestEnsureCached_StaleNode_ReturnsError(t *testing.T) {
	// Volume cached on dead-node, candidates = [dead-node] but dead-node
	// is NOT in the live set. Should return FailedPrecondition.
	srv, reg := newTestServer([]string{"live-node"})
	reg.RegisterNode("dead-node")
	reg.RegisterNode("live-node")
	reg.RegisterVolume("vol-1")
	reg.SetOwner("vol-1", "dead-node")
	reg.SetCached("vol-1", "dead-node")

	_, err := callEnsureCached(srv, EnsureCachedRequest{
		VolumeID:       "vol-1",
		CandidateNodes: []string{"dead-node"},
	})
	if err == nil {
		t.Fatal("expected error for all-dead candidates")
	}
	st, ok := status.FromError(err)
	if !ok || st.Code() != codes.FailedPrecondition {
		t.Errorf("expected FailedPrecondition, got %v", err)
	}
}

func TestEnsureCached_StaleNode_CleansCacheEntry(t *testing.T) {
	// Volume cached on dead-node and live-node. After the call, the stale
	// cache entry for dead-node should be removed from the registry.
	srv, reg := newTestServer([]string{"live-node"})
	reg.RegisterNode("dead-node")
	reg.RegisterNode("live-node")
	reg.RegisterVolume("vol-1")
	reg.SetCached("vol-1", "dead-node")
	reg.SetCached("vol-1", "live-node")

	resp, err := callEnsureCached(srv, EnsureCachedRequest{
		VolumeID:       "vol-1",
		CandidateNodes: []string{"live-node"},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.NodeName != "live-node" {
		t.Errorf("got %q, want live-node", resp.NodeName)
	}

	// Stale entry should be cleaned.
	if reg.IsCached("vol-1", "dead-node") {
		t.Error("dead-node cache entry should have been removed")
	}
}

func TestEnsureCached_LiveCachedNotInCandidates_TriesPeerTransfer(t *testing.T) {
	// Volume cached on live-node-a (not a candidate), candidates = [live-node-b].
	// nodeClient returns error, so peer transfer will fail and fall through
	// to CAS restore (which also fails). The key test is that it does NOT
	// return live-node-a (not in candidates).
	srv, reg := newTestServer([]string{"live-node-a", "live-node-b"})
	reg.RegisterNode("live-node-a")
	reg.RegisterNode("live-node-b")
	reg.RegisterVolume("vol-1")
	reg.SetCached("vol-1", "live-node-a")

	_, err := callEnsureCached(srv, EnsureCachedRequest{
		VolumeID:       "vol-1",
		CandidateNodes: []string{"live-node-b"},
	})
	// Both peer transfer and CAS restore fail (no real nodes), but we verify
	// it attempted to use live-node-b as the target (error message).
	if err == nil {
		t.Fatal("expected error (no real node connection)")
	}
	// The error should be about connecting to live-node-b, not returning live-node-a.
	st, _ := status.FromError(err)
	if st.Code() != codes.Internal {
		t.Errorf("expected Internal error (connect failure), got %v", st.Code())
	}
}

func TestEnsureCached_NoCandidates_UsesAllLiveNodes(t *testing.T) {
	// No candidates specified — Hub picks from all live nodes.
	// Volume cached on live-node-a → should return it (fast path).
	srv, reg := newTestServer([]string{"live-node-a", "live-node-b"})
	reg.RegisterNode("live-node-a")
	reg.RegisterNode("live-node-b")
	reg.RegisterVolume("vol-1")
	reg.SetCached("vol-1", "live-node-a")

	resp, err := callEnsureCached(srv, EnsureCachedRequest{
		VolumeID: "vol-1",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.NodeName != "live-node-a" {
		t.Errorf("got %q, want live-node-a", resp.NodeName)
	}
}

func TestEnsureCached_AllCandidatesDead_FailedPrecondition(t *testing.T) {
	srv, _ := newTestServer([]string{"live-node-x"})

	_, err := callEnsureCached(srv, EnsureCachedRequest{
		VolumeID:       "vol-1",
		CandidateNodes: []string{"dead-1", "dead-2"},
	})
	if err == nil {
		t.Fatal("expected error for all-dead candidates")
	}
	st, ok := status.FromError(err)
	if !ok || st.Code() != codes.FailedPrecondition {
		t.Errorf("expected FailedPrecondition, got %v", err)
	}
}

func TestEnsureCached_BackwardCompat_HintNodeAsSingleCandidate(t *testing.T) {
	// Old caller sends hint_node only (no candidate_nodes).
	// Should be treated as a single-element candidate list.
	srv, reg := newTestServer([]string{"node-a"})
	reg.RegisterNode("node-a")
	reg.RegisterVolume("vol-1")
	reg.SetCached("vol-1", "node-a")

	resp, err := callEnsureCached(srv, EnsureCachedRequest{
		VolumeID: "vol-1",
		HintNode: "node-a",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.NodeName != "node-a" {
		t.Errorf("got %q, want node-a (backward compat)", resp.NodeName)
	}
}

func TestEnsureCached_NoLiveNodes_FailedPrecondition(t *testing.T) {
	srv, _ := newTestServer([]string{}) // no live nodes at all

	_, err := callEnsureCached(srv, EnsureCachedRequest{
		VolumeID: "vol-1",
	})
	if err == nil {
		t.Fatal("expected error for no live nodes")
	}
	st, ok := status.FromError(err)
	if !ok || st.Code() != codes.FailedPrecondition {
		t.Errorf("expected FailedPrecondition, got %v", err)
	}
}

// ---------------------------------------------------------------------------
// pickBestCandidate
// ---------------------------------------------------------------------------

func TestPickBestCandidate_LeastLoaded(t *testing.T) {
	srv, reg := newTestServer(nil)
	reg.RegisterNode("node-a")
	reg.RegisterNode("node-b")
	// Put 3 volumes on node-a, 1 on node-b.
	reg.SetCached("v1", "node-a")
	reg.SetCached("v2", "node-a")
	reg.SetCached("v3", "node-a")
	reg.SetCached("v4", "node-b")

	candidates := map[string]struct{}{
		"node-a": {},
		"node-b": {},
	}
	best := srv.pickBestCandidate(candidates)
	if best != "node-b" {
		t.Errorf("got %q, want node-b (least loaded)", best)
	}
}

func TestPickBestCandidate_TieBreakLexicographic(t *testing.T) {
	srv, reg := newTestServer(nil)
	reg.RegisterNode("node-b")
	reg.RegisterNode("node-a")
	// Both have 0 volumes.

	candidates := map[string]struct{}{
		"node-a": {},
		"node-b": {},
	}
	best := srv.pickBestCandidate(candidates)
	if best != "node-a" {
		t.Errorf("got %q, want node-a (lexicographic tie-break)", best)
	}
}
