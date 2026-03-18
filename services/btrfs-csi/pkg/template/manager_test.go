package template

import (
	"testing"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
)

func TestNewManager(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	poolPath := "/pool"

	// With nil CAS store (valid scenario for local-only usage).
	m := NewManager(bm, nil, poolPath)
	if m == nil {
		t.Fatal("NewManager returned nil")
	}
	if m.btrfs != bm {
		t.Error("btrfs manager not set correctly")
	}
	if m.cas != nil {
		t.Error("CAS store should be nil when passed nil")
	}
	if m.poolPath != poolPath {
		t.Errorf("poolPath = %q, want %q", m.poolPath, poolPath)
	}
}

func TestNewManager_DifferentPoolPaths(t *testing.T) {
	tests := []struct {
		name     string
		poolPath string
	}{
		{
			name:     "standard pool path",
			poolPath: "/mnt/btrfs-pool",
		},
		{
			name:     "root pool",
			poolPath: "/pool",
		},
		{
			name:     "nested path",
			poolPath: "/var/lib/csi/btrfs/data",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			bm := btrfs.NewManager(tt.poolPath)
			m := NewManager(bm, nil, tt.poolPath)

			if m == nil {
				t.Fatal("NewManager returned nil")
			}
			if m.poolPath != tt.poolPath {
				t.Errorf("poolPath = %q, want %q", m.poolPath, tt.poolPath)
			}
			if m.btrfs != bm {
				t.Error("btrfs manager reference mismatch")
			}
		})
	}
}
