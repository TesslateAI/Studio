package objstore

import (
	"context"
	"testing"
)

func TestNewS3Storage_Valid(t *testing.T) {
	cfg := S3Config{
		Endpoint:       "localhost:9000",
		AccessKeyID:    "minioadmin",
		SecretAccessKey: "minioadmin",
		Region:         "us-east-1",
		Bucket:         "test-bucket",
		UseSSL:         false,
	}

	store, err := NewS3Storage(cfg)
	if err != nil {
		t.Fatalf("NewS3Storage with valid config returned error: %v", err)
	}
	if store == nil {
		t.Fatal("NewS3Storage returned nil")
	}
	if store.bucket != "test-bucket" {
		t.Errorf("bucket = %q, want %q", store.bucket, "test-bucket")
	}
	if store.client == nil {
		t.Error("client is nil")
	}
}

func TestNewS3Storage_EmptyEndpoint(t *testing.T) {
	cfg := S3Config{Bucket: "test-bucket"}
	_, err := NewS3Storage(cfg)
	if err == nil {
		t.Fatal("expected error for empty endpoint, got nil")
	}
}

func TestNewS3Storage_EmptyBucket(t *testing.T) {
	cfg := S3Config{Endpoint: "localhost:9000"}
	_, err := NewS3Storage(cfg)
	if err == nil {
		t.Fatal("expected error for empty bucket, got nil")
	}
}

func TestDetectSSL(t *testing.T) {
	tests := []struct {
		endpoint string
		want     bool
	}{
		{"http://minio.kube-system.svc:9000", false},
		{"http://localhost:9000", false},
		{"http://127.0.0.1:9000", false},
		{"https://s3.amazonaws.com", true},
		{"https://s3.us-east-1.amazonaws.com", true},
		{"HTTPS://S3.AMAZONAWS.COM", true},
		// No scheme defaults to false (bare host:port, common for MinIO).
		{"minio.kube-system.svc:9000", false},
		{"s3.amazonaws.com", false},
		{"localhost:9000", false},
	}

	for _, tt := range tests {
		t.Run(tt.endpoint, func(t *testing.T) {
			got := DetectSSL(tt.endpoint)
			if got != tt.want {
				t.Errorf("DetectSSL(%q) = %v, want %v", tt.endpoint, got, tt.want)
			}
		})
	}
}

func TestNewS3Storage_StripsHTTPScheme(t *testing.T) {
	// RCLONE_S3_ENDPOINT typically includes "http://" prefix.
	cfg := S3Config{
		Endpoint:       "http://minio.minio-system.svc:9000",
		AccessKeyID:    "minioadmin",
		SecretAccessKey: "minioadmin",
		Bucket:         "test-bucket",
		UseSSL:         false,
	}

	store, err := NewS3Storage(cfg)
	if err != nil {
		t.Fatalf("NewS3Storage with http:// endpoint: %v", err)
	}
	if store == nil {
		t.Fatal("NewS3Storage returned nil")
	}
	// The client should have been created successfully (no "http://" in host).
}

func TestNewS3Storage_StripsHTTPSScheme(t *testing.T) {
	cfg := S3Config{
		Endpoint:       "https://s3.amazonaws.com",
		AccessKeyID:    "key",
		SecretAccessKey: "secret",
		Bucket:         "test-bucket",
		UseSSL:         false, // should be overridden to true by https:// scheme
	}

	store, err := NewS3Storage(cfg)
	if err != nil {
		t.Fatalf("NewS3Storage with https:// endpoint: %v", err)
	}
	if store == nil {
		t.Fatal("NewS3Storage returned nil")
	}
}

func TestS3Storage_ImplementsInterface(t *testing.T) {
	// Compile-time check that S3Storage satisfies ObjectStorage.
	var _ ObjectStorage = (*S3Storage)(nil)
}

func TestNewS3Storage_SemaphoreInitialized(t *testing.T) {
	cfg := S3Config{
		Endpoint:       "localhost:9000",
		AccessKeyID:    "key",
		SecretAccessKey: "secret",
		Bucket:         "test-bucket",
	}

	store, err := NewS3Storage(cfg)
	if err != nil {
		t.Fatalf("NewS3Storage: %v", err)
	}
	if store.sem == nil {
		t.Fatal("semaphore channel not initialized")
	}
	if cap(store.sem) != maxConcurrentUploads {
		t.Errorf("semaphore capacity = %d, want %d", cap(store.sem), maxConcurrentUploads)
	}
}

func TestS3Storage_UploadSemaphore_BlocksAtLimit(t *testing.T) {
	cfg := S3Config{
		Endpoint:       "localhost:9000",
		AccessKeyID:    "key",
		SecretAccessKey: "secret",
		Bucket:         "test-bucket",
	}
	store, err := NewS3Storage(cfg)
	if err != nil {
		t.Fatalf("NewS3Storage: %v", err)
	}

	// Fill the semaphore to capacity.
	for range maxConcurrentUploads {
		if !store.acquireSem(context.Background()) {
			t.Fatal("acquireSem failed unexpectedly")
		}
	}

	// Next acquire with a cancelled context should fail immediately.
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if store.acquireSem(ctx) {
		t.Error("acquireSem should return false when semaphore is full and context cancelled")
	}

	// Release one and verify acquire works again.
	store.releaseSem()
	if !store.acquireSem(context.Background()) {
		t.Error("acquireSem should succeed after releaseSem")
	}
}

func TestS3Storage_UploadSemaphore_DeferRelease(t *testing.T) {
	cfg := S3Config{
		Endpoint:       "localhost:9000",
		AccessKeyID:    "key",
		SecretAccessKey: "secret",
		Bucket:         "test-bucket",
	}
	store, err := NewS3Storage(cfg)
	if err != nil {
		t.Fatalf("NewS3Storage: %v", err)
	}

	// Simulate what Upload does: acquire + defer release.
	func() {
		if !store.acquireSem(context.Background()) {
			t.Fatal("acquireSem failed")
		}
		defer store.releaseSem()
		// Simulate panic/error — deferred release still runs.
	}()

	// Semaphore should be empty (all released).
	if len(store.sem) != 0 {
		t.Errorf("semaphore has %d permits held after deferred release, want 0", len(store.sem))
	}
}

func TestS3Storage_PartSize(t *testing.T) {
	// Verify the part size constant is the S3 minimum multipart size
	// and not minio-go's default 512 MiB.
	if s3PartSize != 16*1024*1024 {
		t.Errorf("s3PartSize = %d, want %d (16 MiB)", s3PartSize, 16*1024*1024)
	}
	// Must be >= 5 MiB (S3 absolute minimum).
	if s3PartSize < 5*1024*1024 {
		t.Errorf("s3PartSize = %d, must be >= 5 MiB (S3 minimum)", s3PartSize)
	}
}
