package objstore

import (
	"context"
	"fmt"
	"io"
	"os"
	"runtime/debug"
	"strings"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"k8s.io/klog/v2"
)

// s3PartSize is the multipart upload part size. minio-go defaults to
// computing this from the assumed object size (5 TiB / 10000 = 512 MiB)
// when size is unknown (-1). Our blobs are incremental btrfs diffs,
// typically KB to low-MB — 16 MiB is generous. This prevents minio-go
// from allocating a 512 MiB buffer per upload.
const s3PartSize = 16 * 1024 * 1024 // 16 MiB

// maxConcurrentUploads limits concurrent uploads to bound peak memory.
// Each upload allocates a partSize buffer (16 MiB). With rclone these
// lived in child processes — now they share the driver's heap.
// Peak upload memory: maxConcurrentUploads × s3PartSize = 96 MiB.
const maxConcurrentUploads = 6

// MaxConcurrentUploads returns the upload concurrency limit (for tests).
func MaxConcurrentUploads() int { return maxConcurrentUploads }

// S3Config holds configuration for a native S3 client.
type S3Config struct {
	Endpoint       string // e.g. "minio.kube-system.svc:9000" or "s3.amazonaws.com"
	AccessKeyID    string
	SecretAccessKey string
	Region         string
	Bucket         string
	UseSSL         bool // false for MinIO / local, true for AWS S3
}

// S3Storage implements ObjectStorage using the minio-go SDK. Unlike
// RcloneStorage, it maintains a persistent HTTP connection pool — no
// per-operation process spawn overhead. A semaphore limits concurrent
// data operations to prevent OOM in memory-constrained containers.
type S3Storage struct {
	client *minio.Client
	bucket string
	sem    chan struct{} // bounds concurrent uploads + downloads
}

// buildS3Credentials selects the appropriate credentials provider for the
// minio-go client. Precedence:
//
//  1. Static keys when both AccessKeyID and SecretAccessKey are set.
//  2. AWS EKS IRSA (AssumeRoleWithWebIdentity) when AWS_WEB_IDENTITY_TOKEN_FILE
//     and AWS_ROLE_ARN are present — common for service-account-bound IAM on EKS.
//  3. IAM chain (env vars → shared file → EC2/ECS metadata) as a final fallback.
//
// Returns the provider plus a short source label for logging.
func buildS3Credentials(cfg S3Config) (*credentials.Credentials, string, error) {
	if cfg.AccessKeyID != "" && cfg.SecretAccessKey != "" {
		return credentials.NewStaticV4(cfg.AccessKeyID, cfg.SecretAccessKey, ""), "static", nil
	}

	tokenFile := os.Getenv("AWS_WEB_IDENTITY_TOKEN_FILE")
	roleARN := os.Getenv("AWS_ROLE_ARN")
	if tokenFile != "" && roleARN != "" {
		region := cfg.Region
		if region == "" {
			region = os.Getenv("AWS_REGION")
		}
		if region == "" {
			region = "us-east-1"
		}
		stsEndpoint := fmt.Sprintf("https://sts.%s.amazonaws.com", region)

		creds, err := credentials.NewSTSWebIdentity(
			stsEndpoint,
			func() (*credentials.WebIdentityToken, error) {
				token, err := os.ReadFile(tokenFile)
				if err != nil {
					return nil, fmt.Errorf("read IRSA token %s: %w", tokenFile, err)
				}
				return &credentials.WebIdentityToken{Token: string(token)}, nil
			},
			func(s *credentials.STSWebIdentity) { s.RoleARN = roleARN },
		)
		if err != nil {
			return nil, "", fmt.Errorf("create IRSA credentials: %w", err)
		}
		return creds, "irsa", nil
	}

	// Fallback chain: env vars, shared credentials file, EC2/ECS metadata.
	return credentials.NewChainCredentials([]credentials.Provider{
		&credentials.EnvAWS{},
		&credentials.FileAWSCredentials{},
		&credentials.IAM{},
	}), "iam-chain", nil
}

