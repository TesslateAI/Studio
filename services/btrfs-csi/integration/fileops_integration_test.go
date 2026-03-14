//go:build integration

package integration

import (
	"archive/tar"
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// buildTestTar creates an in-memory tar archive from a map of name->content.
func buildTestTar(t *testing.T, files map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	for name, content := range files {
		hdr := &tar.Header{
			Name: name,
			Mode: 0644,
			Size: int64(len(content)),
		}
		if err := tw.WriteHeader(hdr); err != nil {
			t.Fatalf("tar header: %v", err)
		}
		if _, err := tw.Write([]byte(content)); err != nil {
			t.Fatalf("tar write: %v", err)
		}
	}
	tw.Close()
	return buf.Bytes()
}

// ---------------------------------------------------------------------------
// WriteFile / ReadFile
// ---------------------------------------------------------------------------

func TestFileOps_WriteAndReadFile(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	if err := client.WriteFile(ctx, volID, "hello.txt", []byte("hello world"), 0644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	data, err := client.ReadFile(ctx, volID, "hello.txt")
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	if string(data) != "hello world" {
		t.Fatalf("content = %q, want %q", string(data), "hello world")
	}
}

// ---------------------------------------------------------------------------
// ReadFile not found
// ---------------------------------------------------------------------------

func TestFileOps_ReadFile_NotFound(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	_, err := client.ReadFile(ctx, volID, "nonexistent.txt")
	if err == nil {
		t.Fatal("expected error for missing file")
	}
	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status, got %T: %v", err, err)
	}
	if st.Code() != codes.NotFound {
		t.Fatalf("expected NotFound, got %s", st.Code())
	}
}

// ---------------------------------------------------------------------------
// WriteFile creates parent directories
// ---------------------------------------------------------------------------

func TestFileOps_WriteFile_CreatesParentDirs(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	if err := client.WriteFile(ctx, volID, "a/b/c/deep.txt", []byte("deep"), 0644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	data, err := client.ReadFile(ctx, volID, "a/b/c/deep.txt")
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	if string(data) != "deep" {
		t.Fatalf("content = %q, want %q", string(data), "deep")
	}
}

// ---------------------------------------------------------------------------
// ListDir non-recursive
// ---------------------------------------------------------------------------

func TestFileOps_ListDir_NonRecursive(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	for _, name := range []string{"file1.txt", "file2.txt", "file3.txt"} {
		if err := client.WriteFile(ctx, volID, name, []byte("x"), 0644); err != nil {
			t.Fatalf("WriteFile %s: %v", name, err)
		}
	}
	if err := client.MkdirAll(ctx, volID, "subdir"); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}

	entries, err := client.ListDir(ctx, volID, ".", false)
	if err != nil {
		t.Fatalf("ListDir: %v", err)
	}
	if len(entries) != 4 {
		t.Fatalf("expected 4 entries (3 files + 1 dir), got %d", len(entries))
	}
}

// ---------------------------------------------------------------------------
// ListDir recursive
// ---------------------------------------------------------------------------

func TestFileOps_ListDir_Recursive(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	for _, path := range []string{"top.txt", "sub/nested.txt", "sub/deep/bottom.txt"} {
		if err := client.WriteFile(ctx, volID, path, []byte("data"), 0644); err != nil {
			t.Fatalf("WriteFile %s: %v", path, err)
		}
	}

	entries, err := client.ListDir(ctx, volID, ".", true)
	if err != nil {
		t.Fatalf("ListDir recursive: %v", err)
	}

	// Should include: "." (root), "top.txt", "sub", "sub/nested.txt", "sub/deep", "sub/deep/bottom.txt"
	// That is at least 6 entries. The exact count depends on whether the root
	// itself is included by WalkDir (it is).
	if len(entries) < 6 {
		t.Fatalf("expected at least 6 entries (3 files + 2 dirs + root), got %d", len(entries))
	}

	// Verify specific nested file is present.
	foundDeep := false
	for _, e := range entries {
		if e.Path == "sub/deep/bottom.txt" || e.Name == "bottom.txt" {
			foundDeep = true
			break
		}
	}
	if !foundDeep {
		t.Fatal("sub/deep/bottom.txt not found in recursive listing")
	}
}

// ---------------------------------------------------------------------------
// StatPath file
// ---------------------------------------------------------------------------

func TestFileOps_StatPath_File(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	content := []byte("stat-test-content")
	if err := client.WriteFile(ctx, volID, "stat.txt", content, 0644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	info, err := client.StatPath(ctx, volID, "stat.txt")
	if err != nil {
		t.Fatalf("StatPath: %v", err)
	}
	if info.Name != "stat.txt" {
		t.Fatalf("Name = %q, want %q", info.Name, "stat.txt")
	}
	if info.Size != int64(len(content)) {
		t.Fatalf("Size = %d, want %d", info.Size, len(content))
	}
	if info.IsDir {
		t.Fatal("IsDir = true for a file")
	}
}

// ---------------------------------------------------------------------------
// StatPath directory
// ---------------------------------------------------------------------------

func TestFileOps_StatPath_Directory(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	if err := client.MkdirAll(ctx, volID, "mydir"); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}

	info, err := client.StatPath(ctx, volID, "mydir")
	if err != nil {
		t.Fatalf("StatPath: %v", err)
	}
	if !info.IsDir {
		t.Fatal("IsDir = false for a directory")
	}
}

// ---------------------------------------------------------------------------
// DeletePath file
// ---------------------------------------------------------------------------

func TestFileOps_DeletePath_File(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	if err := client.WriteFile(ctx, volID, "hello.txt", []byte("gone soon"), 0644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	if err := client.DeletePath(ctx, volID, "hello.txt"); err != nil {
		t.Fatalf("DeletePath: %v", err)
	}

	_, err := client.StatPath(ctx, volID, "hello.txt")
	if err == nil {
		t.Fatal("expected error after delete")
	}
	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status, got %T: %v", err, err)
	}
	if st.Code() != codes.NotFound {
		t.Fatalf("expected NotFound, got %s", st.Code())
	}
}

// ---------------------------------------------------------------------------
// DeletePath directory (recursive)
// ---------------------------------------------------------------------------

func TestFileOps_DeletePath_Directory(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	if err := client.MkdirAll(ctx, volID, "toremove/child"); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	if err := client.WriteFile(ctx, volID, "toremove/child/file.txt", []byte("bye"), 0644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	if err := client.DeletePath(ctx, volID, "toremove"); err != nil {
		t.Fatalf("DeletePath dir: %v", err)
	}

	_, err := client.StatPath(ctx, volID, "toremove")
	if err == nil {
		t.Fatal("expected error after directory delete")
	}
	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status, got %T: %v", err, err)
	}
	if st.Code() != codes.NotFound {
		t.Fatalf("expected NotFound, got %s", st.Code())
	}
}

// ---------------------------------------------------------------------------
// MkdirAll
// ---------------------------------------------------------------------------

func TestFileOps_MkdirAll(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	if err := client.MkdirAll(ctx, volID, "a/b/c/d"); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}

	info, err := client.StatPath(ctx, volID, "a/b/c/d")
	if err != nil {
		t.Fatalf("StatPath: %v", err)
	}
	if !info.IsDir {
		t.Fatal("expected directory")
	}
}

