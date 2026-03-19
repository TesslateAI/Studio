package fileops

import (
	"archive/tar"
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"net"
	"os"
	"path/filepath"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/encoding"
	"google.golang.org/grpc/status"
	"k8s.io/klog/v2"
)

func init() {
	encoding.RegisterCodec(jsonCodec{})
}

// Server exposes file operations over gRPC on port 9742.
// Access is restricted by NetworkPolicy to the tesslate namespace.
type Server struct {
	poolPath string
	srv      *grpc.Server
}

// TLSConfig holds paths for mTLS certificate files.
type TLSConfig struct {
	CertFile string
	KeyFile  string
	CAFile   string
}

// NewServer creates a FileOps server that operates on the given btrfs pool.
func NewServer(poolPath string) *Server {
	return &Server{poolPath: poolPath}
}

// Start begins serving FileOps gRPC on the given address (e.g., ":9742").
func (s *Server) Start(addr string, tlsCfg *TLSConfig) error {
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("fileops listen on %s: %w", addr, err)
	}

	var opts []grpc.ServerOption
	if creds, tlsErr := loadServerTLS(tlsCfg); tlsErr != nil {
		return fmt.Errorf("fileops TLS: %w", tlsErr)
	} else if creds != nil {
		opts = append(opts, grpc.Creds(creds))
		klog.Info("FileOps gRPC server using mTLS")
	}

	// Limit message size to 64MB for large file transfers.
	// ForceServerCodec makes all RPCs use JSON regardless of content-type.
	opts = append(opts,
		grpc.MaxRecvMsgSize(64*1024*1024),
		grpc.MaxSendMsgSize(64*1024*1024),
		grpc.ForceServerCodec(jsonCodec{}),
	)

	s.srv = grpc.NewServer(opts...)
	registerFileOpsServer(s.srv, s)

	klog.Infof("FileOps gRPC server listening on %s", addr)
	return s.srv.Serve(listener)
}

