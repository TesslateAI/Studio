package objstore

import (
	"context"
	"io"
	"time"
)

// ObjectInfo holds metadata about a stored object.
type ObjectInfo struct {
	Key          string
	Size         int64
	LastModified time.Time
}

// ObjectStorage defines operations for reading and writing objects to a
// cloud-agnostic storage backend.
type ObjectStorage interface {
	Upload(ctx context.Context, key string, reader io.Reader, size int64) error
	Download(ctx context.Context, key string) (io.ReadCloser, error)
	Delete(ctx context.Context, key string) error
	Exists(ctx context.Context, key string) (bool, error)
	List(ctx context.Context, prefix string) ([]ObjectInfo, error)
	EnsureBucket(ctx context.Context) error

	// Copy performs a server-side copy from srcKey to dstKey. The source
	// object is not deleted. Used by CAS to move blobs from a staging key
	// to their content-addressed key without re-uploading data.
	Copy(ctx context.Context, srcKey, dstKey string) error
}