// NewS3Storage creates a native S3 client backed by minio-go.
func NewS3Storage(cfg S3Config) (*S3Storage, error) {
	if cfg.Endpoint == "" {
		return nil, fmt.Errorf("objstore: S3 endpoint must not be empty")
	}
	if cfg.Bucket == "" {
		return nil, fmt.Errorf("objstore: S3 bucket must not be empty")
	}

	// minio-go expects host:port without scheme — the scheme is controlled
	// by the Secure option. Strip http:// or https:// if present (rclone
	// endpoints typically include the scheme).
	endpoint := cfg.Endpoint
	if after, ok := strings.CutPrefix(endpoint, "https://"); ok {
		endpoint = after
		if !cfg.UseSSL {
			cfg.UseSSL = true
		}
	} else if after, ok := strings.CutPrefix(endpoint, "http://"); ok {
		endpoint = after
	}

	creds, credsSource, err := buildS3Credentials(cfg)
	if err != nil {
		return nil, err
	}

	client, err := minio.New(endpoint, &minio.Options{
		Creds:  creds,
		Secure: cfg.UseSSL,
		Region: cfg.Region,
	})
	if err != nil {
		return nil, fmt.Errorf("create S3 client for %s: %w", cfg.Endpoint, err)
	}

	klog.V(2).Infof("S3 native client connected to %s (bucket=%s, ssl=%v, creds=%s, maxOps=%d)",
		cfg.Endpoint, cfg.Bucket, cfg.UseSSL, credsSource, maxConcurrentUploads)

	return &S3Storage{
		client: client,
		bucket: cfg.Bucket,
		sem:    make(chan struct{}, maxConcurrentUploads),
	}, nil
}

// acquireSem acquires a data-operation permit. Returns false if ctx is cancelled.
func (s *S3Storage) acquireSem(ctx context.Context) bool {
	select {
	case s.sem <- struct{}{}:
		return true
	case <-ctx.Done():
		return false
	}
}

func (s *S3Storage) releaseSem() {
	<-s.sem
	// Hint the GC to reclaim upload/download buffers promptly.
	// FreeOSMemory is cheap (~100µs) and prevents heap from lingering
	// at high-water marks between bursts of S3 operations.
	debug.FreeOSMemory()
}

// Upload writes data from reader to the object at key.
func (s *S3Storage) Upload(ctx context.Context, key string, reader io.Reader, size int64) error {
	if !s.acquireSem(ctx) {
		return ctx.Err()
	}
	defer s.releaseSem()

	opts := minio.PutObjectOptions{
		PartSize: s3PartSize,
	}
	// size -1 tells minio-go to use multipart upload with unknown size.
	if size <= 0 {
		size = -1
	}
	_, err := s.client.PutObject(ctx, s.bucket, key, reader, size, opts)
	if err != nil {
		return fmt.Errorf("upload %q: %w", key, err)
	}
	klog.V(4).Infof("Uploaded %s", key)
	return nil
}

// Download returns a ReadCloser streaming the object at key.
// Downloads are truly streaming (no large buffer allocation), so they
// do not acquire the upload semaphore — no leak risk from unclosed readers.
func (s *S3Storage) Download(ctx context.Context, key string) (io.ReadCloser, error) {
	obj, err := s.client.GetObject(ctx, s.bucket, key, minio.GetObjectOptions{})
	if err != nil {
		return nil, fmt.Errorf("download %q: %w", key, err)
	}
	// Stat to trigger actual request and surface errors (e.g. NoSuchKey)
	// before the caller starts reading.
	if _, err := obj.Stat(); err != nil {
		obj.Close()
		return nil, fmt.Errorf("download %q: %w", key, err)
	}
	klog.V(4).Infof("Downloading %s", key)
	return obj, nil
}

