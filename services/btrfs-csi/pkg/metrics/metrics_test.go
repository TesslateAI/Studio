package metrics

import (
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// TestMetricsRecording verifies that every exported metric can be recorded
// without panicking. Since metrics are registered in init(), they are already
// available by the time tests run.
func TestMetricsRecording(t *testing.T) {
	// Histograms (vec) — VolumeCreateDuration
	VolumeCreateDuration.WithLabelValues("template").Observe(0.5)
	VolumeCreateDuration.WithLabelValues("snapshot").Observe(1.0)
	VolumeCreateDuration.WithLabelValues("empty").Observe(0.01)

	// Histograms (plain)
	VolumeDeleteDuration.Observe(0.1)
	SyncDuration.Observe(2.5)
	RestoreDuration.Observe(15.0)

	// Gauges (vec) — SubvolumeCount
	SubvolumeCount.WithLabelValues("volumes").Set(10)
	SubvolumeCount.WithLabelValues("snapshots").Set(5)
	SubvolumeCount.WithLabelValues("templates").Set(3)

	// Gauges (vec) — SyncLag
	SyncLag.WithLabelValues("vol-1").Set(30.5)

	// Counters (plain)
	SyncBytesTransferred.Add(1024)
	SyncFailures.Inc()
	GCOrphansDeleted.Inc()
	GCS3ObjectsDeleted.Inc()

	// Counters (vec)
	FileOpsRequests.WithLabelValues("ReadFile").Inc()
	FileOpsErrors.WithLabelValues("ReadFile").Inc()
	TierTransitions.WithLabelValues("0", "1").Inc()

	// Histograms (vec) — FileOpsDuration
	FileOpsDuration.WithLabelValues("WriteFile").Observe(0.05)
}

// TestMetricsServer_Responds verifies that the Prometheus handler serves a
// valid /metrics page containing our custom namespace "tesslate_csi".
func TestMetricsServer_Responds(t *testing.T) {
	// Record at least one metric so it appears in the output.
	VolumeCreateDuration.WithLabelValues("template").Observe(0.1)

	handler := promhttp.Handler()
	req := httptest.NewRequest("GET", "/metrics", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("expected status 200, got %d", w.Code)
	}

	body := w.Body.String()
	if !strings.Contains(body, "tesslate_csi") {
		t.Fatalf("expected metrics body to contain 'tesslate_csi', got:\n%s", body)
	}
}

// TestMetricsHandler_ContentType verifies the Prometheus handler returns a
// content-type header suitable for Prometheus scraping (text/plain or
// application/openmetrics-text).
func TestMetricsHandler_ContentType(t *testing.T) {
	handler := promhttp.Handler()
	req := httptest.NewRequest("GET", "/metrics", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	ct := w.Header().Get("Content-Type")
	if ct == "" {
		t.Fatal("Content-Type header is empty")
	}

	// The Prometheus client library returns either:
	//   text/plain; version=0.0.4; charset=utf-8
	//   application/openmetrics-text; version=1.0.0; charset=utf-8
	// depending on the client's Accept header negotiation.
	validTypes := []string{"text/plain", "application/openmetrics-text"}
	found := false
	for _, vt := range validTypes {
		if strings.Contains(ct, vt) {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("unexpected Content-Type: %s; expected one containing 'text/plain' or 'application/openmetrics-text'", ct)
	}
}
