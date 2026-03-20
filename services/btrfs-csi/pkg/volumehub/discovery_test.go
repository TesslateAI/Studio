package volumehub

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestParseEndpoints(t *testing.T) {
	r := &NodeResolver{port: 9741}

	ep := &endpointsResponse{
		Subsets: []endpointSubset{
			{
				Addresses: []endpointAddress{
					{IP: "10.0.1.10", NodeName: "node-a"},
					{IP: "10.0.2.20", NodeName: "node-b"},
				},
			},
			{
				Addresses: []endpointAddress{
					{IP: "10.0.3.30", NodeName: "node-c"},
				},
			},
		},
	}

	m := r.parseEndpoints(ep)

	if len(m) != 3 {
		t.Fatalf("got %d entries, want 3", len(m))
	}
	if m["node-a"] != "10.0.1.10:9741" {
		t.Errorf("node-a = %q, want %q", m["node-a"], "10.0.1.10:9741")
	}
	if m["node-b"] != "10.0.2.20:9741" {
		t.Errorf("node-b = %q, want %q", m["node-b"], "10.0.2.20:9741")
	}
	if m["node-c"] != "10.0.3.30:9741" {
		t.Errorf("node-c = %q, want %q", m["node-c"], "10.0.3.30:9741")
	}
}

func TestParseEndpoints_Empty(t *testing.T) {
	r := &NodeResolver{port: 9741}
	m := r.parseEndpoints(&endpointsResponse{})
	if len(m) != 0 {
		t.Fatalf("got %d entries, want 0", len(m))
	}
}

func TestParseEndpoints_SkipsMissingFields(t *testing.T) {
	r := &NodeResolver{port: 9741}

	ep := &endpointsResponse{
		Subsets: []endpointSubset{
			{
				Addresses: []endpointAddress{
					{IP: "10.0.1.10", NodeName: ""},          // missing NodeName
					{IP: "", NodeName: "node-b"},              // missing IP
					{IP: "10.0.3.30", NodeName: "node-c"},    // valid
				},
			},
		},
	}

	m := r.parseEndpoints(ep)
	if len(m) != 1 {
		t.Fatalf("got %d entries, want 1 (only node-c valid)", len(m))
	}
	if m["node-c"] != "10.0.3.30:9741" {
		t.Errorf("node-c = %q", m["node-c"])
	}
}

func TestRefreshReturnsResourceVersion(t *testing.T) {
	ep := endpointsResponse{
		Metadata: endpointsMeta{ResourceVersion: "12345"},
		Subsets: []endpointSubset{
			{
				Addresses: []endpointAddress{
					{IP: "10.0.1.10", NodeName: "node-a"},
				},
			},
		},
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ep)
	}))
	defer srv.Close()

	r := newTestNodeResolver(srv.URL, "test-svc", "test-ns", 9741)

	rv, err := r.Refresh(context.Background())
	if err != nil {
		t.Fatalf("Refresh returned error: %v", err)
	}
	if rv != "12345" {
		t.Errorf("resourceVersion = %q, want %q", rv, "12345")
	}
	if r.Resolve("node-a") != "10.0.1.10:9741" {
		t.Errorf("node-a = %q after Refresh", r.Resolve("node-a"))
	}
}

func TestWatchEventUpdatesMap(t *testing.T) {
	listCalled := atomic.Int32{}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()

		if q.Get("watch") == "true" {
			// Stream a MODIFIED event then close.
			w.Header().Set("Content-Type", "application/json")
			flusher, ok := w.(http.Flusher)
			if !ok {
				http.Error(w, "no flusher", 500)
				return
			}

			event := watchEvent{
				Type: "MODIFIED",
				Object: endpointsResponse{
					Metadata: endpointsMeta{ResourceVersion: "200"},
					Subsets: []endpointSubset{
						{
							Addresses: []endpointAddress{
								{IP: "10.0.9.99", NodeName: "node-updated"},
							},
						},
					},
				},
			}
			json.NewEncoder(w).Encode(event)
			flusher.Flush()
			// Close connection to end the watch.
			return
		}

		// List request.
		listCalled.Add(1)
		ep := endpointsResponse{
			Metadata: endpointsMeta{ResourceVersion: "100"},
			Subsets: []endpointSubset{
				{
					Addresses: []endpointAddress{
						{IP: "10.0.1.10", NodeName: "node-a"},
					},
				},
			},
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ep)
	}))
	defer srv.Close()

	r := newTestNodeResolver(srv.URL, "test-svc", "test-ns", 9741)

	changeCalled := atomic.Int32{}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	r.StartWatch(ctx, func() {
		changeCalled.Add(1)
	})

	// Wait for the watch to process the event.
	deadline := time.After(2 * time.Second)
	for {
		if r.Resolve("node-updated") == "10.0.9.99:9741" {
			break
		}
		select {
		case <-deadline:
			t.Fatal("timed out waiting for watch event to update map")
		case <-time.After(50 * time.Millisecond):
		}
	}

	if r.Resolve("node-updated") != "10.0.9.99:9741" {
		t.Errorf("node-updated = %q, want %q", r.Resolve("node-updated"), "10.0.9.99:9741")
	}
	if changeCalled.Load() < 1 {
		t.Error("onNodeChange was never called")
	}
}

