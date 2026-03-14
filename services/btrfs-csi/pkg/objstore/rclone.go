package objstore

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"

	"k8s.io/klog/v2"
)

// rcloneBin is the hardcoded name of the rclone binary. All command execution
// in this file is restricted to this single binary.
const rcloneBin = "rclone"

// RcloneStorage implements ObjectStorage by shelling out to the rclone binary.
// It uses rclone's backend-specific remote path syntax (:provider:bucket/key)
// so no rclone.conf file is needed. All provider configuration is passed via
// environment variables using rclone's RCLONE_<PROVIDER>_<KEY> convention.
type RcloneStorage struct {
	provider string   // "s3", "gcs", "azureblob"
	bucket   string
	env      []string // Pre-formatted KEY=VALUE for process env
}

// NewRcloneStorage creates a new RcloneStorage. provider is the rclone backend
// name (e.g. "s3", "gcs", "azureblob"), bucket is the bucket/container name,
// and env supplies additional environment variables (typically RCLONE_* config).
// The process inherits the current environment; entries in env override
// any inherited values with the same key.
func NewRcloneStorage(provider, bucket string, env map[string]string) (*RcloneStorage, error) {
	if provider == "" {
		return nil, fmt.Errorf("objstore: provider must not be empty")
	}
	if bucket == "" {
		return nil, fmt.Errorf("objstore: bucket must not be empty")
	}

	// Start with inherited environment as the base.
	merged := os.Environ()

	// Overlay caller-supplied variables so they take precedence.
	for k, v := range env {
		merged = append(merged, k+"="+v)
	}

	return &RcloneStorage{
		provider: provider,
		bucket:   bucket,
		env:      merged,
	}, nil
}

// ---------------------------------------------------------------------------
// ObjectStorage implementation
// ---------------------------------------------------------------------------

// Upload writes data from reader to the object at key using `rclone rcat`.
func (r *RcloneStorage) Upload(ctx context.Context, key string, reader io.Reader, size int64) error {
	cmd := r.command(ctx, "rcat", r.remotePath(key))
	cmd.Stdin = reader
	cmd.Stderr = &logWriter{prefix: "rclone rcat"}

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("upload %q: %w", key, err)
	}
	klog.V(4).Infof("Uploaded %s", key)
	return nil
}

// Download returns a ReadCloser streaming the object at key via `rclone cat`.
// The caller is responsible for closing the returned reader.
func (r *RcloneStorage) Download(ctx context.Context, key string) (io.ReadCloser, error) {
	cmd := r.command(ctx, "cat", r.remotePath(key))
	cmd.Stderr = &logWriter{prefix: "rclone cat"}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("stdout pipe for rclone cat: %w", err)
	}

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start rclone cat %q: %w", key, err)
	}

	klog.V(4).Infof("Downloading %s", key)
	return &cmdReadCloser{ReadCloser: stdout, cmd: cmd}, nil
}

// Delete removes the object at key using `rclone deletefile`.
// Deleting a non-existent key is a no-op (matches S3 DeleteObject semantics).
func (r *RcloneStorage) Delete(ctx context.Context, key string) error {
	cmd := r.command(ctx, "deletefile", r.remotePath(key))
	cmd.Stderr = &logWriter{prefix: "rclone deletefile"}

	if err := cmd.Run(); err != nil {
		// rclone deletefile exits with code 4 when the object does not exist.
		// Treat this as a no-op to match S3 DeleteObject idempotency.
		if exitErr, ok := err.(*exec.ExitError); ok && exitErr.ExitCode() == 4 {
			klog.V(4).Infof("Delete %s: object not found (no-op)", key)
			return nil
		}
		return fmt.Errorf("delete %q: %w", key, err)
	}
	klog.V(4).Infof("Deleted %s", key)
	return nil
}

// Exists returns true if an object with the given key exists.
// It uses `rclone lsf --max-depth 1` on the exact key path; if the object
// exists the output will be non-empty, otherwise empty. Both cases return
// exit code 0.
func (r *RcloneStorage) Exists(ctx context.Context, key string) (bool, error) {
	cmd := r.command(ctx, "lsf", "--max-depth", "1", r.remotePath(key))

	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &logWriter{prefix: "rclone lsf"}

	if err := cmd.Run(); err != nil {
		// rclone lsf returns exit 0 for non-existent objects (empty output).
		// A non-zero exit indicates a real error (auth, network, etc.).
		return false, fmt.Errorf("exists %q: %w", key, err)
	}

	return strings.TrimSpace(stdout.String()) != "", nil
}

