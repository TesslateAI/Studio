// Package fileops provides a gRPC server for direct file operations on btrfs
// subvolumes. This is Tier 0 of the compute model — file ops work with zero
// pods running. The agent and orchestrator can read/write project files
// directly through this service.
package fileops

import (
	"context"
)

// FileInfo represents metadata about a file or directory.
type FileInfo struct {
	Name    string `json:"name"`
	Path    string `json:"path"`
	Size    int64  `json:"size"`
	IsDir   bool   `json:"is_dir"`
	ModTime int64  `json:"mod_time"` // Unix timestamp
	Mode    uint32 `json:"mode"`     // File permission bits
}

// FileContent holds a file's path, data and size for batch reads.
type FileContent struct {
	Path string `json:"path"`
	Data []byte `json:"data"`
	Size int64  `json:"size"`
}

// FileOps defines the file operations interface for Tier 0.
type FileOps interface {
	// ReadFile reads the contents of a file in a project volume.
	ReadFile(ctx context.Context, volumeID, path string) ([]byte, error)

	// WriteFile writes data to a file in a project volume.
	WriteFile(ctx context.Context, volumeID, path string, data []byte, mode uint32) error

	// ListDir lists the contents of a directory in a project volume.
	ListDir(ctx context.Context, volumeID, path string, recursive bool) ([]FileInfo, error)

	// ListTree returns a filtered recursive file listing, skipping excluded dirs/files/extensions.
	ListTree(ctx context.Context, volumeID, path string, excludeDirs, excludeFiles, excludeExts []string) ([]FileInfo, error)

	// StatPath returns metadata about a file or directory.
	StatPath(ctx context.Context, volumeID, path string) (*FileInfo, error)

	// DeletePath removes a file or directory.
	DeletePath(ctx context.Context, volumeID, path string) error

	// MkdirAll creates a directory and all parents.
	MkdirAll(ctx context.Context, volumeID, path string) error

	// ReadFiles reads multiple files in a single call. Returns contents and error paths.
	ReadFiles(ctx context.Context, volumeID string, paths []string, maxFileSize int64) ([]FileContent, []string, error)

	// TarCreate creates a tar archive of a directory or file.
	TarCreate(ctx context.Context, volumeID, path string) ([]byte, error)

	// TarExtract extracts a tar archive into a directory.
	TarExtract(ctx context.Context, volumeID, path string, data []byte) error
}
