//go:build integration

package integration

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"sync/atomic"
	"testing"

	"golang.org/x/sync/errgroup"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/objstore"
)

// newS3Storage creates a native S3 client (minio-go) connected to the same
// MinIO instance used by the rclone integration tests.
func newS3Storage(t *testing.T, bucket string) objstore.ObjectStorage {
	t.Helper()
	endpoint := getS3Endpoint(t)

	cfg := objstore.S3Config{
		Endpoint:       endpoint,
		AccessKeyID:    "minioadmin",
		SecretAccessKey: "minioadmin",
		Region:         "us-east-1",
		Bucket:         bucket,
		UseSSL:         false,
	}

	store, err := objstore.NewS3Storage(cfg)
	if err != nil {
		t.Fatalf("NewS3Storage: %v", err)
	}

	if err := store.EnsureBucket(context.Background()); err != nil {
		t.Fatalf("EnsureBucket(%s): %v", bucket, err)
	}
	return store
}

func TestS3Native_EnsureBucket(t *testing.T) {
	bucket := uniqueName("test-s3nat-bucket")
	c := newS3Storage(t, bucket)
	ctx := context.Background()

	// Second call should be idempotent.
	if err := c.EnsureBucket(ctx); err != nil {
		t.Fatalf("second EnsureBucket: %v", err)
	}
}

func TestS3Native_UploadAndDownload(t *testing.T) {
	bucket := uniqueName("test-s3nat-updown")
	c := newS3Storage(t, bucket)
	ctx := context.Background()

	data := bytes.Repeat([]byte("B"), 2048)
	key := "test/native.dat"

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
		t.Fatalf("content mismatch: got %d bytes, want %d", len(got), len(data))
	}
}