// ---------------------------------------------------------------------------
// TarCreate
// ---------------------------------------------------------------------------

func TestFileOps_TarCreate(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	// Create files inside a subdirectory to tar.
	if err := client.WriteFile(ctx, volID, "tartest/f1.txt", []byte("one"), 0644); err != nil {
		t.Fatalf("WriteFile f1: %v", err)
	}
	if err := client.WriteFile(ctx, volID, "tartest/f2.txt", []byte("two"), 0644); err != nil {
		t.Fatalf("WriteFile f2: %v", err)
	}

	tarData, err := client.TarCreate(ctx, volID, "tartest")
	if err != nil {
		t.Fatalf("TarCreate: %v", err)
	}
	if len(tarData) == 0 {
		t.Fatal("TarCreate returned empty data")
	}

	// Parse the tar and verify entries.
	tr := tar.NewReader(bytes.NewReader(tarData))
	found := make(map[string]bool)
	for {
		hdr, err := tr.Next()
		if err != nil {
			break
		}
		found[filepath.Base(hdr.Name)] = true
	}
	for _, want := range []string{"f1.txt", "f2.txt"} {
		if !found[want] {
			t.Errorf("tar missing entry %q; have %v", want, found)
		}
	}
}

// ---------------------------------------------------------------------------
// TarExtract
// ---------------------------------------------------------------------------

func TestFileOps_TarExtract(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	tarData := buildTestTar(t, map[string]string{
		"readme.md": "# Test",
	})

	if err := client.TarExtract(ctx, volID, "extracted", tarData); err != nil {
		t.Fatalf("TarExtract: %v", err)
	}

	data, err := client.ReadFile(ctx, volID, "extracted/readme.md")
	if err != nil {
		t.Fatalf("ReadFile after extract: %v", err)
	}
	if string(data) != "# Test" {
		t.Fatalf("content = %q, want %q", string(data), "# Test")
	}
}

// ---------------------------------------------------------------------------
// Path traversal (WriteFile)
// ---------------------------------------------------------------------------

func TestFileOps_PathTraversal(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	err := client.WriteFile(ctx, volID, "../../etc/passwd", []byte("evil"), 0644)
	if err == nil {
		t.Fatal("expected error for path traversal")
	}

	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status, got %T: %v", err, err)
	}
	if st.Code() != codes.InvalidArgument {
		t.Fatalf("expected InvalidArgument, got %s", st.Code())
	}
}

// ---------------------------------------------------------------------------
// TarExtract with path traversal in entries
// ---------------------------------------------------------------------------

func TestFileOps_TarExtract_PathTraversal(t *testing.T) {
	pool := getPoolPath(t)
	volID := uniqueName("fileops")
	volDir := filepath.Join(pool, "volumes", volID)
	os.MkdirAll(volDir, 0755)
	t.Cleanup(func() { os.RemoveAll(volDir) })

	addr := startFileOpsServer(t, pool)
	client := connectFileOpsClient(t, addr)
	ctx := context.Background()

	// Build a tar with a malicious path-traversal entry.
	tarData := buildTestTar(t, map[string]string{
		"../../evil.txt": "malicious content",
	})

	// The server should silently skip bad entries (not error out).
	if err := client.TarExtract(ctx, volID, "safe", tarData); err != nil {
		t.Fatalf("TarExtract: %v", err)
	}

	// Verify the malicious file does NOT exist relative to the pool.
	evilPath := filepath.Join(pool, "evil.txt")
	if _, err := os.Stat(evilPath); err == nil {
		t.Fatalf("evil.txt should not exist at %s", evilPath)
	}

	// Verify no files were extracted into "safe" (all entries were skipped).
	entries, err := client.ListDir(ctx, volID, "safe", false)
	if err != nil {
		// The "safe" directory may still exist but be empty, or may not exist
		// at all. Either is acceptable.
		return
	}
	if len(entries) > 0 {
		t.Fatalf("expected no files in safe/, got %d entries", len(entries))
	}
}
