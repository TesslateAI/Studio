// Package metrics provides Prometheus metrics for the btrfs CSI driver.
package metrics

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"k8s.io/klog/v2"
)

var (
	// CSI operations.
	VolumeCreateDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: "tesslate_csi",
			Name:      "volume_create_duration_seconds",
			Help:      "Time to create a volume (subvolume snapshot or empty create)",
			Buckets:   []float64{0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5, 10, 30},
		},
		[]string{"source"}, // "template", "snapshot", "empty"
	)

	VolumeDeleteDuration = prometheus.NewHistogram(
		prometheus.HistogramOpts{
			Namespace: "tesslate_csi",
			Name:      "volume_delete_duration_seconds",
			Help:      "Time to delete a volume",
			Buckets:   []float64{0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5},
		},
	)

	SubvolumeCount = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: "tesslate_csi",
			Name:      "subvolume_count",
			Help:      "Number of btrfs subvolumes by type",
		},
		[]string{"type"}, // "volumes", "snapshots", "templates"
	)

	// Sync daemon.
	SyncLag = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: "tesslate_csi",
			Name:      "sync_lag_seconds",
			Help:      "Time since last successful sync per volume",
		},
		[]string{"volume_id"},
	)

	SyncDuration = prometheus.NewHistogram(
		prometheus.HistogramOpts{
			Namespace: "tesslate_csi",
			Name:      "sync_duration_seconds",
			Help:      "Duration of a single sync operation",
			Buckets:   []float64{0.1, 0.5, 1, 2, 5, 10, 30, 60, 120},
		},
	)

	SyncBytesTransferred = prometheus.NewCounter(
		prometheus.CounterOpts{
			Namespace: "tesslate_csi",
			Name:      "sync_bytes_transferred_total",
			Help:      "Total bytes uploaded to object storage",
		},
	)

	SyncFailures = prometheus.NewCounter(
		prometheus.CounterOpts{
			Namespace: "tesslate_csi",
			Name:      "sync_failures_total",
			Help:      "Total number of failed sync operations",
		},
	)

	// FileOps.
	FileOpsRequests = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "tesslate_csi",
			Name:      "fileops_requests_total",
			Help:      "Total FileOps gRPC requests by method",
		},
		[]string{"method"},
	)

	FileOpsDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: "tesslate_csi",
			Name:      "fileops_duration_seconds",
			Help:      "FileOps request latency by method",
			Buckets:   []float64{0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5},
		},
		[]string{"method"},
	)

	FileOpsErrors = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "tesslate_csi",
			Name:      "fileops_errors_total",
			Help:      "Total FileOps errors by method",
		},
		[]string{"method"},
	)

	// Tier transitions.
	TierTransitions = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "tesslate_csi",
			Name:      "tier_transitions_total",
			Help:      "Number of compute tier transitions",
		},
		[]string{"from", "to"}, // e.g., "0" → "1", "1" → "2", "2" → "0"
	)

	// Cross-node restore.
	RestoreDuration = prometheus.NewHistogram(
		prometheus.HistogramOpts{
			Namespace: "tesslate_csi",
			Name:      "restore_duration_seconds",
			Help:      "Time to restore a volume from object storage",
			Buckets:   []float64{1, 5, 10, 30, 60, 120, 300},
		},
	)

	// GC.
	GCOrphansDeleted = prometheus.NewCounter(
		prometheus.CounterOpts{
			Namespace: "tesslate_csi",
			Name:      "gc_orphans_deleted_total",
			Help:      "Total orphaned subvolumes deleted by GC",
		},
	)

	GCS3ObjectsDeleted = prometheus.NewCounter(
		prometheus.CounterOpts{
			Namespace: "tesslate_csi",
			Name:      "gc_s3_objects_deleted_total",
			Help:      "Total orphaned S3 objects deleted by GC",
		},
	)
)

func init() {
	prometheus.MustRegister(
		VolumeCreateDuration,
		VolumeDeleteDuration,
		SubvolumeCount,
		SyncLag,
		SyncDuration,
		SyncBytesTransferred,
		SyncFailures,
		FileOpsRequests,
		FileOpsDuration,
		FileOpsErrors,
		TierTransitions,
		RestoreDuration,
		GCOrphansDeleted,
		GCS3ObjectsDeleted,
	)
}

// StartMetricsServer starts an HTTP server for Prometheus /metrics endpoint.
// Uses TLS if certFile and keyFile are provided, otherwise plaintext
// (suitable for cluster-internal Prometheus scraping with NetworkPolicy).
func StartMetricsServer(addr, certFile, keyFile string) {
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())

	klog.Infof("Metrics server listening on %s", addr)

	if certFile != "" && keyFile != "" {
		if err := http.ListenAndServeTLS(addr, certFile, keyFile, mux); err != nil {
			klog.Errorf("Metrics server (TLS) failed: %v", err)
		}
	} else {
		server := &http.Server{Addr: addr, Handler: mux}
		if err := server.ListenAndServe(); err != nil {
			klog.Errorf("Metrics server failed: %v", err)
		}
	}
}