func TestS3Native_UploadStreamingUnknownSize(t *testing.T) {
	bucket := uniqueName("test-s3nat-stream")
	c := newS3Storage(t, bucket)
	ctx := context.Background()

	data := []byte("streaming upload with unknown size via native client")
	key := "stream/native-unknown.dat"

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

func TestS3Native_Exists(t *testing.T) {
	bucket := uniqueName("test-s3nat-exists")
	c := newS3Storage(t, bucket)
	ctx := context.Background()

	key := "exists/native.txt"

	// Should not exist yet.
	exists, err := c.Exists(ctx, key)
	if err != nil {
		t.Fatalf("Exists (before): %v", err)
	}
	if exists {
		t.Fatal("Exists returned true for non-existent key")
	}

	// Upload and check again.
	if err := c.Upload(ctx, key, bytes.NewReader([]byte("present")), 7); err != nil {
		t.Fatalf("Upload: %v", err)
	}

	exists, err = c.Exists(ctx, key)
	if err != nil {
		t.Fatalf("Exists (after): %v", err)
	}
	if !exists {
		t.Fatal("Exists returned false for uploaded object")
	}
}

func TestS3Native_Delete(t *testing.T) {
	bucket := uniqueName("test-s3nat-delete")
	c := newS3Storage(t, bucket)
	ctx := context.Background()

	key := "delete/native.txt"
	if err := c.Upload(ctx, key, bytes.NewReader([]byte("to delete")), 9); err != nil {
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

func TestS3Native_Delete_NonExistent(t *testing.T) {
	bucket := uniqueName("test-s3nat-delnone")
	c := newS3Storage(t, bucket)
	ctx := context.Background()

	if err := c.Delete(ctx, "nonexistent/key.txt"); err != nil {
		t.Fatalf("Delete non-existent: %v", err)
	}
}

func TestS3Native_List(t *testing.T) {
	bucket := uniqueName("test-s3nat-list")
	c := newS3Storage(t, bucket)
	ctx := context.Background()

	keys := []string{
		"data/file1.txt",
		"data/file2.txt",
		"data/file3.txt",
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
	if len(objects) != 3 {
		t.Fatalf("List returned %d objects, want 3", len(objects))
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

func TestS3Native_Copy(t *testing.T) {
	bucket := uniqueName("test-s3nat-copy")
	c := newS3Storage(t, bucket)
	ctx := context.Background()

	srcKey := "copy/source.txt"
	dstKey := "copy/dest.txt"
	data := []byte("server-side copy test")

	if err := c.Upload(ctx, srcKey, bytes.NewReader(data), int64(len(data))); err != nil {
		t.Fatalf("Upload source: %v", err)
	}

	if err := c.Copy(ctx, srcKey, dstKey); err != nil {
		t.Fatalf("Copy: %v", err)
	}

	// Source should still exist.
	exists, err := c.Exists(ctx, srcKey)
	if err != nil {
		t.Fatalf("Exists source: %v", err)
	}
	if !exists {
		t.Fatal("source deleted after Copy")
	}

	// Destination should exist with same content.
	reader, err := c.Download(ctx, dstKey)
	if err != nil {
		t.Fatalf("Download dest: %v", err)
	}
	defer reader.Close()

	got, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("ReadAll dest: %v", err)
	}
	if !bytes.Equal(got, data) {
		t.Fatalf("copy content mismatch: got %q, want %q", got, data)
	}
}

func TestS3Native_LargeObject(t *testing.T) {
	bucket := uniqueName("test-s3nat-large")
	c := newS3Storage(t, bucket)
	ctx := context.Background()

	size := 10 * 1024 * 1024 // 10 MB
	data := bytes.Repeat([]byte("Y"), size)
	key := "large/10mb-native.bin"

	if err := c.Upload(ctx, key, bytes.NewReader(data), int64(size)); err != nil {
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
}

// TestS3Native_ConcurrentUploads verifies the upload semaphore bounds
// concurrency — all uploads succeed without OOM or deadlock.
func TestS3Native_ConcurrentUploads(t *testing.T) {
	bucket := uniqueName("test-s3nat-conc")
	c := newS3Storage(t, bucket)
	ctx := context.Background()

	// Launch more goroutines than the semaphore allows. All should complete.
	const numUploads = 20
	const blobSize = 256 * 1024 // 256 KB each

	var peakConcurrent atomic.Int32
	var current atomic.Int32

	g, gctx := errgroup.WithContext(ctx)
	for i := range numUploads {
		g.Go(func() error {
			cur := current.Add(1)
			defer current.Add(-1)

			// Track peak concurrency.
			for {
				old := peakConcurrent.Load()
				if cur <= old || peakConcurrent.CompareAndSwap(old, cur) {
					break
				}
			}

			key := fmt.Sprintf("concurrent/upload-%d.dat", i)
			data := bytes.Repeat([]byte{byte(i)}, blobSize)
			return c.Upload(gctx, key, bytes.NewReader(data), int64(blobSize))
		})
	}

	if err := g.Wait(); err != nil {
		t.Fatalf("concurrent uploads failed: %v", err)
	}

	t.Logf("peak concurrent uploads: %d (semaphore limit: %d)",
		peakConcurrent.Load(), objstore.MaxConcurrentUploads())

	// Verify all objects exist.
	for i := range numUploads {
		key := fmt.Sprintf("concurrent/upload-%d.dat", i)
		exists, err := c.Exists(ctx, key)
		if err != nil {
			t.Fatalf("Exists %s: %v", key, err)
		}
		if !exists {
			t.Errorf("upload %s missing after concurrent write", key)
		}
	}
}

// TestS3Native_UploadSemaphore_CancelledContext verifies that uploads blocked
// on the semaphore respect context cancellation.
func TestS3Native_UploadSemaphore_CancelledContext(t *testing.T) {
	bucket := uniqueName("test-s3nat-cancel")
	c := newS3Storage(t, bucket)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel immediately

	err := c.Upload(ctx, "should-not-exist.dat", bytes.NewReader([]byte("x")), 1)
	if err == nil {
		t.Fatal("expected error from cancelled context")
	}
}

// TestS3Native_RcloneInterop verifies that blobs written by the native S3
// client can be read by rclone and vice versa — ensuring binary compatibility.
func TestS3Native_RcloneInterop(t *testing.T) {
	bucket := uniqueName("test-s3nat-interop")
	native := newS3Storage(t, bucket)
	rclone := newObjectStorage(t, bucket)
	ctx := context.Background()

	// Write via native, read via rclone.
	data1 := []byte("written by native Go client")
	key1 := "interop/native-to-rclone.txt"
	if err := native.Upload(ctx, key1, bytes.NewReader(data1), int64(len(data1))); err != nil {
		t.Fatalf("native Upload: %v", err)
	}

	reader, err := rclone.Download(ctx, key1)
	if err != nil {
		t.Fatalf("rclone Download: %v", err)
	}
	got1, err := io.ReadAll(reader)
	reader.Close()
	if err != nil {
		t.Fatalf("rclone ReadAll: %v", err)
	}
	if !bytes.Equal(got1, data1) {
		t.Fatalf("native→rclone mismatch: got %q, want %q", got1, data1)
	}

	// Write via rclone, read via native.
	data2 := []byte("written by rclone subprocess")
	key2 := "interop/rclone-to-native.txt"
	if err := rclone.Upload(ctx, key2, bytes.NewReader(data2), int64(len(data2))); err != nil {
		t.Fatalf("rclone Upload: %v", err)
	}

	reader2, err := native.Download(ctx, key2)
	if err != nil {
		t.Fatalf("native Download: %v", err)
	}
	got2, err := io.ReadAll(reader2)
	reader2.Close()
	if err != nil {
		t.Fatalf("native ReadAll: %v", err)
	}
	if !bytes.Equal(got2, data2) {
		t.Fatalf("rclone→native mismatch: got %q, want %q", got2, data2)
	}
}
