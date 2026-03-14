//go:build integration

package integration

import (
	"bytes"
	"context"
	"io"
	"testing"
)

func TestS3_EnsureBucket(t *testing.T) {
	bucket := uniqueName("test-ensure")
	c := newS3Client(t, bucket)
	ctx := context.Background()

	// EnsureBucket was already called by newS3Client; call it again to
	// verify idempotency.
	if err := c.EnsureBucket(ctx, "us-east-1"); err != nil {
		t.Fatalf("second EnsureBucket: %v", err)
	}
}

func TestS3_UploadAndDownload(t *testing.T) {
	bucket := uniqueName("test-updown")
	c := newS3Client(t, bucket)
	ctx := context.Background()

	data := bytes.Repeat([]byte("A"), 1024) // 1KB
	key := "test/file.dat"

	if err := c.Upload(ctx, key, bytes.NewReader(data), int64(len(data))); err != nil {
		t.Fatalf("Upload: %v", err)
	}

	reader, err := c.Download(ctx, key)
	if err != nil {
		t.Fatalf("Download: %v", err)
	}
	defer reader.Close()

	got, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("ReadAll: %v", err)
	}
	if !bytes.Equal(got, data) {
		t.Fatalf("content mismatch: got %d bytes, want %d bytes", len(got), len(data))
	}
}

func TestS3_UploadStreamingUnknownSize(t *testing.T) {
	bucket := uniqueName("test-stream")
	c := newS3Client(t, bucket)
	ctx := context.Background()

	data := []byte("streaming upload with unknown size")
	key := "stream/unknown.dat"

	// size=-1 signals unknown size to the S3 client.
	if err := c.Upload(ctx, key, bytes.NewReader(data), -1); err != nil {
		t.Fatalf("Upload (unknown size): %v", err)
	}

	reader, err := c.Download(ctx, key)
	if err != nil {
		t.Fatalf("Download: %v", err)
	}
	defer reader.Close()

	got, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("ReadAll: %v", err)
	}
	if !bytes.Equal(got, data) {
		t.Fatalf("content mismatch: got %q, want %q", got, data)
	}
}

func TestS3_Exists_True(t *testing.T) {
	bucket := uniqueName("test-exists-t")
	c := newS3Client(t, bucket)
	ctx := context.Background()

	key := "exists/yes.txt"
	data := []byte("present")
	if err := c.Upload(ctx, key, bytes.NewReader(data), int64(len(data))); err != nil {
		t.Fatalf("Upload: %v", err)
	}

	exists, err := c.Exists(ctx, key)
	if err != nil {
		t.Fatalf("Exists: %v", err)
	}
	if !exists {
		t.Fatal("Exists returned false for uploaded object")
	}
}

func TestS3_Exists_False(t *testing.T) {
	bucket := uniqueName("test-exists-f")
	c := newS3Client(t, bucket)
	ctx := context.Background()

	exists, err := c.Exists(ctx, "no/such/key.txt")
	if err != nil {
		t.Fatalf("Exists: %v", err)
	}
	if exists {
		t.Fatal("Exists returned true for missing object")
	}
}

func TestS3_Delete(t *testing.T) {
	bucket := uniqueName("test-delete")
	c := newS3Client(t, bucket)
	ctx := context.Background()

	key := "delete/me.txt"
	data := []byte("to be deleted")
	if err := c.Upload(ctx, key, bytes.NewReader(data), int64(len(data))); err != nil {
		t.Fatalf("Upload: %v", err)
	}

	if err := c.Delete(ctx, key); err != nil {
		t.Fatalf("Delete: %v", err)
	}

	exists, err := c.Exists(ctx, key)
	if err != nil {
		t.Fatalf("Exists after delete: %v", err)
	}
	if exists {
		t.Fatal("object still exists after Delete")
	}
}

func TestS3_Delete_NonExistent(t *testing.T) {
	bucket := uniqueName("test-delnone")
	c := newS3Client(t, bucket)
	ctx := context.Background()

	// Deleting a non-existent key should not return an error.
	if err := c.Delete(ctx, "nonexistent/key.txt"); err != nil {
		t.Fatalf("Delete non-existent: %v", err)
	}
}

func TestS3_List(t *testing.T) {
	bucket := uniqueName("test-list")
	c := newS3Client(t, bucket)
	ctx := context.Background()

	// Upload 5 objects under the "data/" prefix.
	keys := []string{
		"data/file1.txt",
		"data/file2.txt",
		"data/file3.txt",
		"data/file4.txt",
		"data/file5.txt",
	}
	for _, key := range keys {
		payload := []byte("content-" + key)
		if err := c.Upload(ctx, key, bytes.NewReader(payload), int64(len(payload))); err != nil {
			t.Fatalf("Upload %s: %v", key, err)
		}
	}

	objects, err := c.List(ctx, "data/")
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(objects) != 5 {
		t.Fatalf("List returned %d objects, want 5", len(objects))
	}

	found := make(map[string]bool)
	for _, obj := range objects {
		found[obj.Key] = true
	}
	for _, key := range keys {
		if !found[key] {
			t.Errorf("missing key %q in listing", key)
		}
	}
}

func TestS3_List_EmptyPrefix(t *testing.T) {
	bucket := uniqueName("test-listempty")
	c := newS3Client(t, bucket)
	ctx := context.Background()

	// Fresh bucket with no objects -- List should return 0 results.
	objects, err := c.List(ctx, "")
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(objects) != 0 {
		t.Fatalf("List on empty bucket returned %d objects, want 0", len(objects))
	}
}

func TestS3_LargeObject(t *testing.T) {
	bucket := uniqueName("test-large")
	c := newS3Client(t, bucket)
	ctx := context.Background()

	// 10 MB object.
	size := 10 * 1024 * 1024
	data := bytes.Repeat([]byte("X"), size)
	key := "large/10mb.bin"

	if err := c.Upload(ctx, key, bytes.NewReader(data), int64(len(data))); err != nil {
		t.Fatalf("Upload 10MB: %v", err)
	}

	reader, err := c.Download(ctx, key)
	if err != nil {
		t.Fatalf("Download 10MB: %v", err)
	}
	defer reader.Close()

	got, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("ReadAll: %v", err)
	}
	if len(got) != size {
		t.Fatalf("downloaded size = %d, want %d", len(got), size)
	}
	if !bytes.Equal(got, data) {
		// Find the first differing byte for a useful error message.
		for i := range got {
			if got[i] != data[i] {
				t.Fatalf("content mismatch at byte %d: got 0x%02x, want 0x%02x", i, got[i], data[i])
			}
		}
	}
}
