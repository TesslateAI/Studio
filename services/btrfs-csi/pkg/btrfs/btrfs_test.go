package btrfs

import (
	"path/filepath"
	"testing"
)

func TestSafePath(t *testing.T) {
	m := NewManager("/pool")

	tests := []struct {
		name    string
		input   string
		wantErr bool
		wantOut string // expected cleaned path (only checked when wantErr is false)
	}{
		{
			name:    "valid volumes path",
			input:   "volumes/foo",
			wantErr: false,
			wantOut: "/pool/volumes/foo",
		},
		{
			name:    "valid snapshots path",
			input:   "snapshots/bar",
			wantErr: false,
			wantOut: "/pool/snapshots/bar",
		},
		{
			name:    "valid templates path",
			input:   "templates/baz",
			wantErr: false,
			wantOut: "/pool/templates/baz",
		},
		{
			name:    "traversal with dot-dot escaping",
			input:   "../etc/passwd",
			wantErr: true,
		},
		{
			name:    "deeper traversal",
			input:   "../../root",
			wantErr: true,
		},
		{
			name:    "absolute path outside pool",
			input:   "/../../../etc/shadow",
			wantErr: true,
		},
		{
			name:    "dot-dot that normalizes back into pool",
			input:   "volumes/../volumes/foo",
			wantErr: false,
			wantOut: "/pool/volumes/foo",
		},
		{
			name:    "empty string resolves to pool root itself",
			input:   "",
			wantErr: false,
			wantOut: "/pool",
		},
		{
			name:    "single dot resolves to pool root",
			input:   ".",
			wantErr: false,
			wantOut: "/pool",
		},
		{
			name:    "traversal out and back still blocked if it escapes",
			input:   "volumes/../../etc",
			wantErr: true,
		},
		{
			name:    "nested valid path",
			input:   "templates/nextjs/subdir",
			wantErr: false,
			wantOut: "/pool/templates/nextjs/subdir",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := m.safePath(tt.input)
			if tt.wantErr {
				if err == nil {
					t.Errorf("safePath(%q) expected error, got path %q", tt.input, got)
				}
				return
			}
			if err != nil {
				t.Errorf("safePath(%q) unexpected error: %v", tt.input, err)
				return
			}
			want := filepath.Clean(tt.wantOut)
			if got != want {
				t.Errorf("safePath(%q) = %q, want %q", tt.input, got, want)
			}
		})
	}
}

func TestParseSubvolumeLine(t *testing.T) {
	tests := []struct {
		name     string
		line     string
		wantOK   bool
		wantID   int
		wantName string
		wantPath string
	}{
		{
			name:     "valid standard line",
			line:     "ID 258 gen 42 top level 5 path volumes/my-vol",
			wantOK:   true,
			wantID:   258,
			wantName: "my-vol",
			wantPath: "volumes/my-vol",
		},
		{
			name:     "path with nested slashes",
			line:     "ID 300 gen 50 top level 5 path templates/nextjs/subdir",
			wantOK:   true,
			wantID:   300,
			wantName: "subdir",
			wantPath: "templates/nextjs/subdir",
		},
		{
			name:   "too few fields",
			line:   "ID 258 gen 42",
			wantOK: false,
		},
		{
			name:   "missing ID prefix",
			line:   "XX 258 gen 42 top level 5 path volumes/my-vol",
			wantOK: false,
		},
		{
			name:   "missing path keyword",
			line:   "ID 258 gen 42 top level 5 nopath volumes/my-vol",
			wantOK: false,
		},
		{
			name:   "empty line",
			line:   "",
			wantOK: false,
		},
		{
			name:   "non-numeric ID",
			line:   "ID abc gen 42 top level 5 path volumes/my-vol",
			wantOK: false,
		},
		{
			name:     "large ID value",
			line:     "ID 99999 gen 100 top level 5 path snapshots/snap-abc",
			wantOK:   true,
			wantID:   99999,
			wantName: "snap-abc",
			wantPath: "snapshots/snap-abc",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			info, ok := parseSubvolumeLine(tt.line)
			if ok != tt.wantOK {
				t.Fatalf("parseSubvolumeLine(%q) ok = %v, want %v", tt.line, ok, tt.wantOK)
			}
			if !ok {
				return
			}
			if info.ID != tt.wantID {
				t.Errorf("ID = %d, want %d", info.ID, tt.wantID)
			}
			if info.Name != tt.wantName {
				t.Errorf("Name = %q, want %q", info.Name, tt.wantName)
			}
			if info.Path != tt.wantPath {
				t.Errorf("Path = %q, want %q", info.Path, tt.wantPath)
			}
		})
	}
}

func TestExtractBytes(t *testing.T) {
	tests := []struct {
		name string
		line string
		want int64
	}{
		{
			name: "device size line",
			line: "Device size:          107374182400",
			want: 107374182400,
		},
		{
			name: "free estimated with parenthesized min",
			line: "Free (estimated):      53687091200    (min: 26843545600)",
			want: 26843545600,
		},
		{
			name: "no numbers",
			line: "no numbers here",
			want: 0,
		},
		{
			name: "empty string",
			line: "",
			want: 0,
		},
		{
			name: "single number",
			line: "12345",
			want: 12345,
		},
		{
			name: "number at start followed by text",
			line: "1024 bytes used",
			want: 1024,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := extractBytes(tt.line)
			if got != tt.want {
				t.Errorf("extractBytes(%q) = %d, want %d", tt.line, got, tt.want)
			}
		})
	}
}

func TestNewManager(t *testing.T) {
	tests := []struct {
		name     string
		poolPath string
	}{
		{
			name:     "standard pool path",
			poolPath: "/mnt/btrfs-pool",
		},
		{
			name:     "root pool path",
			poolPath: "/pool",
		},
		{
			name:     "nested pool path",
			poolPath: "/var/lib/csi/btrfs/pool",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			m := NewManager(tt.poolPath)
			if m == nil {
				t.Fatal("NewManager returned nil")
			}
			if m.PoolPath() != tt.poolPath {
				t.Errorf("PoolPath() = %q, want %q", m.PoolPath(), tt.poolPath)
			}
		})
	}
}
