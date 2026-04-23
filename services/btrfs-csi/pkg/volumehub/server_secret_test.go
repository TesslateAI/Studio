// Tests for the X-Internal-Secret header path in VolumeHub's
// notifyOrchestrator and SetOrchestratorURL methods.
package volumehub

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

// TestSetOrchestratorURL_StoresURLAndSecret confirms that SetOrchestratorURL
// persists both the URL and secret on the Server struct.
func TestSetOrchestratorURL_StoresURLAndSecret(t *testing.T) {
	s := &Server{inflight: make(map[string]*inflightRestore)}
	s.SetOrchestratorURL("http://tesslate-backend:8000", "my-secret")

	if s.orchestratorURL != "http://tesslate-backend:8000" {
		t.Errorf("orchestratorURL: got %q, want %q", s.orchestratorURL, "http://tesslate-backend:8000")
	}
	if s.orchestratorSecret != "my-secret" {
		t.Errorf("orchestratorSecret: got %q, want %q", s.orchestratorSecret, "my-secret")
	}
}

// TestNotifyOrchestrator_SendsSecretHeader verifies that notifyOrchestrator
// includes the X-Internal-Secret header when a secret is configured.
func TestNotifyOrchestrator_SendsSecretHeader(t *testing.T) {
	const wantSecret = "notify-secret-xyz"
	var (
		mu         sync.Mutex
		gotSecret  string
		gotPayload map[string]string
	)

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		gotSecret = r.Header.Get("X-Internal-Secret")
		json.NewDecoder(r.Body).Decode(&gotPayload) //nolint:errcheck
		w.WriteHeader(http.StatusOK)
	}))
	defer ts.Close()

	s := &Server{
		orchestratorURL:    ts.URL,
		orchestratorSecret: wantSecret,
		inflight:           make(map[string]*inflightRestore),
	}

	s.notifyOrchestrator("vol-abc", "ready")

	// notifyOrchestrator is fire-and-forget (goroutine). Poll briefly.
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		mu.Lock()
		done := gotSecret != ""
		mu.Unlock()
		if done {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}

	mu.Lock()
	defer mu.Unlock()

	if gotSecret != wantSecret {
		t.Errorf("X-Internal-Secret: got %q, want %q", gotSecret, wantSecret)
	}
	if gotPayload["volume_id"] != "vol-abc" {
		t.Errorf("volume_id: got %q, want %q", gotPayload["volume_id"], "vol-abc")
	}
	if gotPayload["event"] != "ready" {
		t.Errorf("event: got %q, want %q", gotPayload["event"], "ready")
	}
}

// TestNotifyOrchestrator_OmitsHeaderWhenSecretEmpty confirms no header is sent
// when the secret field is empty (minikube / development scenario).
func TestNotifyOrchestrator_OmitsHeaderWhenSecretEmpty(t *testing.T) {
	var (
		mu          sync.Mutex
		headerSeen  bool
		requestSeen bool
	)

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		requestSeen = true
		_, headerSeen = r.Header["X-Internal-Secret"]
		w.WriteHeader(http.StatusOK)
	}))
	defer ts.Close()

	s := &Server{
		orchestratorURL:    ts.URL,
		orchestratorSecret: "", // no secret
		inflight:           make(map[string]*inflightRestore),
	}

	s.notifyOrchestrator("vol-def", "deleted")

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		mu.Lock()
		done := requestSeen
		mu.Unlock()
		if done {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}

	mu.Lock()
	defer mu.Unlock()

	if !requestSeen {
		t.Fatal("notifyOrchestrator did not call the server within 2s")
	}
	if headerSeen {
		t.Error("X-Internal-Secret header should NOT be present when secret is empty")
	}
}

// TestNotifyOrchestrator_NoopWhenURLEmpty confirms that notifyOrchestrator is
// a no-op (no goroutine, no panic) when orchestratorURL is not configured.
func TestNotifyOrchestrator_NoopWhenURLEmpty(t *testing.T) {
	s := &Server{inflight: make(map[string]*inflightRestore)}
	// Should return immediately without spawning a goroutine or panicking.
	s.notifyOrchestrator("vol-noop", "ready")
	// Give a moment in case a goroutine was incorrectly spawned.
	time.Sleep(50 * time.Millisecond)
}
