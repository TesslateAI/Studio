package cas

import (
	"context"
	"io"
	"strings"
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/objstore"
)

// fakeObjStore implements objstore.ObjectStorage for unit tests.
type fakeObjStore struct {
	objects map[string]fakeObject
	deleted []string
}

type fakeObject struct {
	data         string
	lastModified time.Time
}

func newFakeObjStore() *fakeObjStore {
	return &fakeObjStore{objects: make(map[string]fakeObject)}
}

func (f *fakeObjStore) Upload(_ context.Context, key string, reader io.Reader, _ int64) error {
	data, _ := io.ReadAll(reader)
	f.objects[key] = fakeObject{data: string(data), lastModified: time.Now()}
	return nil
}

func (f *fakeObjStore) Download(_ context.Context, key string) (io.ReadCloser, error) {
	obj, ok := f.objects[key]
	if !ok {
		return nil, io.EOF
	}
	return io.NopCloser(strings.NewReader(obj.data)), nil
}

func (f *fakeObjStore) Delete(_ context.Context, key string) error {
	f.deleted = append(f.deleted, key)
	delete(f.objects, key)
	return nil
}

func (f *fakeObjStore) Exists(_ context.Context, key string) (bool, error) {
	_, ok := f.objects[key]
	return ok, nil
}

func (f *fakeObjStore) List(_ context.Context, prefix string) ([]objstore.ObjectInfo, error) {
	var result []objstore.ObjectInfo
	for key, obj := range f.objects {
		if strings.HasPrefix(key, prefix) {
			result = append(result, objstore.ObjectInfo{
				Key:          key,
				LastModified: obj.lastModified,
			})
		}
	}
	return result, nil
}

func (f *fakeObjStore) EnsureBucket(_ context.Context) error { return nil }

func (f *fakeObjStore) Copy(_ context.Context, src, dst string) error {
	f.objects[dst] = f.objects[src]
	return nil
}

// TestCleanupStaging_DeletesOldKeys verifies that staging keys older than
// StagingMaxAge are deleted.
func TestCleanupStaging_DeletesOldKeys(t *testing.T) {
	obj := newFakeObjStore()
	store := NewStore(obj)

	// Add an old staging key (2 hours ago).
	obj.objects["blobs/_staging/old.zst"] = fakeObject{
		data:         "old-data",
		lastModified: time.Now().Add(-2 * time.Hour),
	}
	// Add a recent staging key (5 minutes ago).
	obj.objects["blobs/_staging/recent.zst"] = fakeObject{
		data:         "recent-data",
		lastModified: time.Now().Add(-5 * time.Minute),
	}
	// Add a non-staging key (should not be touched).
	obj.objects["blobs/sha256:abc.zst"] = fakeObject{
		data:         "blob-data",
		lastModified: time.Now().Add(-24 * time.Hour),
	}

	deleted, err := store.CleanupStaging(context.Background())
	if err != nil {
		t.Fatalf("CleanupStaging failed: %v", err)
	}

	if deleted != 1 {
		t.Errorf("expected 1 deleted, got %d", deleted)
	}

	// Old staging key should be gone.
	if _, ok := obj.objects["blobs/_staging/old.zst"]; ok {
		t.Error("old staging key should have been deleted")
	}

	// Recent staging key should remain.
	if _, ok := obj.objects["blobs/_staging/recent.zst"]; !ok {
		t.Error("recent staging key should still exist")
	}

	// Non-staging blob should be untouched.
	if _, ok := obj.objects["blobs/sha256:abc.zst"]; !ok {
		t.Error("non-staging blob should not be deleted")
	}
}

// TestCleanupStaging_NoOrphans verifies no-op when there are no staging keys.
func TestCleanupStaging_NoOrphans(t *testing.T) {
	obj := newFakeObjStore()
	store := NewStore(obj)

	deleted, err := store.CleanupStaging(context.Background())
	if err != nil {
		t.Fatalf("CleanupStaging failed: %v", err)
	}
	if deleted != 0 {
		t.Errorf("expected 0 deleted, got %d", deleted)
	}
}
