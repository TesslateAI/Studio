package fileops

import (
	"context"
	"fmt"

	"google.golang.org/grpc"
	"k8s.io/klog/v2"
)

// Client implements FileOps by forwarding calls to a remote node's gRPC server.
type Client struct {
	conn *grpc.ClientConn
}

// NewClient connects to the fileops gRPC server at the given address.
// Callers provide transport credentials and other options via opts.
func NewClient(addr string, opts ...grpc.DialOption) (*Client, error) {
	opts = append(opts,
		grpc.WithDefaultCallOptions(
			grpc.ForceCodec(jsonCodec{}),
			grpc.MaxCallRecvMsgSize(64*1024*1024),
			grpc.MaxCallSendMsgSize(64*1024*1024),
		),
	)

	klog.V(2).Infof("FileOps client connecting to %s", addr)

	conn, err := grpc.NewClient(addr, opts...)
	if err != nil {
		return nil, fmt.Errorf("connect to fileops at %s: %w", addr, err)
	}

	return &Client{conn: conn}, nil
}

// Close closes the underlying gRPC connection.
func (c *Client) Close() error {
	return c.conn.Close()
}

// invoke is a helper that calls a fileops RPC method.
func (c *Client) invoke(ctx context.Context, method string, req, resp interface{}) error {
	return c.conn.Invoke(ctx, "/fileops.FileOps/"+method, req, resp)
}

func (c *Client) ReadFile(ctx context.Context, volumeID, path string) ([]byte, error) {
	var resp ReadFileResponse
	if err := c.invoke(ctx, "ReadFile", &ReadFileRequest{VolumeID: volumeID, Path: path}, &resp); err != nil {
		return nil, err
	}
	return resp.Data, nil
}

func (c *Client) WriteFile(ctx context.Context, volumeID, path string, data []byte, mode uint32) error {
	return c.invoke(ctx, "WriteFile", &WriteFileRequest{VolumeID: volumeID, Path: path, Data: data, Mode: mode}, &Empty{})
}

func (c *Client) ListDir(ctx context.Context, volumeID, path string, recursive bool) ([]FileInfo, error) {
	var resp ListDirResponse
	if err := c.invoke(ctx, "ListDir", &ListDirRequest{VolumeID: volumeID, Path: path, Recursive: recursive}, &resp); err != nil {
		return nil, err
	}
	return resp.Entries, nil
}

func (c *Client) ListTree(ctx context.Context, volumeID, path string, excludeDirs, excludeFiles, excludeExts []string) ([]FileInfo, error) {
	var resp ListTreeResponse
	if err := c.invoke(ctx, "ListTree", &ListTreeRequest{
		VolumeID:          volumeID,
		Path:              path,
		ExcludeDirs:       excludeDirs,
		ExcludeFiles:      excludeFiles,
		ExcludeExtensions: excludeExts,
	}, &resp); err != nil {
		return nil, err
	}
	return resp.Entries, nil
}

func (c *Client) ReadFiles(ctx context.Context, volumeID string, paths []string, maxFileSize int64) ([]FileContent, []string, error) {
	var resp ReadFilesResponse
	if err := c.invoke(ctx, "ReadFiles", &ReadFilesRequest{
		VolumeID:    volumeID,
		Paths:       paths,
		MaxFileSize: maxFileSize,
	}, &resp); err != nil {
		return nil, nil, err
	}
	return resp.Files, resp.Errors, nil
}

func (c *Client) StatPath(ctx context.Context, volumeID, path string) (*FileInfo, error) {
	var resp FileInfoResponse
	if err := c.invoke(ctx, "StatPath", &StatPathRequest{VolumeID: volumeID, Path: path}, &resp); err != nil {
		return nil, err
	}
	return &resp.Info, nil
}

func (c *Client) DeletePath(ctx context.Context, volumeID, path string) error {
	return c.invoke(ctx, "DeletePath", &DeletePathRequest{VolumeID: volumeID, Path: path}, &Empty{})
}

func (c *Client) MkdirAll(ctx context.Context, volumeID, path string) error {
	return c.invoke(ctx, "MkdirAll", &MkdirAllRequest{VolumeID: volumeID, Path: path}, &Empty{})
}

func (c *Client) TarCreate(ctx context.Context, volumeID, path string) ([]byte, error) {
	var resp TarResponse
	if err := c.invoke(ctx, "TarCreate", &TarRequest{VolumeID: volumeID, Path: path}, &resp); err != nil {
		return nil, err
	}
	return resp.Data, nil
}

func (c *Client) TarExtract(ctx context.Context, volumeID, path string, data []byte) error {
	return c.invoke(ctx, "TarExtract", &TarRequest{VolumeID: volumeID, Path: path, Data: data}, &Empty{})
}
