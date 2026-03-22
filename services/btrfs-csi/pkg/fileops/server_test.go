package fileops

import (
	"archive/tar"
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// makeDec returns a gRPC-style decode function that unmarshals req into the
// target via JSON round-trip, matching the jsonCodec used by the real server.
func makeDec(req interface{}) func(interface{}) error {
	data, _ := json.Marshal(req)
	return func(v interface{}) error { return json.Unmarshal(data, v) }
}

// setupVolume creates the volumes/{volID} directory tree inside poolPath and
// returns the absolute path to the volume root.
func setupVolume(t *testing.T, poolPath, volID string) string {
	t.Helper()
	volDir := filepath.Join(poolPath, "volumes", volID)
	if err := os.MkdirAll(volDir, 0755); err != nil {
		t.Fatalf("setup volume dir: %v", err)
	}
	return volDir
}

// requireCode asserts that err carries the expected gRPC status code.
func requireCode(t *testing.T, err error, want codes.Code) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected error with code %v, got nil", want)
	}
	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status error, got: %v", err)
	}
	if st.Code() != want {
		t.Errorf("expected code %v, got %v (msg: %s)", want, st.Code(), st.Message())
	}
}

// ctx is a short-hand used throughout the tests.
var ctx = context.Background()

// nilInterceptor satisfies the grpc.UnaryServerInterceptor parameter.
var nilInterceptor grpc.UnaryServerInterceptor

// ---------------------------------------------------------------------------
// volumePath
// ---------------------------------------------------------------------------