func loadServerTLS(cfg *TLSConfig) (credentials.TransportCredentials, error) {
	if cfg == nil || cfg.CertFile == "" {
		return nil, nil
	}
	if _, err := os.Stat(cfg.CertFile); os.IsNotExist(err) {
		return nil, nil
	}

	cert, err := tls.LoadX509KeyPair(cfg.CertFile, cfg.KeyFile)
	if err != nil {
		return nil, fmt.Errorf("load key pair: %w", err)
	}

	tlsConfig := &tls.Config{
		Certificates: []tls.Certificate{cert},
		MinVersion:   tls.VersionTLS13,
	}

	if cfg.CAFile != "" {
		caPEM, err := os.ReadFile(cfg.CAFile)
		if err != nil {
			return nil, fmt.Errorf("read CA file: %w", err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(caPEM) {
			return nil, fmt.Errorf("failed to parse CA certificate")
		}
		tlsConfig.ClientCAs = pool
		tlsConfig.ClientAuth = tls.RequireAndVerifyClientCert
	}

	return credentials.NewTLS(tlsConfig), nil
}

// Stop gracefully stops the server.
func (s *Server) Stop() {
	if s.srv != nil {
		s.srv.GracefulStop()
	}
}

// volumePath returns the safe absolute path to a file within a volume.
func (s *Server) volumePath(volumeID, filePath string) (string, error) {
	volDir := filepath.Join(s.poolPath, "volumes", volumeID)
	full := filepath.Join(volDir, filePath)
	clean := filepath.Clean(full)
	volClean := filepath.Clean(volDir)

	if !strings.HasPrefix(clean, volClean+string(filepath.Separator)) && clean != volClean {
		return "", fmt.Errorf("path traversal detected: %q resolves outside volume %q", filePath, volumeID)
	}
	return clean, nil
}

// --- Request/response types ---

type (
	ReadFileRequest struct {
		VolumeID string `json:"volume_id"`
		Path     string `json:"path"`
	}
	ReadFileResponse struct {
		Data []byte `json:"data"`
	}

	WriteFileRequest struct {
		VolumeID string `json:"volume_id"`
		Path     string `json:"path"`
		Data     []byte `json:"data"`
		Mode     uint32 `json:"mode"`
		Uid      int    `json:"uid"`
		Gid      int    `json:"gid"`
	}

	ListDirRequest struct {
		VolumeID  string `json:"volume_id"`
		Path      string `json:"path"`
		Recursive bool   `json:"recursive"`
	}
	ListDirResponse struct {
		Entries []FileInfo `json:"entries"`
	}

	StatPathRequest struct {
		VolumeID string `json:"volume_id"`
		Path     string `json:"path"`
	}

	DeletePathRequest struct {
		VolumeID string `json:"volume_id"`
		Path     string `json:"path"`
	}

	MkdirAllRequest struct {
		VolumeID string `json:"volume_id"`
		Path     string `json:"path"`
		Uid      int    `json:"uid"`
		Gid      int    `json:"gid"`
	}

	TarRequest struct {
		VolumeID string `json:"volume_id"`
		Path     string `json:"path"`
		Data     []byte `json:"data,omitempty"`
		Uid      int    `json:"uid"`
		Gid      int    `json:"gid"`
	}
	TarResponse struct {
		Data []byte `json:"data"`
	}

	FileInfoResponse struct {
		Info FileInfo `json:"info"`
	}

	Empty struct{}

	ListTreeRequest struct {
		VolumeID          string   `json:"volume_id"`
		Path              string   `json:"path"`
		ExcludeDirs       []string `json:"exclude_dirs"`
		ExcludeFiles      []string `json:"exclude_files"`
		ExcludeExtensions []string `json:"exclude_extensions"`
	}
	ListTreeResponse struct {
		Entries []FileInfo `json:"entries"`
	}

	ReadFilesRequest struct {
		VolumeID    string   `json:"volume_id"`
		Paths       []string `json:"paths"`
		MaxFileSize int64    `json:"max_file_size"`
	}
	ReadFilesResponse struct {
		Files  []FileContent `json:"files"`
		Errors []string      `json:"errors"`
	}
)

// chownNewParents chowns directories from child up to (but not including) root.
// Best-effort: stops on first error or after 256 iterations.
func chownNewParents(dir, root string, uid, gid int) {
	dir = filepath.Clean(dir)
	root = filepath.Clean(root)
	for i := 0; i < 256 && dir != root && strings.HasPrefix(dir, root+string(filepath.Separator)); i++ {
		if err := os.Chown(dir, uid, gid); err != nil {
			break
		}
		dir = filepath.Dir(dir)
	}
}

type jsonCodec struct{}

func (jsonCodec) Marshal(v interface{}) ([]byte, error)     { return json.Marshal(v) }
func (jsonCodec) Unmarshal(data []byte, v interface{}) error { return json.Unmarshal(data, v) }
func (jsonCodec) Name() string                              { return "json" }

// fileOpsServiceServer is the interface type required by gRPC's RegisterService.
type fileOpsServiceServer interface{}

func registerFileOpsServer(srv *grpc.Server, s *Server) {
	srv.RegisterService(&grpc.ServiceDesc{
		ServiceName: "fileops.FileOps",
		HandlerType: (*fileOpsServiceServer)(nil),
		Methods: []grpc.MethodDesc{
			{MethodName: "ReadFile", Handler: s.handleReadFile},
			{MethodName: "WriteFile", Handler: s.handleWriteFile},
			{MethodName: "ListDir", Handler: s.handleListDir},
			{MethodName: "ListTree", Handler: s.handleListTree},
			{MethodName: "StatPath", Handler: s.handleStatPath},
			{MethodName: "DeletePath", Handler: s.handleDeletePath},
			{MethodName: "MkdirAll", Handler: s.handleMkdirAll},
			{MethodName: "ReadFiles", Handler: s.handleReadFiles},
			{MethodName: "TarCreate", Handler: s.handleTarCreate},
			{MethodName: "TarExtract", Handler: s.handleTarExtract},
		},
		Streams: []grpc.StreamDesc{},
	}, s)
}

func (s *Server) handleReadFile(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req ReadFileRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.Path == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and path are required")
	}

	fullPath, err := s.volumePath(req.VolumeID, req.Path)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "%v", err)
	}

	data, err := os.ReadFile(fullPath)
	if os.IsNotExist(err) {
		return nil, status.Errorf(codes.NotFound, "file not found: %s", req.Path)
	} else if err != nil {
		return nil, status.Errorf(codes.Internal, "read file: %v", err)
	}

	return &ReadFileResponse{Data: data}, nil
}

