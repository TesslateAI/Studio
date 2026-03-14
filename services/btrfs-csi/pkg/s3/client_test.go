package s3

import (
	"testing"
	"time"
)

func TestNewClient_ValidConfig(t *testing.T) {
	// Use a valid-looking endpoint. The minio SDK validates endpoint format
	// at construction time but does not connect until an operation is performed.
	client, err := NewClient(
		"localhost:9000",
		"minioadmin",
		"minioadmin",
		"test-bucket",
		"us-east-1",
		false,
	)
	if err != nil {
		t.Fatalf("NewClient with valid config returned error: %v", err)
	}
	if client == nil {
		t.Fatal("NewClient returned nil client")
	}
	if client.bucket != "test-bucket" {
		t.Errorf("bucket = %q, want %q", client.bucket, "test-bucket")
	}
	if client.mc == nil {
		t.Error("internal minio client is nil")
	}
}

func TestNewClient_WithSSL(t *testing.T) {
	client, err := NewClient(
		"s3.amazonaws.com",
		"access-key",
		"secret-key",
		"my-bucket",
		"us-west-2",
		true,
	)
	if err != nil {
		t.Fatalf("NewClient with SSL returned error: %v", err)
	}
	if client == nil {
		t.Fatal("NewClient returned nil client")
	}
	if client.bucket != "my-bucket" {
		t.Errorf("bucket = %q, want %q", client.bucket, "my-bucket")
	}
}

func TestNewClient_InvalidEndpoint(t *testing.T) {
	// The minio SDK may or may not return an error for certain invalid
	// endpoints. We test that the function does not panic and returns
	// a consistent result.
	tests := []struct {
		name     string
		endpoint string
	}{
		{
			name:     "empty endpoint",
			endpoint: "",
		},
		{
			name:     "endpoint with scheme",
			endpoint: "http://localhost:9000",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			client, err := NewClient(
				tt.endpoint,
				"access",
				"secret",
				"bucket",
				"us-east-1",
				false,
			)
			// The minio SDK returns an error for empty endpoints and
			// endpoints that include a scheme. Verify we don't panic
			// and that a nil client means an error was returned.
			if client == nil && err == nil {
				t.Error("nil client returned without error")
			}
			if client != nil && err != nil {
				t.Error("non-nil client returned with error")
			}
		})
	}
}

func TestObjectInfo(t *testing.T) {
	now := time.Now()
	info := ObjectInfo{
		Key:          "volumes/abc/full-20240101.zst",
		Size:         1048576,
		LastModified: now,
	}

	if info.Key != "volumes/abc/full-20240101.zst" {
		t.Errorf("Key = %q, want %q", info.Key, "volumes/abc/full-20240101.zst")
	}
	if info.Size != 1048576 {
		t.Errorf("Size = %d, want %d", info.Size, 1048576)
	}
	if !info.LastModified.Equal(now) {
		t.Errorf("LastModified = %v, want %v", info.LastModified, now)
	}

	// Verify zero value
	var zero ObjectInfo
	if zero.Key != "" {
		t.Errorf("zero ObjectInfo Key = %q, want empty", zero.Key)
	}
	if zero.Size != 0 {
		t.Errorf("zero ObjectInfo Size = %d, want 0", zero.Size)
	}
	if !zero.LastModified.IsZero() {
		t.Errorf("zero ObjectInfo LastModified should be zero time")
	}
}