func TestVolumePath_Valid(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)

	got, err := s.volumePath("vol1", "src/main.go")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := filepath.Join(pool, "volumes", "vol1", "src/main.go")
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestVolumePath_TraversalBlocked(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)

	cases := []struct {
		name     string
		volumeID string
		path     string
	}{
		{"dot-dot-etc-passwd", "vol1", "../../etc/passwd"},
		{"bare-dot-dot", "vol1", ".."},
		{"dot-dot-slash", "vol1", "../"},
		{"nested-traversal", "vol1", "a/b/../../../../etc/shadow"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := s.volumePath(tc.volumeID, tc.path)
			if err == nil {
				t.Errorf("expected path traversal error for path %q, got nil", tc.path)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// ReadFile
// ---------------------------------------------------------------------------

func TestReadFile_Success(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	want := []byte("hello world")
	if err := os.WriteFile(filepath.Join(volDir, "test.txt"), want, 0644); err != nil {
		t.Fatal(err)
	}

	resp, err := s.handleReadFile(nil, ctx, makeDec(ReadFileRequest{VolumeID: "v1", Path: "test.txt"}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	got := resp.(*ReadFileResponse).Data
	if !bytes.Equal(got, want) {
		t.Errorf("data mismatch: got %q, want %q", got, want)
	}
}

func TestReadFile_NotFound(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	setupVolume(t, pool, "v1")

	_, err := s.handleReadFile(nil, ctx, makeDec(ReadFileRequest{VolumeID: "v1", Path: "nope.txt"}), nilInterceptor)
	requireCode(t, err, codes.NotFound)
}

func TestReadFile_MissingArgs(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)

	cases := []struct {
		name string
		req  ReadFileRequest
	}{
		{"empty-volume", ReadFileRequest{VolumeID: "", Path: "f.txt"}},
		{"empty-path", ReadFileRequest{VolumeID: "v1", Path: ""}},
		{"both-empty", ReadFileRequest{}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := s.handleReadFile(nil, ctx, makeDec(tc.req), nilInterceptor)
			requireCode(t, err, codes.InvalidArgument)
		})
	}
}

func TestReadFile_PathTraversal(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	setupVolume(t, pool, "v1")

	_, err := s.handleReadFile(nil, ctx, makeDec(ReadFileRequest{VolumeID: "v1", Path: "../../etc/passwd"}), nilInterceptor)
	requireCode(t, err, codes.InvalidArgument)
}

// ---------------------------------------------------------------------------
// WriteFile
// ---------------------------------------------------------------------------

func TestWriteFile_NewFile(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	data := []byte("new content")
	_, err := s.handleWriteFile(nil, ctx, makeDec(WriteFileRequest{
		VolumeID: "v1", Path: "new.txt", Data: data, Mode: 0644,
	}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(volDir, "new.txt"))
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if !bytes.Equal(got, data) {
		t.Errorf("got %q, want %q", got, data)
	}
}

func TestWriteFile_Overwrite(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	original := []byte("original")
	if err := os.WriteFile(filepath.Join(volDir, "f.txt"), original, 0644); err != nil {
		t.Fatal(err)
	}

	replacement := []byte("replaced")
	_, err := s.handleWriteFile(nil, ctx, makeDec(WriteFileRequest{
		VolumeID: "v1", Path: "f.txt", Data: replacement, Mode: 0644,
	}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(volDir, "f.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, replacement) {
		t.Errorf("got %q, want %q", got, replacement)
	}
}

func TestWriteFile_DefaultMode(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	_, err := s.handleWriteFile(nil, ctx, makeDec(WriteFileRequest{
		VolumeID: "v1", Path: "default_mode.txt", Data: []byte("x"), Mode: 0,
	}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	info, err := os.Stat(filepath.Join(volDir, "default_mode.txt"))
	if err != nil {
		t.Fatal(err)
	}
	// Mode 0 should default to 0644. Mask with 0777 to ignore OS-specific bits.
	got := info.Mode().Perm()
	if got != 0644 {
		t.Errorf("mode = %04o, want 0644", got)
	}
}

func TestWriteFile_CreatesParentDirs(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	_, err := s.handleWriteFile(nil, ctx, makeDec(WriteFileRequest{
		VolumeID: "v1", Path: "a/b/c/deep.txt", Data: []byte("deep"), Mode: 0644,
	}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(volDir, "a", "b", "c", "deep.txt"))
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if string(got) != "deep" {
		t.Errorf("got %q, want %q", got, "deep")
	}
}

func TestWriteFile_MissingArgs(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)

	cases := []struct {
		name string
		req  WriteFileRequest
	}{
		{"empty-volume", WriteFileRequest{VolumeID: "", Path: "f.txt", Data: []byte("x")}},
		{"empty-path", WriteFileRequest{VolumeID: "v1", Path: "", Data: []byte("x")}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := s.handleWriteFile(nil, ctx, makeDec(tc.req), nilInterceptor)
			requireCode(t, err, codes.InvalidArgument)
		})
	}
}

// ---------------------------------------------------------------------------
// ListDir
// ---------------------------------------------------------------------------

func TestListDir_NonRecursive(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	// Create files and a subdir.
	if err := os.WriteFile(filepath.Join(volDir, "a.txt"), []byte("a"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(volDir, "b.txt"), []byte("b"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(volDir, "subdir"), 0755); err != nil {
		t.Fatal(err)
	}

	resp, err := s.handleListDir(nil, ctx, makeDec(ListDirRequest{VolumeID: "v1", Path: "."}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	entries := resp.(*ListDirResponse).Entries
	if len(entries) != 3 {
		t.Fatalf("expected 3 entries, got %d", len(entries))
	}

	names := map[string]bool{}
	for _, e := range entries {
		names[e.Name] = true
	}
	for _, want := range []string{"a.txt", "b.txt", "subdir"} {
		if !names[want] {
			t.Errorf("missing entry %q", want)
		}
	}
}

func TestListDir_Recursive(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	if err := os.MkdirAll(filepath.Join(volDir, "d1", "d2"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(volDir, "root.txt"), []byte("r"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(volDir, "d1", "d2", "nested.txt"), []byte("n"), 0644); err != nil {
		t.Fatal(err)
	}

	resp, err := s.handleListDir(nil, ctx, makeDec(ListDirRequest{VolumeID: "v1", Path: ".", Recursive: true}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	entries := resp.(*ListDirResponse).Entries

	// Recursive walk from volume root includes: "." (the volume root), "d1", "d1/d2",
	// "d1/d2/nested.txt", "root.txt". That is at least 5 entries.
	if len(entries) < 5 {
		t.Errorf("expected at least 5 entries in recursive walk, got %d", len(entries))
	}

	paths := map[string]bool{}
	for _, e := range entries {
		paths[e.Path] = true
	}
	for _, want := range []string{"d1", filepath.Join("d1", "d2"), filepath.Join("d1", "d2", "nested.txt"), "root.txt"} {
		if !paths[want] {
			t.Errorf("missing path %q in recursive listing", want)
		}
	}
}

func TestListDir_EmptyDir(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	setupVolume(t, pool, "v1")

	resp, err := s.handleListDir(nil, ctx, makeDec(ListDirRequest{VolumeID: "v1", Path: "."}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	entries := resp.(*ListDirResponse).Entries
	if len(entries) != 0 {
		t.Errorf("expected 0 entries for empty dir, got %d", len(entries))
	}
}

func TestListDir_NotFound(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	setupVolume(t, pool, "v1")

	_, err := s.handleListDir(nil, ctx, makeDec(ListDirRequest{VolumeID: "v1", Path: "nonexistent"}), nilInterceptor)
	requireCode(t, err, codes.NotFound)
}

func TestListDir_DefaultPath(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	if err := os.WriteFile(filepath.Join(volDir, "hello.txt"), []byte("hi"), 0644); err != nil {
		t.Fatal(err)
	}

	// Empty path should default to "." and list volume root.
	resp, err := s.handleListDir(nil, ctx, makeDec(ListDirRequest{VolumeID: "v1", Path: ""}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	entries := resp.(*ListDirResponse).Entries
	if len(entries) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(entries))
	}
	if entries[0].Name != "hello.txt" {
		t.Errorf("entry name = %q, want %q", entries[0].Name, "hello.txt")
	}
}

// ---------------------------------------------------------------------------
// StatPath
// ---------------------------------------------------------------------------

func TestStatPath_File(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	data := []byte("stat me")
	if err := os.WriteFile(filepath.Join(volDir, "info.txt"), data, 0644); err != nil {
		t.Fatal(err)
	}

	resp, err := s.handleStatPath(nil, ctx, makeDec(StatPathRequest{VolumeID: "v1", Path: "info.txt"}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	fi := resp.(*FileInfoResponse).Info

	if fi.Name != "info.txt" {
		t.Errorf("Name = %q, want %q", fi.Name, "info.txt")
	}
	if fi.Size != int64(len(data)) {
		t.Errorf("Size = %d, want %d", fi.Size, len(data))
	}
	if fi.IsDir {
		t.Error("expected IsDir=false for file")
	}
	if fi.Path != "info.txt" {
		t.Errorf("Path = %q, want %q", fi.Path, "info.txt")
	}
}

func TestStatPath_Directory(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	if err := os.MkdirAll(filepath.Join(volDir, "mydir"), 0755); err != nil {
		t.Fatal(err)
	}

	resp, err := s.handleStatPath(nil, ctx, makeDec(StatPathRequest{VolumeID: "v1", Path: "mydir"}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	fi := resp.(*FileInfoResponse).Info

	if !fi.IsDir {
		t.Error("expected IsDir=true for directory")
	}
	if fi.Name != "mydir" {
		t.Errorf("Name = %q, want %q", fi.Name, "mydir")
	}
}

func TestStatPath_NotFound(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	setupVolume(t, pool, "v1")

	_, err := s.handleStatPath(nil, ctx, makeDec(StatPathRequest{VolumeID: "v1", Path: "ghost"}), nilInterceptor)
	requireCode(t, err, codes.NotFound)
}

// ---------------------------------------------------------------------------
// DeletePath
// ---------------------------------------------------------------------------

func TestDeletePath_File(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	target := filepath.Join(volDir, "bye.txt")
	if err := os.WriteFile(target, []byte("gone"), 0644); err != nil {
		t.Fatal(err)
	}

	_, err := s.handleDeletePath(nil, ctx, makeDec(DeletePathRequest{VolumeID: "v1", Path: "bye.txt"}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if _, statErr := os.Stat(target); !os.IsNotExist(statErr) {
		t.Error("file still exists after delete")
	}
}

func TestDeletePath_Directory(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	dir := filepath.Join(volDir, "tree", "branch")
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "leaf.txt"), []byte("leaf"), 0644); err != nil {
		t.Fatal(err)
	}

	_, err := s.handleDeletePath(nil, ctx, makeDec(DeletePathRequest{VolumeID: "v1", Path: "tree"}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if _, statErr := os.Stat(filepath.Join(volDir, "tree")); !os.IsNotExist(statErr) {
		t.Error("directory still exists after delete")
	}
}

// ---------------------------------------------------------------------------
// MkdirAll
// ---------------------------------------------------------------------------

func TestMkdirAll_Nested(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	_, err := s.handleMkdirAll(nil, ctx, makeDec(MkdirAllRequest{VolumeID: "v1", Path: "a/b/c/d"}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	info, statErr := os.Stat(filepath.Join(volDir, "a", "b", "c", "d"))
	if statErr != nil {
		t.Fatalf("stat nested dir: %v", statErr)
	}
	if !info.IsDir() {
		t.Error("expected directory, got file")
	}
}

// ---------------------------------------------------------------------------
// TarCreate
// ---------------------------------------------------------------------------

func TestTarCreate_Directory(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	// Build a directory tree to tar.
	if err := os.MkdirAll(filepath.Join(volDir, "proj", "sub"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(volDir, "proj", "readme.txt"), []byte("hello"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(volDir, "proj", "sub", "data.bin"), []byte{0x01, 0x02}, 0644); err != nil {
		t.Fatal(err)
	}

	resp, err := s.handleTarCreate(nil, ctx, makeDec(TarRequest{VolumeID: "v1", Path: "proj"}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	tarData := resp.(*TarResponse).Data
	if len(tarData) == 0 {
		t.Fatal("tar data is empty")
	}

	// Read back the tar to verify entries.
	tr := tar.NewReader(bytes.NewReader(tarData))
	found := map[string]bool{}
	for {
		hdr, readErr := tr.Next()
		if readErr != nil {
			break
		}
		found[hdr.Name] = true
	}

	for _, want := range []string{"readme.txt", "sub", filepath.Join("sub", "data.bin")} {
		if !found[want] {
			t.Errorf("tar missing entry %q, found: %v", want, found)
		}
	}
}

// ---------------------------------------------------------------------------
// TarExtract
// ---------------------------------------------------------------------------

func TestTarExtract_Success(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	volDir := setupVolume(t, pool, "v1")

	// Build a tar with two files and a directory.
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)

	tw.WriteHeader(&tar.Header{Name: "dir/", Typeflag: tar.TypeDir, Mode: 0755})

	fileContent := []byte("extracted content")
	tw.WriteHeader(&tar.Header{
		Name:     "dir/file.txt",
		Typeflag: tar.TypeReg,
		Mode:     0644,
		Size:     int64(len(fileContent)),
	})
	tw.Write(fileContent)

	rootContent := []byte("root file")
	tw.WriteHeader(&tar.Header{
		Name:     "root.txt",
		Typeflag: tar.TypeReg,
		Mode:     0644,
		Size:     int64(len(rootContent)),
	})
	tw.Write(rootContent)

	tw.Close()

	_, err := s.handleTarExtract(nil, ctx, makeDec(TarRequest{
		VolumeID: "v1", Path: "dest", Data: buf.Bytes(),
	}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify extracted files.
	got, err := os.ReadFile(filepath.Join(volDir, "dest", "dir", "file.txt"))
	if err != nil {
		t.Fatalf("read extracted file: %v", err)
	}
	if !bytes.Equal(got, fileContent) {
		t.Errorf("file content = %q, want %q", got, fileContent)
	}

	got2, err := os.ReadFile(filepath.Join(volDir, "dest", "root.txt"))
	if err != nil {
		t.Fatalf("read root.txt: %v", err)
	}
	if !bytes.Equal(got2, rootContent) {
		t.Errorf("root.txt content = %q, want %q", got2, rootContent)
	}
}

func TestTarExtract_TraversalInEntries(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	setupVolume(t, pool, "v1")

	// Build a tar with a path-traversal entry and a legitimate entry.
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)

	evilData := []byte("evil")
	tw.WriteHeader(&tar.Header{
		Name:     "../../evil.txt",
		Typeflag: tar.TypeReg,
		Mode:     0644,
		Size:     int64(len(evilData)),
	})
	tw.Write(evilData)

	goodData := []byte("good")
	tw.WriteHeader(&tar.Header{
		Name:     "safe.txt",
		Typeflag: tar.TypeReg,
		Mode:     0644,
		Size:     int64(len(goodData)),
	})
	tw.Write(goodData)

	tw.Close()

	_, err := s.handleTarExtract(nil, ctx, makeDec(TarRequest{
		VolumeID: "v1", Path: "out", Data: buf.Bytes(),
	}), nilInterceptor)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// The evil entry should have been silently skipped.
	evilTarget := filepath.Join(pool, "evil.txt")
	if _, statErr := os.Stat(evilTarget); !os.IsNotExist(statErr) {
		t.Error("traversal entry was not skipped: evil.txt exists outside volume")
	}

	// The safe entry should exist.
	volDir := filepath.Join(pool, "volumes", "v1")
	safeTarget := filepath.Join(volDir, "out", "safe.txt")
	got, err := os.ReadFile(safeTarget)
	if err != nil {
		t.Fatalf("safe file missing: %v", err)
	}
	if !bytes.Equal(got, goodData) {
		t.Errorf("safe.txt content = %q, want %q", got, goodData)
	}
}

func TestTarExtract_SizeLimitExceeded(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	setupVolume(t, pool, "v1")

	// Build a tar with a header claiming Size > 1<<30 (1GB limit).
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	tw.WriteHeader(&tar.Header{
		Name:     "huge.bin",
		Typeflag: tar.TypeReg,
		Mode:     0644,
		Size:     (1 << 30) + 1, // 1GB + 1 byte
	})
	// We don't write actual data matching the size; the handler checks
	// header.Size before reading, so this is sufficient.
	tw.Close()

	_, err := s.handleTarExtract(nil, ctx, makeDec(TarRequest{
		VolumeID: "v1", Path: "big", Data: buf.Bytes(),
	}), nilInterceptor)
	requireCode(t, err, codes.InvalidArgument)
}

func TestTarExtract_EmptyData(t *testing.T) {
	pool := t.TempDir()
	s := NewServer(pool, nil)
	setupVolume(t, pool, "v1")

	_, err := s.handleTarExtract(nil, ctx, makeDec(TarRequest{
		VolumeID: "v1", Path: "target", Data: nil,
	}), nilInterceptor)
	requireCode(t, err, codes.InvalidArgument)
}