func (s *Server) handleWriteFile(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req WriteFileRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.Path == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and path are required")
	}

	fullPath, err := s.volumePath(req.VolumeID, req.Path)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "%v", err)
	}

	// Ensure parent directory exists.
	dir := filepath.Dir(fullPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, status.Errorf(codes.Internal, "create parent dir: %v", err)
	}

	mode := fs.FileMode(req.Mode)
	if mode == 0 {
		mode = 0644
	}

	if err := os.WriteFile(fullPath, req.Data, mode); err != nil {
		return nil, status.Errorf(codes.Internal, "write file: %v", err)
	}

	if req.Uid > 0 || req.Gid > 0 {
		if err := os.Chown(fullPath, req.Uid, req.Gid); err != nil {
			return nil, status.Errorf(codes.Internal, "chown file: %v", err)
		}
		volDir := filepath.Join(s.poolPath, "volumes", req.VolumeID)
		chownNewParents(dir, volDir, req.Uid, req.Gid)
	}

	return &Empty{}, nil
}

func (s *Server) handleListDir(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req ListDirRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	dirPath := req.Path
	if dirPath == "" {
		dirPath = "."
	}

	fullPath, err := s.volumePath(req.VolumeID, dirPath)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "%v", err)
	}

	var entries []FileInfo

	if req.Recursive {
		volBase, _ := s.volumePath(req.VolumeID, ".")
		err = filepath.WalkDir(fullPath, func(path string, d fs.DirEntry, walkErr error) error {
			if walkErr != nil {
				return nil // Skip entries we can't read.
			}
			info, statErr := d.Info()
			if statErr != nil {
				return nil
			}
			relPath, _ := filepath.Rel(volBase, path)
			entries = append(entries, FileInfo{
				Name:    d.Name(),
				Path:    relPath,
				Size:    info.Size(),
				IsDir:   d.IsDir(),
				ModTime: info.ModTime().Unix(),
				Mode:    uint32(info.Mode()),
			})
			return nil
		})
	} else {
		dirEntries, readErr := os.ReadDir(fullPath)
		if readErr != nil {
			if os.IsNotExist(readErr) {
				return nil, status.Errorf(codes.NotFound, "directory not found: %s", dirPath)
			}
			return nil, status.Errorf(codes.Internal, "read dir: %v", readErr)
		}
		for _, d := range dirEntries {
			info, statErr := d.Info()
			if statErr != nil {
				continue
			}
			entries = append(entries, FileInfo{
				Name:    d.Name(),
				Path:    filepath.Join(dirPath, d.Name()),
				Size:    info.Size(),
				IsDir:   d.IsDir(),
				ModTime: info.ModTime().Unix(),
				Mode:    uint32(info.Mode()),
			})
		}
		err = nil
	}

	if err != nil {
		return nil, status.Errorf(codes.Internal, "list dir: %v", err)
	}

	return &ListDirResponse{Entries: entries}, nil
}

func (s *Server) handleStatPath(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req StatPathRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.Path == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and path are required")
	}

	fullPath, err := s.volumePath(req.VolumeID, req.Path)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "%v", err)
	}

	info, err := os.Stat(fullPath)
	if os.IsNotExist(err) {
		return nil, status.Errorf(codes.NotFound, "path not found: %s", req.Path)
	} else if err != nil {
		return nil, status.Errorf(codes.Internal, "stat: %v", err)
	}

	return &FileInfoResponse{Info: FileInfo{
		Name:    info.Name(),
		Path:    req.Path,
		Size:    info.Size(),
		IsDir:   info.IsDir(),
		ModTime: info.ModTime().Unix(),
		Mode:    uint32(info.Mode()),
	}}, nil
}