func TestWatchReconnectsOn410(t *testing.T) {
	listCount := atomic.Int32{}
	watchCount := atomic.Int32{}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()

		if q.Get("watch") == "true" {
			wc := watchCount.Add(1)
			w.Header().Set("Content-Type", "application/json")
			flusher, ok := w.(http.Flusher)
			if !ok {
				http.Error(w, "no flusher", 500)
				return
			}

			if wc == 1 {
				// First watch: send 410 Gone error event.
				event := watchEvent{
					Type: "ERROR",
					Object: endpointsResponse{
						Metadata: endpointsMeta{ResourceVersion: ""},
					},
				}
				json.NewEncoder(w).Encode(event)
				flusher.Flush()
				return
			}

			// Second watch: send a valid event then close.
			event := watchEvent{
				Type: "MODIFIED",
				Object: endpointsResponse{
					Metadata: endpointsMeta{ResourceVersion: "300"},
					Subsets: []endpointSubset{
						{
							Addresses: []endpointAddress{
								{IP: "10.0.5.50", NodeName: "node-recovered"},
							},
						},
					},
				},
			}
			json.NewEncoder(w).Encode(event)
			flusher.Flush()
			return
		}

		// List request.
		listCount.Add(1)
		ep := endpointsResponse{
			Metadata: endpointsMeta{ResourceVersion: fmt.Sprintf("%d", 100*listCount.Load())},
			Subsets: []endpointSubset{
				{
					Addresses: []endpointAddress{
						{IP: "10.0.1.10", NodeName: "node-a"},
					},
				},
			},
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ep)
	}))
	defer srv.Close()

	r := newTestNodeResolver(srv.URL, "test-svc", "test-ns", 9741)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	r.StartWatch(ctx, nil)

	// Wait for re-list after 410 → second watch → recovery event.
	deadline := time.After(4 * time.Second)
	for {
		if r.Resolve("node-recovered") == "10.0.5.50:9741" {
			break
		}
		select {
		case <-deadline:
			t.Fatalf("timed out: listCount=%d watchCount=%d", listCount.Load(), watchCount.Load())
		case <-time.After(50 * time.Millisecond):
		}
	}

	// Should have listed at least twice (initial + re-list after 410).
	if listCount.Load() < 2 {
		t.Errorf("listCount = %d, want >= 2 (initial + re-list after 410)", listCount.Load())
	}
	if watchCount.Load() < 2 {
		t.Errorf("watchCount = %d, want >= 2 (first 410 + second success)", watchCount.Load())
	}
}

func TestWatchStopsOnContextCancel(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("watch") == "true" {
			// Block forever — only context cancellation should end this.
			w.Header().Set("Content-Type", "application/json")
			<-r.Context().Done()
			return
		}
		// List request.
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(endpointsResponse{
			Metadata: endpointsMeta{ResourceVersion: "1"},
			Subsets: []endpointSubset{
				{Addresses: []endpointAddress{{IP: "10.0.1.1", NodeName: "node-a"}}},
			},
		})
	}))
	defer srv.Close()

	r := newTestNodeResolver(srv.URL, "test-svc", "test-ns", 9741)

	ctx, cancel := context.WithCancel(context.Background())
	changeCalled := atomic.Int32{}
	r.StartWatch(ctx, func() { changeCalled.Add(1) })

	// Wait for the initial list + watch connection.
	deadline := time.After(2 * time.Second)
	for changeCalled.Load() < 1 {
		select {
		case <-deadline:
			t.Fatal("timed out waiting for initial onNodeChange")
		case <-time.After(50 * time.Millisecond):
		}
	}

	// Cancel context — watch should terminate cleanly.
	cancel()
	time.Sleep(200 * time.Millisecond)

	// Verify the resolver still has the last known state (not cleared).
	if r.Resolve("node-a") != "10.0.1.1:9741" {
		t.Errorf("node-a = %q, expected last known state preserved", r.Resolve("node-a"))
	}
}

func TestLogChanges(t *testing.T) {
	r := &NodeResolver{}

	// Just verify it doesn't panic on various inputs.
	r.logChanges(nil, map[string]string{"a": "1"})
	r.logChanges(map[string]string{"a": "1"}, nil)
	r.logChanges(map[string]string{"a": "1"}, map[string]string{"a": "2"})
	r.logChanges(map[string]string{"a": "1"}, map[string]string{"a": "1", "b": "2"})
}