// List returns metadata for all objects whose key starts with prefix.
// It uses `rclone lsjson --recursive` and parses the JSON output.
func (r *RcloneStorage) List(ctx context.Context, prefix string) ([]ObjectInfo, error) {
	cmd := r.command(ctx, "lsjson", "--recursive", r.remotePath(prefix))

	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &logWriter{prefix: "rclone lsjson"}

	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("list prefix %q: %w", prefix, err)
	}

	results, err := parseLsjsonOutput(stdout.Bytes(), prefix)
	if err != nil {
		return nil, fmt.Errorf("list prefix %q: parse lsjson: %w", prefix, err)
	}

	klog.V(4).Infof("Listed %d objects with prefix %q", len(results), prefix)
	return results, nil
}

// EnsureBucket creates the bucket if it does not already exist using
// `rclone mkdir`. This operation is idempotent.
func (r *RcloneStorage) EnsureBucket(ctx context.Context) error {
	cmd := r.command(ctx, "mkdir", r.remotePath(""))
	cmd.Stderr = &logWriter{prefix: "rclone mkdir"}

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("ensure bucket %q: %w", r.bucket, err)
	}
	klog.V(2).Infof("Ensured bucket %s exists", r.bucket)
	return nil
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// command builds an exec.Cmd for the rclone binary with the configured
// environment variables.
func (r *RcloneStorage) command(ctx context.Context, args ...string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, rcloneBin, args...) // #nosec G204 -- binary is a hardcoded constant
	cmd.Env = r.env
	return cmd
}

// remotePath returns the rclone remote path for the given key using the
// backend-specific syntax :provider:bucket/key. If key is empty it returns
// :provider:bucket.
func (r *RcloneStorage) remotePath(key string) string {
	if key == "" {
		return fmt.Sprintf(":%s:%s", r.provider, r.bucket)
	}
	return fmt.Sprintf(":%s:%s/%s", r.provider, r.bucket, key)
}

// ---------------------------------------------------------------------------
// lsjson parsing
// ---------------------------------------------------------------------------

// lsjsonEntry represents a single item in rclone's lsjson output.
type lsjsonEntry struct {
	Path    string    `json:"Path"`
	Name    string    `json:"Name"`
	Size    int64     `json:"Size"`
	ModTime time.Time `json:"ModTime"`
	IsDir   bool      `json:"IsDir"`
}

// parseLsjsonOutput parses the JSON array produced by `rclone lsjson` into a
// slice of ObjectInfo. Only non-directory entries are included. The prefix is
// prepended to each Path to reconstruct the full object key.
func parseLsjsonOutput(data []byte, prefix string) ([]ObjectInfo, error) {
	// rclone lsjson returns "[]" or empty output when there are no results.
	trimmed := bytes.TrimSpace(data)
	if len(trimmed) == 0 || string(trimmed) == "[]" {
		return nil, nil
	}

	var entries []lsjsonEntry
	if err := json.Unmarshal(trimmed, &entries); err != nil {
		return nil, fmt.Errorf("unmarshal lsjson output: %w", err)
	}

	var results []ObjectInfo
	for _, e := range entries {
		if e.IsDir {
			continue
		}

		// Reconstruct full key by prepending the prefix.
		fullKey := e.Path
		if prefix != "" {
			// Ensure exactly one separator between prefix and relative path.
			fullKey = strings.TrimRight(prefix, "/") + "/" + e.Path
		}

		results = append(results, ObjectInfo{
			Key:          fullKey,
			Size:         e.Size,
			LastModified: e.ModTime,
		})
	}

	return results, nil
}

// ---------------------------------------------------------------------------
// Process helpers (matching patterns from pkg/btrfs/btrfs.go)
// ---------------------------------------------------------------------------

// cmdReadCloser wraps a stdout pipe so that Close also waits for the
// underlying process to exit.
type cmdReadCloser struct {
	io.ReadCloser
	cmd *exec.Cmd
}

func (c *cmdReadCloser) Close() error {
	_ = c.ReadCloser.Close()
	return c.cmd.Wait()
}

// logWriter is an io.Writer that forwards written data to klog as warnings.
type logWriter struct {
	prefix string
}

func (w *logWriter) Write(p []byte) (int, error) {
	msg := strings.TrimSpace(string(p))
	if msg != "" {
		klog.Warningf("[%s] %s", w.prefix, msg)
	}
	return len(p), nil
}