func (s *Server) handleDeletePath(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req DeletePathRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.Path == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and path are required")
	}

	fullPath, err := s.volumePath(req.VolumeID, req.Path)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "%v", err)
	}

	if err := os.RemoveAll(fullPath); err != nil {
		return nil, status.Errorf(codes.Internal, "delete: %v", err)
	}

	return &Empty{}, nil
}

func (s *Server) handleMkdirAll(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req MkdirAllRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.Path == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and path are required")
	}

	fullPath, err := s.volumePath(req.VolumeID, req.Path)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "%v", err)
	}

	if err := os.MkdirAll(fullPath, 0755); err != nil {
		return nil, status.Errorf(codes.Internal, "mkdir: %v", err)
	}

	if req.Uid > 0 || req.Gid > 0 {
		volDir := filepath.Join(s.poolPath, "volumes", req.VolumeID)
		chownNewParents(fullPath, volDir, req.Uid, req.Gid)
	}

	return &Empty{}, nil
}

func (s *Server) handleListTree(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req ListTreeRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}

	walkPath := req.Path
	if walkPath == "" {
		walkPath = "."
	}

	fullPath, err := s.volumePath(req.VolumeID, walkPath)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "%v", err)
	}

	// Build lookup sets for O(1) filtering.
	excludeDirs := make(map[string]struct{}, len(req.ExcludeDirs))
	for _, d := range req.ExcludeDirs {
		excludeDirs[d] = struct{}{}
	}
	excludeFiles := make(map[string]struct{}, len(req.ExcludeFiles))
	for _, f := range req.ExcludeFiles {
		excludeFiles[f] = struct{}{}
	}
	excludeExts := make(map[string]struct{}, len(req.ExcludeExtensions))
	for _, e := range req.ExcludeExtensions {
		excludeExts[e] = struct{}{}
	}

	var entries []FileInfo

	err = filepath.WalkDir(fullPath, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return nil // Skip entries we can't read.
		}

		relPath, _ := filepath.Rel(fullPath, path)
		if relPath == "." {
			return nil // Skip root entry.
		}

		name := d.Name()

		// Skip excluded directories (and their entire subtree).
		if d.IsDir() {
			if _, ok := excludeDirs[name]; ok {
				return filepath.SkipDir
			}
		} else {
			// Skip excluded filenames.
			if _, ok := excludeFiles[name]; ok {
				return nil
			}
			// Skip excluded extensions.
			if idx := strings.LastIndex(name, "."); idx >= 0 {
				ext := name[idx+1:]
				if _, ok := excludeExts[ext]; ok {
					return nil
				}
			}
		}

		info, statErr := d.Info()
		if statErr != nil {
			return nil
		}

		entries = append(entries, FileInfo{
			Name:    name,
			Path:    relPath,
			Size:    info.Size(),
			IsDir:   d.IsDir(),
			ModTime: info.ModTime().Unix(),
			Mode:    uint32(info.Mode()),
		})
		return nil
	})

	if err != nil {
		return nil, status.Errorf(codes.Internal, "list tree: %v", err)
	}

	return &ListTreeResponse{Entries: entries}, nil
}

func (s *Server) handleReadFiles(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req ReadFilesRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id is required")
	}
	if len(req.Paths) == 0 {
		return &ReadFilesResponse{}, nil
	}

	var files []FileContent
	var errors []string

	for _, p := range req.Paths {
		fullPath, err := s.volumePath(req.VolumeID, p)
		if err != nil {
			errors = append(errors, p)
			continue
		}

		info, statErr := os.Stat(fullPath)
		if statErr != nil {
			errors = append(errors, p)
			continue
		}

		// Skip files larger than max size (if limit set).
		if req.MaxFileSize > 0 && info.Size() > req.MaxFileSize {
			errors = append(errors, p)
			continue
		}

		data, readErr := os.ReadFile(fullPath)
		if readErr != nil {
			errors = append(errors, p)
			continue
		}

		files = append(files, FileContent{
			Path: p,
			Data: data,
			Size: info.Size(),
		})
	}

	return &ReadFilesResponse{Files: files, Errors: errors}, nil
}

