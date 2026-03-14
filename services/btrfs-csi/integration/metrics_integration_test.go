//go:build integration

package integration

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/metrics"
)

var (
	metricsOnce sync.Once
	metricsAddr string
)

// ensureMetricsServer starts the Prometheus metrics HTTP server exactly once
// across all tests in this file. Because metrics.init() registers collectors
// globally, we must share a single server instance.
func ensureMetricsServer(t *testing.T) string {
	t.Helper()
	metricsOnce.Do(func() {
		lis, err := net.Listen("tcp", "localhost:0")
		if err != nil {
			t.Fatalf("find free port: %v", err)
		}
		metricsAddr = lis.Addr().String()
		lis.Close()
		go metrics.StartMetricsServer(metricsAddr, "", "")
		// Allow the server goroutine to bind the port.
		time.Sleep(100 * time.Millisecond)
	})
	return metricsAddr
}

// scrapeMetrics performs a GET /metrics against the shared server and returns
// the response body as a string.
func scrapeMetrics(t *testing.T, addr string) string {
	t.Helper()
	resp, err := http.Get(fmt.Sprintf("http://%s/metrics", addr))
	if err != nil {
		t.Fatalf("GET /metrics: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("GET /metrics status %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	return string(body)
}

// --------------------------------------------------------------------------
// Server starts and serves /metrics
// --------------------------------------------------------------------------

func TestMetrics_ServerStartsAndServes(t *testing.T) {
	addr := ensureMetricsServer(t)

	body := scrapeMetrics(t, addr)

	if !strings.Contains(body, "tesslate_csi") {
		t.Fatalf("expected /metrics body to contain 'tesslate_csi', got:\n%s", body)
	}
}

// --------------------------------------------------------------------------
// VolumeCreateDuration histogram
// --------------------------------------------------------------------------

func TestMetrics_VolumeCreateDuration(t *testing.T) {
	addr := ensureMetricsServer(t)

	metrics.VolumeCreateDuration.WithLabelValues("template").Observe(0.042)

	body := scrapeMetrics(t, addr)

	if !strings.Contains(body, "tesslate_csi_volume_create_duration_seconds") {
		t.Fatalf("expected volume_create_duration_seconds metric in output:\n%s", body)
	}
}

// --------------------------------------------------------------------------
// Sync metrics (bytes transferred + failures)
// --------------------------------------------------------------------------

func TestMetrics_SyncMetrics(t *testing.T) {
	addr := ensureMetricsServer(t)

	metrics.SyncBytesTransferred.Add(12345)
	metrics.SyncFailures.Inc()

	body := scrapeMetrics(t, addr)

	if !strings.Contains(body, "tesslate_csi_sync_bytes_transferred_total") {
		t.Fatalf("expected sync_bytes_transferred_total metric in output:\n%s", body)
	}
	if !strings.Contains(body, "tesslate_csi_sync_failures_total") {
		t.Fatalf("expected sync_failures_total metric in output:\n%s", body)
	}
}

// --------------------------------------------------------------------------
// Metrics after real btrfs operations
// --------------------------------------------------------------------------

func TestMetrics_AfterRealOperations(t *testing.T) {
	addr := ensureMetricsServer(t)
	mgr := newBtrfsManager(t)
	ctx := context.Background()

	volName := "volumes/" + uniqueName("metrics-real")

	start := time.Now()
	if err := mgr.CreateSubvolume(ctx, volName); err != nil {
		t.Fatalf("CreateSubvolume: %v", err)
	}
	duration := time.Since(start)

	// Record the real duration in the Prometheus metric.
	metrics.VolumeCreateDuration.WithLabelValues("empty").Observe(duration.Seconds())

	// Clean up the subvolume.
	if err := mgr.DeleteSubvolume(ctx, volName); err != nil {
		t.Fatalf("DeleteSubvolume: %v", err)
	}

	body := scrapeMetrics(t, addr)

	if !strings.Contains(body, "tesslate_csi_volume_create_duration_seconds") {
		t.Fatalf("expected volume_create_duration_seconds metric after real operation:\n%s", body)
	}
	// Verify the "empty" label bucket received our observation.
	if !strings.Contains(body, `source="empty"`) {
		t.Fatalf("expected source=\"empty\" label in metrics output:\n%s", body)
	}
}
