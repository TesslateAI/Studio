package objstore

import (
	"testing"
	"time"
)

func TestNewRcloneStorage_Valid(t *testing.T) {
	env := map[string]string{
		"RCLONE_S3_ACCESS_KEY_ID":     "minioadmin",
		"RCLONE_S3_SECRET_ACCESS_KEY": "minioadmin",
		"RCLONE_S3_ENDPOINT":          "http://localhost:9000",
	}

	store, err := NewRcloneStorage("s3", "test-bucket", env)
	if err != nil {
		t.Fatalf("NewRcloneStorage with valid config returned error: %v", err)
	}
	if store == nil {
		t.Fatal("NewRcloneStorage returned nil")
	}
	if store.provider != "s3" {
		t.Errorf("provider = %q, want %q", store.provider, "s3")
	}
	if store.bucket != "test-bucket" {
		t.Errorf("bucket = %q, want %q", store.bucket, "test-bucket")
	}
	if len(store.env) == 0 {
		t.Error("env slice is empty, expected inherited + overlay vars")
	}

	// Verify overlay vars are present in env.
	found := 0
	for _, e := range store.env {
		if e == "RCLONE_S3_ACCESS_KEY_ID=minioadmin" ||
			e == "RCLONE_S3_SECRET_ACCESS_KEY=minioadmin" ||
			e == "RCLONE_S3_ENDPOINT=http://localhost:9000" {
			found++
		}
	}
	if found != 3 {
		t.Errorf("expected 3 overlay env vars present, found %d", found)
	}
}

func TestNewRcloneStorage_EmptyProvider(t *testing.T) {
	_, err := NewRcloneStorage("", "bucket", nil)
	if err == nil {
		t.Fatal("expected error for empty provider, got nil")
	}
}

func TestNewRcloneStorage_EmptyBucket(t *testing.T) {
	_, err := NewRcloneStorage("s3", "", nil)
	if err == nil {
		t.Fatal("expected error for empty bucket, got nil")
	}
}

func TestRemotePath(t *testing.T) {
	store := &RcloneStorage{provider: "s3", bucket: "my-bucket"}

	got := store.remotePath("snapshots/abc/full.zst")
	want := ":s3:my-bucket/snapshots/abc/full.zst"
	if got != want {
		t.Errorf("remotePath = %q, want %q", got, want)
	}
}

func TestRemotePath_EmptyKey(t *testing.T) {
	store := &RcloneStorage{provider: "gcs", bucket: "my-bucket"}

	got := store.remotePath("")
	want := ":gcs:my-bucket"
	if got != want {
		t.Errorf("remotePath (empty key) = %q, want %q", got, want)
	}
}

func TestRemotePath_NestedKey(t *testing.T) {
	store := &RcloneStorage{provider: "azureblob", bucket: "data"}

	got := store.remotePath("a/b/c")
	want := ":azureblob:data/a/b/c"
	if got != want {
		t.Errorf("remotePath (nested) = %q, want %q", got, want)
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

	// Verify zero value.
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

func TestParseLsjsonOutput(t *testing.T) {
	tests := []struct {
		name       string
		data       string
		prefix     string
		wantCount  int
		wantKeys   []string
		wantSizes  []int64
		wantErr    bool
	}{
		{
			name:      "empty output",
			data:      "",
			prefix:    "volumes/",
			wantCount: 0,
		},
		{
			name:      "empty array",
			data:      "[]",
			prefix:    "volumes/",
			wantCount: 0,
		},
		{
			name: "single file",
			data: `[{
				"Path": "full-20240101.zst",
				"Name": "full-20240101.zst",
				"Size": 1048576,
				"ModTime": "2024-01-01T00:00:00.000000000Z",
				"IsDir": false
			}]`,
			prefix:    "volumes/abc",
			wantCount: 1,
			wantKeys:  []string{"volumes/abc/full-20240101.zst"},
			wantSizes: []int64{1048576},
		},
		{
			name: "multiple files with directory filtered out",
			data: `[
				{
					"Path": "full-20240101.zst",
					"Name": "full-20240101.zst",
					"Size": 1048576,
					"ModTime": "2024-01-01T00:00:00.000000000Z",
					"IsDir": false
				},
				{
					"Path": "subdir",
					"Name": "subdir",
					"Size": 0,
					"ModTime": "2024-01-02T00:00:00.000000000Z",
					"IsDir": true
				},
				{
					"Path": "incr-20240102.zst",
					"Name": "incr-20240102.zst",
					"Size": 524288,
					"ModTime": "2024-01-02T12:00:00.000000000Z",
					"IsDir": false
				}
			]`,
			prefix:    "volumes/abc/",
			wantCount: 2,
			wantKeys:  []string{"volumes/abc/full-20240101.zst", "volumes/abc/incr-20240102.zst"},
			wantSizes: []int64{1048576, 524288},
		},
		{
			name: "no prefix",
			data: `[{
				"Path": "file.txt",
				"Name": "file.txt",
				"Size": 100,
				"ModTime": "2024-06-15T10:30:00.000000000Z",
				"IsDir": false
			}]`,
			prefix:    "",
			wantCount: 1,
			wantKeys:  []string{"file.txt"},
			wantSizes: []int64{100},
		},
		{
			name:    "invalid json",
			data:    `{not valid json`,
			prefix:  "",
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			results, err := parseLsjsonOutput([]byte(tt.data), tt.prefix)
			if tt.wantErr {
				if err == nil {
					t.Fatal("expected error, got nil")
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if len(results) != tt.wantCount {
				t.Fatalf("got %d results, want %d", len(results), tt.wantCount)
			}

			for i, wantKey := range tt.wantKeys {
				if results[i].Key != wantKey {
					t.Errorf("results[%d].Key = %q, want %q", i, results[i].Key, wantKey)
				}
			}
			for i, wantSize := range tt.wantSizes {
				if results[i].Size != wantSize {
					t.Errorf("results[%d].Size = %d, want %d", i, results[i].Size, wantSize)
				}
			}
		})
	}
}

func TestParseLsjsonOutput_ModTime(t *testing.T) {
	data := `[{
		"Path": "test.zst",
		"Name": "test.zst",
		"Size": 42,
		"ModTime": "2024-06-15T10:30:00.000000000Z",
		"IsDir": false
	}]`

	results, err := parseLsjsonOutput([]byte(data), "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(results))
	}

	expected := time.Date(2024, 6, 15, 10, 30, 0, 0, time.UTC)
	if !results[0].LastModified.Equal(expected) {
		t.Errorf("LastModified = %v, want %v", results[0].LastModified, expected)
	}
}