func (s *Server) handleTarCreate(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req TarRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.Path == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and path are required")
	}

	fullPath, err := s.volumePath(req.VolumeID, req.Path)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "%v", err)
	}

	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)

	err = filepath.WalkDir(fullPath, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return nil
		}
		info, statErr := d.Info()
		if statErr != nil {
			return nil
		}

		relPath, _ := filepath.Rel(fullPath, path)
		if relPath == "." {
			return nil
		}

		header, headerErr := tar.FileInfoHeader(info, "")
		if headerErr != nil {
			return headerErr
		}
		header.Name = relPath

		if writeErr := tw.WriteHeader(header); writeErr != nil {
			return writeErr
		}

		if !d.IsDir() {
			file, openErr := os.Open(path)
			if openErr != nil {
				return openErr
			}
			defer file.Close()
			if _, copyErr := io.Copy(tw, file); copyErr != nil {
				return copyErr
			}
		}
		return nil
	})

	if err != nil {
		return nil, status.Errorf(codes.Internal, "create tar: %v", err)
	}

	if err := tw.Close(); err != nil {
		return nil, status.Errorf(codes.Internal, "finalize tar: %v", err)
	}

	return &TarResponse{Data: buf.Bytes()}, nil
}

func (s *Server) handleTarExtract(_ interface{}, ctx context.Context, dec func(interface{}) error, _ grpc.UnaryServerInterceptor) (interface{}, error) {
	var req TarRequest
	if err := dec(&req); err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "decode: %v", err)
	}
	if req.VolumeID == "" || req.Path == "" {
		return nil, status.Error(codes.InvalidArgument, "volume_id and path are required")
	}
	if len(req.Data) == 0 {
		return nil, status.Error(codes.InvalidArgument, "tar data is required")
	}

	destPath, err := s.volumePath(req.VolumeID, req.Path)
	if err != nil {
		return nil, status.Errorf(codes.InvalidArgument, "%v", err)
	}

	if err := os.MkdirAll(destPath, 0755); err != nil {
		return nil, status.Errorf(codes.Internal, "mkdir dest: %v", err)
	}

	tr := tar.NewReader(bytes.NewReader(req.Data))
	for {
		header, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, status.Errorf(codes.Internal, "read tar: %v", err)
		}

		targetPath := filepath.Join(destPath, header.Name)
		cleanTarget := filepath.Clean(targetPath)
		cleanDest := filepath.Clean(destPath)

		// Prevent path traversal in tar entries.
		if !strings.HasPrefix(cleanTarget, cleanDest+string(filepath.Separator)) && cleanTarget != cleanDest {
			continue // Skip entries that escape the destination.
		}

		switch header.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(cleanTarget, os.FileMode(header.Mode)); err != nil {
				return nil, status.Errorf(codes.Internal, "mkdir tar entry: %v", err)
			}
		case tar.TypeReg:
			// Limit individual file extraction to 1GB to prevent zip bomb attacks.
			const maxFileSize int64 = 1 << 30
			if header.Size > maxFileSize {
				return nil, status.Errorf(codes.InvalidArgument, "tar entry %q exceeds max size (%d > %d)", header.Name, header.Size, maxFileSize)
			}
			if err := os.MkdirAll(filepath.Dir(cleanTarget), 0755); err != nil {
				return nil, status.Errorf(codes.Internal, "mkdir parent: %v", err)
			}
			file, createErr := os.OpenFile(cleanTarget, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, os.FileMode(header.Mode))
			if createErr != nil {
				return nil, status.Errorf(codes.Internal, "create file: %v", createErr)
			}
			if _, copyErr := io.CopyN(file, tr, maxFileSize); copyErr != nil && copyErr != io.EOF {
				file.Close()
				return nil, status.Errorf(codes.Internal, "write file: %v", copyErr)
			}
			file.Close()
		}

		if req.Uid > 0 || req.Gid > 0 {
			os.Chown(cleanTarget, req.Uid, req.Gid)
		}
	}

	return &Empty{}, nil
}
