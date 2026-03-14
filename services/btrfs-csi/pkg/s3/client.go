package s3

import (
	"context"
	"fmt"
	"io"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"k8s.io/klog/v2"
)

// ObjectInfo holds metadata about an object stored in S3.
type ObjectInfo struct {
	Key          string
	Size         int64
	LastModified time.Time
}

// Client is a thin wrapper around the MinIO Go SDK for S3-compatible storage.
type Client struct {
	mc     *minio.Client
	bucket string
}

// NewClient creates a new S3 Client. It connects to the given endpoint with
// the provided credentials. useSSL controls whether TLS is used.
func NewClient(endpoint, accessKey, secretKey, bucket, region string, useSSL bool) (*Client, error) {
	mc, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: useSSL,
		Region: region,
	})
	if err != nil {
		return nil, fmt.Errorf("create minio client: %w", err)
	}

	klog.V(2).Infof("S3 client created for endpoint=%s bucket=%s region=%s ssl=%v", endpoint, bucket, region, useSSL)
	return &Client{mc: mc, bucket: bucket}, nil
}

// EnsureBucket creates the configured bucket if it does not already exist.
func (c *Client) EnsureBucket(ctx context.Context, region string) error {
	exists, err := c.mc.BucketExists(ctx, c.bucket)
	if err != nil {
		return fmt.Errorf("check bucket %q: %w", c.bucket, err)
	}
	if exists {
		return nil
	}
	if err := c.mc.MakeBucket(ctx, c.bucket, minio.MakeBucketOptions{Region: region}); err != nil {
		return fmt.Errorf("create bucket %q: %w", c.bucket, err)
	}
	klog.Infof("Created S3 bucket %q in region %s", c.bucket, region)
	return nil
}

// Upload writes data from reader to the object at key. The content-encoding
// is set to zstd so consumers know the data is compressed.
func (c *Client) Upload(ctx context.Context, key string, reader io.Reader, size int64) error {
	opts := minio.PutObjectOptions{
		ContentEncoding: "zstd",
	}

	// If size is unknown, use -1 to let the SDK handle streaming.
	if size <= 0 {
		size = -1
	}

	info, err := c.mc.PutObject(ctx, c.bucket, key, reader, size, opts)
	if err != nil {
		return fmt.Errorf("upload %q: %w", key, err)
	}
	klog.V(4).Infof("Uploaded %s (%d bytes)", key, info.Size)
	return nil
}

// Download returns a ReadCloser for the object at key. The caller is
// responsible for closing the returned reader.
func (c *Client) Download(ctx context.Context, key string) (io.ReadCloser, error) {
	obj, err := c.mc.GetObject(ctx, c.bucket, key, minio.GetObjectOptions{})
	if err != nil {
		return nil, fmt.Errorf("download %q: %w", key, err)
	}

	// Verify the object is accessible by stating it.
	if _, statErr := obj.Stat(); statErr != nil {
		_ = obj.Close()
		return nil, fmt.Errorf("stat %q after get: %w", key, statErr)
	}

	klog.V(4).Infof("Downloading %s", key)
	return obj, nil
}

// Delete removes the object at key.
func (c *Client) Delete(ctx context.Context, key string) error {
	err := c.mc.RemoveObject(ctx, c.bucket, key, minio.RemoveObjectOptions{})
	if err != nil {
		return fmt.Errorf("delete %q: %w", key, err)
	}
	klog.V(4).Infof("Deleted %s", key)
	return nil
}

// Exists returns true if an object with the given key exists in the bucket.
func (c *Client) Exists(ctx context.Context, key string) (bool, error) {
	_, err := c.mc.StatObject(ctx, c.bucket, key, minio.StatObjectOptions{})
	if err != nil {
		resp := minio.ToErrorResponse(err)
		if resp.Code == "NoSuchKey" {
			return false, nil
		}
		return false, fmt.Errorf("stat %q: %w", key, err)
	}
	return true, nil
}

// List returns metadata for all objects whose key starts with the given
// prefix. Results are collected fully into memory; for very large listings
// consider streaming with the underlying SDK directly.
func (c *Client) List(ctx context.Context, prefix string) ([]ObjectInfo, error) {
	var results []ObjectInfo

	opts := minio.ListObjectsOptions{
		Prefix:    prefix,
		Recursive: true,
	}

	for obj := range c.mc.ListObjects(ctx, c.bucket, opts) {
		if obj.Err != nil {
			return results, fmt.Errorf("list prefix %q: %w", prefix, obj.Err)
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
