//go:build integration

package integration

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/fileops"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/nodeops"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/objstore"
	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
)

// localhostTestCredentials returns plaintext gRPC transport credentials for
// integration tests that connect to servers on localhost inside an isolated
// test container. This is intentionally insecure -- production code uses mTLS
// via TLSConfig.
func localhostTestCredentials() credentials.TransportCredentials {
	// nolint:gosec // Integration test only -- localhost inside test container.
	return insecure.NewCredentials() // nosemgrep: go.grpc.security.grpc-client-insecure-connection.grpc-client-insecure-connection
}

// getPoolPath returns the btrfs pool path from the TESSLATE_BTRFS_POOL
// environment variable. The test is skipped when the variable is unset.
func getPoolPath(t *testing.T) string {
	t.Helper()
	pool := os.Getenv("TESSLATE_BTRFS_POOL")
	if pool == "" {
		t.Skip("TESSLATE_BTRFS_POOL not set — skipping integration tests")
	}
	return pool
}

// getS3Endpoint returns the S3-compatible endpoint from the
// TESSLATE_S3_ENDPOINT environment variable. The test is skipped when unset.
func getS3Endpoint(t *testing.T) string {
	t.Helper()
	ep := os.Getenv("TESSLATE_S3_ENDPOINT")
	if ep == "" {
		t.Skip("TESSLATE_S3_ENDPOINT not set — skipping S3 integration tests")
	}
	return ep
}

// newObjectStorage creates an objstore.ObjectStorage connected to a real MinIO
// instance via rclone. It ensures the given bucket exists before returning.
func newObjectStorage(t *testing.T, bucket string) objstore.ObjectStorage {
	t.Helper()
	endpoint := getS3Endpoint(t)

	store, err := objstore.NewRcloneStorage("s3", bucket, map[string]string{
		"RCLONE_S3_PROVIDER":          "Minio",
		"RCLONE_S3_ENDPOINT":          "http://" + endpoint,
		"RCLONE_S3_ACCESS_KEY_ID":     "minioadmin",
		"RCLONE_S3_SECRET_ACCESS_KEY": "minioadmin",
	})
	if err != nil {
		t.Fatalf("newObjectStorage: %v", err)
	}

	if err := store.EnsureBucket(context.Background()); err != nil {
		t.Fatalf("EnsureBucket(%s): %v", bucket, err)
	}
	return store
}

// newBtrfsManager is shorthand for btrfs.NewManager(getPoolPath(t)).
func newBtrfsManager(t *testing.T) *btrfs.Manager {
	t.Helper()
	return btrfs.NewManager(getPoolPath(t))
}

// uniqueName returns a string of the form "<prefix>-<8 random hex chars>".
func uniqueName(prefix string) string {
	b := make([]byte, 4)
	if _, err := rand.Read(b); err != nil {
		panic(fmt.Sprintf("crypto/rand: %v", err))
	}
	return prefix + "-" + hex.EncodeToString(b)
}

// writeTestFile creates a file at dir/name with the given content.
// Parent directories are created as needed.
func writeTestFile(t *testing.T, dir, name, content string) {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatalf("MkdirAll for %s: %v", path, err)
	}
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("WriteFile %s: %v", path, err)
	}
}

// verifyFileContent reads the file at path and asserts its content equals want.
func verifyFileContent(t *testing.T, path, want string) {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile %s: %v", path, err)
	}
	if string(data) != want {
		t.Fatalf("file %s content = %q, want %q", path, string(data), want)
	}
}

// startNodeOpsServer starts a nodeops gRPC server on a random free port.
// It returns the address string ("localhost:PORT") and registers a cleanup
// function that stops the server when the test completes.
func startNodeOpsServer(t *testing.T, bm *btrfs.Manager, syncer *bsync.Daemon, tmplMgr *template.Manager) string {
	t.Helper()

	// Find a free port.
	lis, err := net.Listen("tcp", "localhost:0")
	if err != nil {
		t.Fatalf("find free port: %v", err)
	}
	addr := lis.Addr().String()
	lis.Close()

	srv := nodeops.NewServer(bm, syncer, tmplMgr, nil)
	go func() {
		// Start blocks; ignore "use of closed" errors on shutdown.
		_ = srv.Start(addr, nil)
	}()

	// Give the server a moment to start.
	time.Sleep(50 * time.Millisecond)

	t.Cleanup(func() {
		srv.Stop()
	})
	return addr
}

// startFileOpsServer starts a fileops gRPC server on a random free port.
// It returns the address string ("localhost:PORT") and registers a cleanup
// function that stops the server when the test completes.
func startFileOpsServer(t *testing.T, poolPath string) string {
	return startFileOpsServerWithSyncer(t, poolPath, nil)
}

// startFileOpsServerWithSyncer starts a fileops gRPC server with an optional
// DirtySyncer for dirty-tracking integration tests.
func startFileOpsServerWithSyncer(t *testing.T, poolPath string, syncer fileops.DirtySyncer) string {
	t.Helper()

	// Find a free port.
	lis, err := net.Listen("tcp", "localhost:0")
	if err != nil {
		t.Fatalf("find free port: %v", err)
	}
	addr := lis.Addr().String()
	lis.Close()

	srv := fileops.NewServer(poolPath, syncer)
	go func() {
		// Start blocks; ignore "use of closed" errors on shutdown.
		_ = srv.Start(addr, nil)
	}()

	// Give the server a moment to start.
	time.Sleep(50 * time.Millisecond)

	t.Cleanup(func() {
		srv.Stop()
	})
	return addr
}

// connectNodeOpsClient connects to a nodeops gRPC server at addr using
// plaintext (insecure) transport. The connection is closed on test cleanup.
func connectNodeOpsClient(t *testing.T, addr string) *nodeops.Client {
	t.Helper()
	c, err := nodeops.NewClientWithDialOptions(addr, grpc.WithTransportCredentials(localhostTestCredentials()))
	if err != nil {
		t.Fatalf("connect nodeops client: %v", err)
	}
	t.Cleanup(func() {
		c.Close()
	})
	return c
}

// connectFileOpsClient connects to a fileops gRPC server at addr using
// plaintext (insecure) transport. The connection is closed on test cleanup.
func connectFileOpsClient(t *testing.T, addr string) *fileops.Client {
	t.Helper()
	c, err := fileops.NewClient(addr, grpc.WithTransportCredentials(localhostTestCredentials()))
	if err != nil {
		t.Fatalf("connect fileops client: %v", err)
	}
	t.Cleanup(func() {
		c.Close()
	})
	return c
}
