// Package cas implements a content-addressable layer store backed by object
// storage. Every btrfs send stream is a blob identified by its SHA256 hash.
// Volumes are manifests listing ordered layers. Templates, syncs, and user
// snapshots are all layers.
//
// S3 layout:
//
//	blobs/sha256:{hash}.zst       — compressed btrfs send streams
//	manifests/{volume_id}.json    — layer chain per volume
//	index/templates.json          — template name → blob hash
package cas

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"time"

	"github.com/klauspost/compress/zstd"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/objstore"
)

// Store provides content-addressable blob operations backed by object storage.
type Store struct {
	obj objstore.ObjectStorage
}

// NewStore creates a CAS Store backed by the given object storage.
func NewStore(obj objstore.ObjectStorage) *Store {
	return &Store{obj: obj}
}

// blobKey returns the S3 object key for a given content hash.
func blobKey(hash string) string {
	return fmt.Sprintf("blobs/%s.zst", hash)
}

// stagingKey returns a unique temporary S3 key for staging a blob upload.
func stagingKey() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return fmt.Sprintf("blobs/_staging/%s.zst", hex.EncodeToString(b))
}

// PutBlob streams data from r through a SHA256 hasher and zstd compressor,
// uploading to a temporary staging key. Once the hash is known, the blob is
// server-side copied to its content-addressed key and the staging key is
// deleted. This uses constant memory regardless of blob size.
//
// Returns the content-addressed hash ("sha256:{hex}").
// If a blob with the same hash already exists, the upload is skipped (dedup).
func (s *Store) PutBlob(ctx context.Context, r io.Reader) (string, error) {
	// Phase 1: Stream upload to a staging key while computing the hash.
	// Pipeline: r → tee(hasher) → zstd compress → pipe → upload
	hasher := sha256.New()
	tee := io.TeeReader(r, hasher)

	pr, pw := io.Pipe()
	compressErrCh := make(chan error, 1)
	go func() {
		encoder, err := zstd.NewWriter(pw)
		if err != nil {
			pw.CloseWithError(err)
			compressErrCh <- err
			return
		}
		_, copyErr := io.Copy(encoder, tee)
		closeErr := encoder.Close()
		if copyErr != nil {
			pw.CloseWithError(copyErr)
			compressErrCh <- copyErr
			return
		}
		if closeErr != nil {
			pw.CloseWithError(closeErr)
			compressErrCh <- closeErr
			return
		}
		pw.Close()
		compressErrCh <- nil
	}()

	tmpKey := stagingKey()
	if err := s.obj.Upload(ctx, tmpKey, pr, -1); err != nil {
		_ = pr.Close()
		return "", fmt.Errorf("upload staging blob: %w", err)
	}
	_ = pr.Close()

	if compressErr := <-compressErrCh; compressErr != nil {
		_ = s.obj.Delete(ctx, tmpKey)
		return "", fmt.Errorf("compress blob: %w", compressErr)
	}

	// Phase 2: Hash is now known. Copy staging → final key (server-side, zero bandwidth).
	hash := "sha256:" + hex.EncodeToString(hasher.Sum(nil))
	finalKey := blobKey(hash)

	// Dedup: if the blob already exists, just delete the staging key.
	exists, err := s.obj.Exists(ctx, finalKey)
	if err != nil {
		_ = s.obj.Delete(ctx, tmpKey)
		return "", fmt.Errorf("check blob existence: %w", err)
	}
	if exists {
		_ = s.obj.Delete(ctx, tmpKey)
		klog.V(4).Infof("Blob %s already exists, skipping (dedup)", hash)
		return hash, nil
	}

	// Server-side copy to content-addressed key, then clean up staging.
	if err := s.obj.Copy(ctx, tmpKey, finalKey); err != nil {
		_ = s.obj.Delete(ctx, tmpKey)
		return "", fmt.Errorf("copy staging to %s: %w", finalKey, err)
	}
	_ = s.obj.Delete(ctx, tmpKey)

	klog.V(2).Infof("Stored blob %s", hash)
	return hash, nil
}

// GetBlob downloads the blob identified by hash and returns a reader over the
// decompressed content. The caller must close the returned ReadCloser.
func (s *Store) GetBlob(ctx context.Context, hash string) (io.ReadCloser, error) {
	key := blobKey(hash)
	reader, err := s.obj.Download(ctx, key)
	if err != nil {
		return nil, fmt.Errorf("download blob %s: %w", hash, err)
	}

	decoder, err := zstd.NewReader(reader)
	if err != nil {
		reader.Close()
		return nil, fmt.Errorf("create zstd decoder for blob %s: %w", hash, err)
	}

	return &blobReader{decoder: decoder, underlying: reader}, nil
}

// HasBlob returns true if a blob with the given hash exists in object storage.
func (s *Store) HasBlob(ctx context.Context, hash string) (bool, error) {
	return s.obj.Exists(ctx, blobKey(hash))
}

// DeleteBlob removes a blob from object storage.
func (s *Store) DeleteBlob(ctx context.Context, hash string) error {
	return s.obj.Delete(ctx, blobKey(hash))
}

// StagingMaxAge is the maximum age of a staging key before it is considered
// orphaned. PutBlob normally cleans up staging keys immediately, but a crash
// between upload and delete leaves orphans. 1 hour is far longer than any
// normal upload takes.
const StagingMaxAge = 1 * time.Hour

// CleanupStaging deletes orphaned staging keys older than StagingMaxAge.
// Returns the number of keys deleted. Safe to call concurrently — each
// staging key is unique (random), so deleting a key that another goroutine
// is still uploading to is not possible in practice (would require the same
// random 8-byte suffix).
func (s *Store) CleanupStaging(ctx context.Context) (int, error) {
	objects, err := s.obj.List(ctx, "blobs/_staging/")
	if err != nil {
		return 0, fmt.Errorf("list staging objects: %w", err)
	}

	cutoff := time.Now().Add(-StagingMaxAge)
	deleted := 0
	for _, obj := range objects {
		if obj.LastModified.Before(cutoff) {
			if err := s.obj.Delete(ctx, obj.Key); err != nil {
				klog.Warningf("CleanupStaging: failed to delete %s: %v", obj.Key, err)
				continue
			}
			deleted++
		}
	}

	if deleted > 0 {
		klog.Infof("CleanupStaging: deleted %d orphaned staging key(s)", deleted)
	}
	return deleted, nil
}

// blobReader wraps a zstd decoder and the underlying download reader so that
// Close releases both resources.
type blobReader struct {
	decoder    *zstd.Decoder
	underlying io.ReadCloser
}

func (b *blobReader) Read(p []byte) (int, error) {
	return b.decoder.Read(p)
}

func (b *blobReader) Close() error {
	b.decoder.Close()
	return b.underlying.Close()
}
