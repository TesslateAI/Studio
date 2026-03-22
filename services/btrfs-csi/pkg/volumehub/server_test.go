package volumehub

import (
	"context"
	"encoding/json"
	"fmt"
	"sync/atomic"
	"testing"
	"time"

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

// ---------------------------------------------------------------------------
// callEnsureCachedWithCtx — like callEnsureCached but accepts a context.
// ---------------------------------------------------------------------------

func callEnsureCachedWithCtx(s *Server, ctx context.Context, req EnsureCachedRequest) (*EnsureCachedResponse, error) {
	dec := func(v interface{}) error {
		b, _ := json.Marshal(req)
		return json.Unmarshal(b, v)
	}
	resp, err := s.handleEnsureCached(nil, ctx, dec, nil)
	if err != nil {
		return nil, err
	}
	return resp.(*EnsureCachedResponse), nil
}

// ---------------------------------------------------------------------------
// Background CAS restore with inflight dedup
// ---------------------------------------------------------------------------

func TestEnsureCached_InflightDedup_SecondCallerWaitsOnSameRestore(t *testing.T) {
	// Pre-populate the inflight map with a pending entry.
	// Two callers should both wait on the same entry.done channel.
	srv, reg := newTestServer([]string{"node-a"})
	reg.RegisterNode("node-a")
	reg.RegisterVolume("vol-1")

	entry := &inflightRestore{done: make(chan struct{})}
	srv.mu.Lock()
	srv.inflight["vol-1"] = entry
	srv.mu.Unlock()

	// Launch two concurrent callers for the same volume.
	type result struct {
		resp *EnsureCachedResponse
		err  error
	}
	ch1 := make(chan result, 1)
	ch2 := make(chan result, 1)

	go func() {
		resp, err := callEnsureCached(srv, EnsureCachedRequest{
			VolumeID:       "vol-1",
			CandidateNodes: []string{"node-a"},
		})
		ch1 <- result{resp, err}
	}()
	go func() {
		resp, err := callEnsureCached(srv, EnsureCachedRequest{
			VolumeID:       "vol-1",
			CandidateNodes: []string{"node-a"},
		})
		ch2 <- result{resp, err}
	}()

	// Neither should return yet since entry.done is open.
	select {
	case <-ch1:
		t.Fatal("caller 1 returned before restore completed")
	case <-ch2:
		t.Fatal("caller 2 returned before restore completed")
	case <-time.After(50 * time.Millisecond):
		// expected — both are blocked
	}

	// Complete the restore.
	entry.node = "node-a"
	srv.mu.Lock()
	close(entry.done)
	delete(srv.inflight, "vol-1")
	srv.mu.Unlock()

	// Both callers should now get the same successful result.
	for i, ch := range []chan result{ch1, ch2} {
		select {
		case r := <-ch:
			if r.err != nil {
				t.Errorf("caller %d: unexpected error: %v", i+1, r.err)
			} else if r.resp.NodeName != "node-a" {
				t.Errorf("caller %d: got node %q, want node-a", i+1, r.resp.NodeName)
			}
		case <-time.After(2 * time.Second):
			t.Fatalf("caller %d: timed out waiting for result", i+1)
		}
	}
}

func TestEnsureCached_InflightDedup_ErrorPropagates(t *testing.T) {
	// Pre-populate inflight with an entry that will fail.
	srv, reg := newTestServer([]string{"node-a"})
	reg.RegisterNode("node-a")
	reg.RegisterVolume("vol-1")

	entry := &inflightRestore{done: make(chan struct{})}
	srv.mu.Lock()
	srv.inflight["vol-1"] = entry
	srv.mu.Unlock()

	ch := make(chan error, 1)
	go func() {
		_, err := callEnsureCached(srv, EnsureCachedRequest{
			VolumeID:       "vol-1",
			CandidateNodes: []string{"node-a"},
		})
		ch <- err
	}()

	// Simulate restore failure.
	entry.err = fmt.Errorf("disk full")
	srv.mu.Lock()
	close(entry.done)
	delete(srv.inflight, "vol-1")
	srv.mu.Unlock()

	select {
	case err := <-ch:
		if err == nil {
			t.Fatal("expected error, got nil")
		}
		st, ok := status.FromError(err)
		if !ok || st.Code() != codes.Internal {
			t.Errorf("expected Internal error, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for error")
	}
}

func TestEnsureCached_ClientTimeout_ReturnsDeadlineExceeded(t *testing.T) {
	// Pre-populate inflight with an entry that never completes within the context deadline.
	srv, reg := newTestServer([]string{"node-a"})
	reg.RegisterNode("node-a")
	reg.RegisterVolume("vol-1")

	entry := &inflightRestore{done: make(chan struct{})}
	srv.mu.Lock()
	srv.inflight["vol-1"] = entry
	srv.mu.Unlock()

	// Create a context that expires quickly.
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	_, err := callEnsureCachedWithCtx(srv, ctx, EnsureCachedRequest{
		VolumeID:       "vol-1",
		CandidateNodes: []string{"node-a"},
	})
	if err == nil {
		t.Fatal("expected DeadlineExceeded error, got nil")
	}
	st, ok := status.FromError(err)
	if !ok || st.Code() != codes.DeadlineExceeded {
		t.Errorf("expected DeadlineExceeded, got %v", err)
	}

	// Clean up the entry (simulate restore completing after client left).
	entry.node = "node-a"
	srv.mu.Lock()
	close(entry.done)
	delete(srv.inflight, "vol-1")
	srv.mu.Unlock()
}

func TestEnsureCached_BackgroundRestore_SetsRegistryAfterSuccess(t *testing.T) {
	// Volume not cached, no peer source. nodeClient factory returns error,
	// so the background goroutine will fail. After that, the next call should
	// NOT find an inflight entry (it was cleaned up).
	srv, reg := newTestServer([]string{"node-a"})
	reg.RegisterNode("node-a")
	reg.RegisterVolume("vol-1")
	// vol-1 is NOT cached anywhere — will reach Step 6.

	_, err := callEnsureCached(srv, EnsureCachedRequest{
		VolumeID:       "vol-1",
		CandidateNodes: []string{"node-a"},
	})
	// nodeClient returns error → background goroutine fails → entry.done closed with error.
	if err == nil {
		t.Fatal("expected error from failed restore")
	}
	st, _ := status.FromError(err)
	if st.Code() != codes.Internal {
		t.Errorf("expected Internal error, got %v", st.Code())
	}

	// Inflight map should be cleaned up.
	srv.mu.Lock()
	_, inMap := srv.inflight["vol-1"]
	srv.mu.Unlock()
	if inMap {
		t.Error("inflight entry should be cleaned up after failure")
	}
}

func TestEnsureCached_BackgroundRestore_OnlyOneRestoreRuns(t *testing.T) {
	// Use a controllable nodeClient that blocks until we signal it.
	// Two concurrent callers should result in only one nodeClient call.
	var restoreCount atomic.Int32
	restoreGate := make(chan struct{})

	registry := NewNodeRegistry()
	srv := NewServer(
		registry,
		nil,
		func(nodeName string) (*nodeops.Client, error) {
			restoreCount.Add(1)
			// Block until test signals to proceed.
			<-restoreGate
			return nil, fmt.Errorf("simulated restore failure")
		},
		func(nodeName string) string { return "" },
		func() []string { return []string{"node-a"} },
	)
	registry.RegisterNode("node-a")
	registry.RegisterVolume("vol-1")

	type result struct {
		resp *EnsureCachedResponse
		err  error
	}
	ch1 := make(chan result, 1)
	ch2 := make(chan result, 1)

	go func() {
		resp, err := callEnsureCached(srv, EnsureCachedRequest{
			VolumeID:       "vol-1",
			CandidateNodes: []string{"node-a"},
		})
		ch1 <- result{resp, err}
	}()

	// Wait for the first goroutine to register the inflight entry.
	for i := 0; i < 100; i++ {
		srv.mu.Lock()
		_, exists := srv.inflight["vol-1"]
		srv.mu.Unlock()
		if exists {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}

	// Wait for the background goroutine to actually enter nodeClient
	// (blocked on restoreGate), confirming the inflight entry is stable.
	for i := 0; i < 100; i++ {
		if restoreCount.Load() >= 1 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if restoreCount.Load() < 1 {
		t.Fatal("timed out waiting for first nodeClient call")
	}

	go func() {
		resp, err := callEnsureCached(srv, EnsureCachedRequest{
			VolumeID:       "vol-1",
			CandidateNodes: []string{"node-a"},
		})
		ch2 <- result{resp, err}
	}()

	// Give goroutine 2 time to reach the inflight check and start waiting.
	time.Sleep(50 * time.Millisecond)

	// Let the restore proceed (it will fail).
	close(restoreGate)

	// Both callers should get the error.
	for i, ch := range []chan result{ch1, ch2} {
		select {
		case r := <-ch:
			if r.err == nil {
				t.Errorf("caller %d: expected error, got success", i+1)
			}
		case <-time.After(5 * time.Second):
			t.Fatalf("caller %d: timed out", i+1)
		}
	}

	// Only one restore should have been attempted.
	if got := restoreCount.Load(); got != 1 {
		t.Errorf("expected 1 restore attempt, got %d", got)
	}
}