// Delete removes the object at key. Deleting a non-existent key is a no-op
// (matches S3 DeleteObject semantics).
func (s *S3Storage) Delete(ctx context.Context, key string) error {
	err := s.client.RemoveObject(ctx, s.bucket, key, minio.RemoveObjectOptions{})
	if err != nil {
		// S3 DeleteObject is already idempotent (no error for missing key),
		// but check for NoSuchKey just in case of non-standard providers.
		if isNoSuchKey(err) {
			klog.V(4).Infof("Delete %s: object not found (no-op)", key)
			return nil
		}
		return fmt.Errorf("delete %q: %w", key, err)
	}
	klog.V(4).Infof("Deleted %s", key)
	return nil
}

// Exists returns true if an object with the given key exists.
func (s *S3Storage) Exists(ctx context.Context, key string) (bool, error) {
	_, err := s.client.StatObject(ctx, s.bucket, key, minio.StatObjectOptions{})
	if err != nil {
		if isNoSuchKey(err) {
			return false, nil
		}
		return false, fmt.Errorf("exists %q: %w", key, err)
	}
	return true, nil
}

// List returns metadata for all objects whose key starts with prefix.
func (s *S3Storage) List(ctx context.Context, prefix string) ([]ObjectInfo, error) {
	opts := minio.ListObjectsOptions{
		Prefix:    prefix,
		Recursive: true,
	}

	var results []ObjectInfo
	for obj := range s.client.ListObjects(ctx, s.bucket, opts) {
		if obj.Err != nil {
			return nil, fmt.Errorf("list prefix %q: %w", prefix, obj.Err)
		}
		results = append(results, ObjectInfo{
			Key:          obj.Key,
			Size:         obj.Size,
			LastModified: obj.LastModified,
		})
	}

	klog.V(4).Infof("Listed %d objects with prefix %q", len(results), prefix)
	return results, nil
}

// Copy performs a server-side copy from srcKey to dstKey. Uses S3 CopyObject
// (zero data transfer — server-side only).
func (s *S3Storage) Copy(ctx context.Context, srcKey, dstKey string) error {
	src := minio.CopySrcOptions{
		Bucket: s.bucket,
		Object: srcKey,
	}
	dst := minio.CopyDestOptions{
		Bucket: s.bucket,
		Object: dstKey,
	}
	_, err := s.client.CopyObject(ctx, dst, src)
	if err != nil {
		return fmt.Errorf("copy %q -> %q: %w", srcKey, dstKey, err)
	}
	klog.V(4).Infof("Copied %s -> %s", srcKey, dstKey)
	return nil
}

// EnsureBucket creates the bucket if it does not already exist.
func (s *S3Storage) EnsureBucket(ctx context.Context) error {
	exists, err := s.client.BucketExists(ctx, s.bucket)
	if err != nil {
		return fmt.Errorf("check bucket %q: %w", s.bucket, err)
	}
	if exists {
		return nil
	}
	if err := s.client.MakeBucket(ctx, s.bucket, minio.MakeBucketOptions{}); err != nil {
		// Race: another process may have created it.
		if exists2, _ := s.client.BucketExists(ctx, s.bucket); exists2 {
			return nil
		}
		return fmt.Errorf("create bucket %q: %w", s.bucket, err)
	}
	klog.V(2).Infof("Created bucket %s", s.bucket)
	return nil
}

// isNoSuchKey checks if a minio error indicates the object does not exist.
func isNoSuchKey(err error) bool {
	resp := minio.ToErrorResponse(err)
	if resp.Code == "NoSuchKey" || resp.StatusCode == 404 {
		return true
	}
	// Fallback string check for non-standard S3 implementations.
	return strings.Contains(err.Error(), "NoSuchKey") ||
		strings.Contains(err.Error(), "The specified key does not exist")
}

// DetectSSL determines SSL from the endpoint URL scheme. Returns true for
// https://, false for http:// or no scheme.
func DetectSSL(endpoint string) bool {
	return strings.HasPrefix(strings.ToLower(endpoint), "https://")
}
