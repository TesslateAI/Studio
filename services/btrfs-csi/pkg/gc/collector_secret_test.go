// Tests for the X-Internal-Secret authentication path in the GC collector.
// Specifically: fetchKnownVolumes sends the header when a secret is set,
// SetOrchestratorURL wires the closure correctly, and the endpoint contract
// is honoured (200+JSON on success, non-200 → error).
package gc

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
)

// TestFetchKnownVolumes_SendsSecretHeader verifies that the X-Internal-Secret
// header is set when a non-empty secret is provided.
func TestFetchKnownVolumes_SendsSecretHeader(t *testing.T) {
	const wantSecret = "test-secret-abc"
	var gotSecret string

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotSecret = r.Header.Get("X-Internal-Secret")
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string][]string{ //nolint:errcheck
			"volume_ids": {"vol-1", "vol-2"},
		})
	}))
	defer ts.Close()

	vols, err := fetchKnownVolumes(context.Background(), ts.URL, wantSecret)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if gotSecret != wantSecret {
		t.Errorf("X-Internal-Secret: got %q, want %q", gotSecret, wantSecret)
	}
	if !vols["vol-1"] || !vols["vol-2"] {
		t.Errorf("expected vol-1 and vol-2 in result, got %v", vols)
	}
}

// TestFetchKnownVolumes_OmitsHeaderWhenEmpty confirms the header is NOT sent
// when the secret is an empty string (unauthenticated / minikube scenario).
func TestFetchKnownVolumes_OmitsHeaderWhenEmpty(t *testing.T) {
	var headerPresent bool

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, headerPresent = r.Header["X-Internal-Secret"]
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string][]string{"volume_ids": {}}) //nolint:errcheck
	}))
	defer ts.Close()

	_, err := fetchKnownVolumes(context.Background(), ts.URL, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if headerPresent {
		t.Error("X-Internal-Secret header should NOT be present when secret is empty")
	}
}

// TestFetchKnownVolumes_Non200ReturnsError ensures a non-200 response is
// surfaced as an error rather than silently returning an empty map.
func TestFetchKnownVolumes_Non200ReturnsError(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "Forbidden", http.StatusForbidden)
	}))
	defer ts.Close()

	_, err := fetchKnownVolumes(context.Background(), ts.URL, "bad-secret")
	if err == nil {
		t.Fatal("expected error for 403 response, got nil")
	}
}

// TestFetchKnownVolumes_ReturnsCorrectMap checks that the volume IDs parsed
// from the JSON response are keyed correctly in the returned map.
func TestFetchKnownVolumes_ReturnsCorrectMap(t *testing.T) {
	want := []string{"vol-aaa", "vol-bbb", "vol-ccc"}

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string][]string{"volume_ids": want}) //nolint:errcheck
	}))
	defer ts.Close()

	got, err := fetchKnownVolumes(context.Background(), ts.URL, "secret")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != len(want) {
		t.Fatalf("expected %d volumes, got %d", len(want), len(got))
	}
	for _, id := range want {
		if !got[id] {
			t.Errorf("expected volume %q in result map", id)
		}
	}
}

// TestSetOrchestratorURL_WiresClosureWithSecret confirms that calling
// SetOrchestratorURL stores the secret so subsequent knownVolumes() calls
// include it in the header.
func TestSetOrchestratorURL_WiresClosureWithSecret(t *testing.T) {
	const wantSecret = "closure-secret-xyz"
	var gotSecret string

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotSecret = r.Header.Get("X-Internal-Secret")
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string][]string{"volume_ids": {}}) //nolint:errcheck
	}))
	defer ts.Close()

	c := newSecretTestCollector(t)
	c.SetOrchestratorURL(ts.URL, wantSecret)

	if c.knownVolumes == nil {
		t.Fatal("expected knownVolumes to be set after SetOrchestratorURL")
	}

	_, err := c.knownVolumes(context.Background())
	if err != nil {
		t.Fatalf("unexpected error from knownVolumes: %v", err)
	}
	if gotSecret != wantSecret {
		t.Errorf("X-Internal-Secret via closure: got %q, want %q", gotSecret, wantSecret)
	}
}

// TestSetOrchestratorURL_EmptySecretNoHeader confirms that an empty secret
// wired through SetOrchestratorURL results in no header being sent.
func TestSetOrchestratorURL_EmptySecretNoHeader(t *testing.T) {
	var headerPresent bool

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, headerPresent = r.Header["X-Internal-Secret"]
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string][]string{"volume_ids": {}}) //nolint:errcheck
	}))
	defer ts.Close()

	c := newSecretTestCollector(t)
	c.SetOrchestratorURL(ts.URL, "")

	_, err := c.knownVolumes(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if headerPresent {
		t.Error("X-Internal-Secret should NOT be present when secret is empty string")
	}
}

// TestFetchKnownVolumes_ServerUnreachable verifies that a connection-refused
// error is returned cleanly (no panic, no hang).
func TestFetchKnownVolumes_ServerUnreachable(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	addr := ts.URL
	ts.Close() // Close immediately so the address is no longer listening.

	_, err := fetchKnownVolumes(context.Background(), addr, "secret")
	if err == nil {
		t.Fatal("expected error for unreachable server, got nil")
	}
}

// newSecretTestCollector builds a minimal Collector for secret-header unit tests.
func newSecretTestCollector(t *testing.T) *Collector {
	t.Helper()
	mgr := btrfs.NewManager("/pool")
	return NewCollector(mgr, nil, Config{})
}
