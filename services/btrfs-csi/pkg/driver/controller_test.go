package driver

import (
	"context"
	"fmt"
	"testing"

	"github.com/container-storage-interface/spec/lib/go/csi"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/nodeops"
)

func TestBuildVolumeResponse(t *testing.T) {
	d := &Driver{
		name:   "btrfs.csi.tesslate.io",
		nodeID: "node-1",
	}
	cs := NewControllerServer(d)

	req := &csi.CreateVolumeRequest{
		Name: "test-vol",
		CapacityRange: &csi.CapacityRange{
			RequiredBytes: 1073741824, // 1 GiB
		},
	}

	resp := cs.buildVolumeResponse("test-vol", req)

	if resp == nil {
		t.Fatal("buildVolumeResponse returned nil")
	}
	if resp.Volume == nil {
		t.Fatal("Volume in response is nil")
	}
	if resp.Volume.VolumeId != "test-vol" {
		t.Errorf("VolumeId = %q, want %q", resp.Volume.VolumeId, "test-vol")
	}
	if resp.Volume.CapacityBytes != 1073741824 {
		t.Errorf("CapacityBytes = %d, want %d", resp.Volume.CapacityBytes, 1073741824)
	}

	// Verify topology
	if len(resp.Volume.AccessibleTopology) != 1 {
		t.Fatalf("AccessibleTopology length = %d, want 1", len(resp.Volume.AccessibleTopology))
	}
	topo := resp.Volume.AccessibleTopology[0]
	wantKey := "btrfs.csi.tesslate.io/node"
	if val, ok := topo.Segments[wantKey]; !ok {
		t.Errorf("topology missing key %q", wantKey)
	} else if val != "node-1" {
		t.Errorf("topology[%q] = %q, want %q", wantKey, val, "node-1")
	}
}

func TestBuildVolumeResponse_WithContentSource(t *testing.T) {
	d := &Driver{
		name:   "btrfs.csi.tesslate.io",
		nodeID: "node-2",
	}
	cs := NewControllerServer(d)

	contentSource := &csi.VolumeContentSource{
		Type: &csi.VolumeContentSource_Snapshot{
			Snapshot: &csi.VolumeContentSource_SnapshotSource{
				SnapshotId: "snap-123",
			},
		},
	}

	req := &csi.CreateVolumeRequest{
		Name:                "vol-from-snap",
		VolumeContentSource: contentSource,
	}

	resp := cs.buildVolumeResponse("vol-from-snap", req)

	if resp.Volume.ContentSource == nil {
		t.Fatal("ContentSource should be set when request has content source")
	}
	snapSource := resp.Volume.ContentSource.GetSnapshot()
	if snapSource == nil {
		t.Fatal("ContentSource snapshot is nil")
	}
	if snapSource.SnapshotId != "snap-123" {
		t.Errorf("SnapshotId = %q, want %q", snapSource.SnapshotId, "snap-123")
	}
}

func TestBuildSnapshotResponse(t *testing.T) {
	d := &Driver{
		name:   "btrfs.csi.tesslate.io",
		nodeID: "node-1",
	}
	cs := NewControllerServer(d)

	resp := cs.buildSnapshotResponse("snap-abc", "vol-xyz")

	if resp == nil {
		t.Fatal("buildSnapshotResponse returned nil")
	}
	if resp.Snapshot == nil {
		t.Fatal("Snapshot in response is nil")
	}
	if resp.Snapshot.SnapshotId != "snap-abc" {
		t.Errorf("SnapshotId = %q, want %q", resp.Snapshot.SnapshotId, "snap-abc")
	}
	if resp.Snapshot.SourceVolumeId != "vol-xyz" {
		t.Errorf("SourceVolumeId = %q, want %q", resp.Snapshot.SourceVolumeId, "vol-xyz")
	}
	if !resp.Snapshot.ReadyToUse {
		t.Error("ReadyToUse should be true")
	}
	if resp.Snapshot.CreationTime == nil {
		t.Error("CreationTime should not be nil")
	}
}

func TestControllerGetCapabilities(t *testing.T) {
	d := &Driver{
		name:   "btrfs.csi.tesslate.io",
		nodeID: "node-1",
	}
	cs := NewControllerServer(d)

	resp, err := cs.ControllerGetCapabilities(context.Background(), &csi.ControllerGetCapabilitiesRequest{})
	if err != nil {
		t.Fatalf("ControllerGetCapabilities returned error: %v", err)
	}

	expectedCaps := map[csi.ControllerServiceCapability_RPC_Type]bool{
		csi.ControllerServiceCapability_RPC_CREATE_DELETE_VOLUME:   false,
		csi.ControllerServiceCapability_RPC_CREATE_DELETE_SNAPSHOT: false,
		csi.ControllerServiceCapability_RPC_GET_CAPACITY:           false,
		csi.ControllerServiceCapability_RPC_LIST_VOLUMES:           false,
		csi.ControllerServiceCapability_RPC_LIST_SNAPSHOTS:         false,
	}

	if len(resp.Capabilities) != len(expectedCaps) {
		t.Fatalf("got %d capabilities, want %d", len(resp.Capabilities), len(expectedCaps))
	}

	for _, cap := range resp.Capabilities {
		rpc := cap.GetRpc()
		if rpc == nil {
			t.Error("capability has nil RPC type")
			continue
		}
		capType := rpc.GetType()
		if _, ok := expectedCaps[capType]; !ok {
			t.Errorf("unexpected capability: %v", capType)
		} else {
			expectedCaps[capType] = true
		}
	}

	for capType, found := range expectedCaps {
		if !found {
			t.Errorf("expected capability %v not found", capType)
		}
	}
}

// ---------------------------------------------------------------------------
// mockNodeOps implements nodeops.NodeOps for controller tests.
// ---------------------------------------------------------------------------

type mockNodeOps struct {
	subvolumes map[string]bool
	createErr  error
	deleteErr  error
	snapErr    error
	existsErr  error
	tracked    map[string]bool
	capacity   struct{ total, avail int64 }
	listResult []nodeops.SubvolumeInfo
	ensureTmpl map[string]bool // templates ensured
	ensureErr  error
	restoreErr error
}

func newMockNodeOps() *mockNodeOps {
	return &mockNodeOps{
		subvolumes: make(map[string]bool),
		tracked:    make(map[string]bool),
		ensureTmpl: make(map[string]bool),
	}
}

func (m *mockNodeOps) CreateSubvolume(_ context.Context, name string) error {
	if m.createErr != nil {
		return m.createErr
	}
	m.subvolumes[name] = true
	return nil
}

func (m *mockNodeOps) DeleteSubvolume(_ context.Context, name string) error {
	if m.deleteErr != nil {
		return m.deleteErr
	}
	delete(m.subvolumes, name)
	return nil
}

func (m *mockNodeOps) SnapshotSubvolume(_ context.Context, source, dest string, _ bool) error {
	if m.snapErr != nil {
		return m.snapErr
	}
	if !m.subvolumes[source] {
		return fmt.Errorf("source %q not found", source)
	}
	m.subvolumes[dest] = true
	return nil
}

func (m *mockNodeOps) SubvolumeExists(_ context.Context, name string) (bool, error) {
	if m.existsErr != nil {
		return false, m.existsErr
	}
	return m.subvolumes[name], nil
}

func (m *mockNodeOps) GetCapacity(_ context.Context) (int64, int64, error) {
	return m.capacity.total, m.capacity.avail, nil
}

func (m *mockNodeOps) ListSubvolumes(_ context.Context, _ string) ([]nodeops.SubvolumeInfo, error) {
	return m.listResult, nil
}

func (m *mockNodeOps) TrackVolume(_ context.Context, volumeID, _, _ string) error {
	m.tracked[volumeID] = true
	return nil
}

func (m *mockNodeOps) UntrackVolume(_ context.Context, volumeID string) error {
	delete(m.tracked, volumeID)
	return nil
}

func (m *mockNodeOps) EnsureTemplate(_ context.Context, name string) error {
	if m.ensureErr != nil {
		return m.ensureErr
	}
	m.ensureTmpl[name] = true
	return nil
}

func (m *mockNodeOps) RestoreVolume(_ context.Context, volumeID string) error {
	return m.restoreErr
}

func (m *mockNodeOps) PromoteToTemplate(_ context.Context, volumeID, templateName string) error {
	volPath := "volumes/" + volumeID
	if !m.subvolumes[volPath] {
		return fmt.Errorf("volume %q not found", volumeID)
	}
	tmplPath := "templates/" + templateName
	delete(m.subvolumes, tmplPath)
	m.subvolumes[tmplPath] = true
	delete(m.subvolumes, volPath)
	return nil
}

func (m *mockNodeOps) SetOwnership(_ context.Context, _ string, _, _ int) error {
	return nil
}

func (m *mockNodeOps) SyncVolume(_ context.Context, _ string) error {
	return nil
}

func (m *mockNodeOps) DeleteVolumeCAS(_ context.Context, _ string) error {
	return nil
}

func (m *mockNodeOps) GetSyncState(_ context.Context) ([]nodeops.TrackedVolumeState, error) {
	return nil, nil
}

func (m *mockNodeOps) SendVolumeTo(_ context.Context, _, _ string) error {
	return nil
}

func (m *mockNodeOps) SendTemplateTo(_ context.Context, _, _ string) error {
	return nil
}

func (m *mockNodeOps) HasBlobs(_ context.Context, hashes []string) ([]bool, error) {
	return make([]bool, len(hashes)), nil
}

func (m *mockNodeOps) CreateUserSnapshot(_ context.Context, _, _ string) (string, error) {
	return "", nil
}

func (m *mockNodeOps) RestoreFromSnapshot(_ context.Context, _, _ string) error {
	return nil
}

func (m *mockNodeOps) GetVolumeMetadata(_ context.Context, _ string) (*nodeops.VolumeMetadata, error) {
	return &nodeops.VolumeMetadata{}, nil
}

// newTestControllerServer builds a ControllerServer backed by the given mock.
func newTestControllerServer(mock *mockNodeOps) *ControllerServer {
	d := &Driver{
		name:    "btrfs.csi.tesslate.io",
		nodeID:  "test-node",
		nodeOps: mock,
	}
	return NewControllerServer(d)
}

// ---------------------------------------------------------------------------
// CreateVolume tests
// ---------------------------------------------------------------------------

func TestCreateVolume_Empty(t *testing.T) {
	mock := newMockNodeOps()
	cs := newTestControllerServer(mock)

	resp, err := cs.CreateVolume(context.Background(), &csi.CreateVolumeRequest{
		Name: "vol-empty",
		CapacityRange: &csi.CapacityRange{
			RequiredBytes: 1 << 30,
		},
	})
	if err != nil {
		t.Fatalf("CreateVolume returned error: %v", err)
	}
	if resp.Volume.VolumeId != "vol-empty" {
		t.Errorf("VolumeId = %q, want %q", resp.Volume.VolumeId, "vol-empty")
	}
	if !mock.subvolumes["volumes/vol-empty"] {
		t.Error("subvolume volumes/vol-empty was not created")
	}
}

func TestCreateVolume_FromTemplate(t *testing.T) {
	mock := newMockNodeOps()
	// Pre-populate the template subvolume so SubvolumeExists returns true.
	mock.subvolumes["templates/nodejs"] = true

	cs := newTestControllerServer(mock)

	resp, err := cs.CreateVolume(context.Background(), &csi.CreateVolumeRequest{
		Name:       "vol-tmpl",
		Parameters: map[string]string{"template": "nodejs"},
		CapacityRange: &csi.CapacityRange{
			RequiredBytes: 1 << 30,
		},
	})
	if err != nil {
		t.Fatalf("CreateVolume returned error: %v", err)
	}
	if resp.Volume.VolumeId != "vol-tmpl" {
		t.Errorf("VolumeId = %q, want %q", resp.Volume.VolumeId, "vol-tmpl")
	}
	if !mock.subvolumes["volumes/vol-tmpl"] {
		t.Error("subvolume volumes/vol-tmpl was not created from template snapshot")
	}
	if !mock.ensureTmpl["nodejs"] {
		t.Error("EnsureTemplate was not called for 'nodejs'")
	}
}

func TestCreateVolume_FromSnapshot(t *testing.T) {
	mock := newMockNodeOps()
	mock.subvolumes["snapshots/snap-restore"] = true

	cs := newTestControllerServer(mock)

	resp, err := cs.CreateVolume(context.Background(), &csi.CreateVolumeRequest{
		Name: "vol-restored",
		VolumeContentSource: &csi.VolumeContentSource{
			Type: &csi.VolumeContentSource_Snapshot{
				Snapshot: &csi.VolumeContentSource_SnapshotSource{
					SnapshotId: "snap-restore",
				},
			},
		},
	})
	if err != nil {
		t.Fatalf("CreateVolume returned error: %v", err)
	}
	if resp.Volume.VolumeId != "vol-restored" {
		t.Errorf("VolumeId = %q, want %q", resp.Volume.VolumeId, "vol-restored")
	}
	if !mock.subvolumes["volumes/vol-restored"] {
		t.Error("subvolume volumes/vol-restored was not created from snapshot")
	}
	if resp.Volume.ContentSource == nil {
		t.Fatal("ContentSource should be set")
	}
	if resp.Volume.ContentSource.GetSnapshot().GetSnapshotId() != "snap-restore" {
		t.Errorf("ContentSource SnapshotId = %q, want %q",
			resp.Volume.ContentSource.GetSnapshot().GetSnapshotId(), "snap-restore")
	}
}

func TestCreateVolume_Idempotent(t *testing.T) {
	mock := newMockNodeOps()
	mock.subvolumes["volumes/vol-exists"] = true

	cs := newTestControllerServer(mock)

	resp, err := cs.CreateVolume(context.Background(), &csi.CreateVolumeRequest{
		Name: "vol-exists",
		CapacityRange: &csi.CapacityRange{
			RequiredBytes: 2 << 30,
		},
	})
	if err != nil {
		t.Fatalf("CreateVolume returned error: %v", err)
	}
	if resp.Volume.VolumeId != "vol-exists" {
		t.Errorf("VolumeId = %q, want %q", resp.Volume.VolumeId, "vol-exists")
	}
	if resp.Volume.CapacityBytes != 2<<30 {
		t.Errorf("CapacityBytes = %d, want %d", resp.Volume.CapacityBytes, 2<<30)
	}
}

func TestCreateVolume_MissingName(t *testing.T) {
	mock := newMockNodeOps()
	cs := newTestControllerServer(mock)

	_, err := cs.CreateVolume(context.Background(), &csi.CreateVolumeRequest{
		Name: "",
	})
	if err == nil {
		t.Fatal("expected error for missing name, got nil")
	}
	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status error, got %v", err)
	}
	if st.Code() != codes.InvalidArgument {
		t.Errorf("code = %v, want %v", st.Code(), codes.InvalidArgument)
	}
}

func TestCreateVolume_TemplateNotFound(t *testing.T) {
	mock := newMockNodeOps()
	// Template does NOT exist in subvolumes — EnsureTemplate succeeds but the
	// subvolume still isn't there (simulates download failure that didn't error).
	cs := newTestControllerServer(mock)

	_, err := cs.CreateVolume(context.Background(), &csi.CreateVolumeRequest{
		Name:       "vol-no-tmpl",
		Parameters: map[string]string{"template": "nonexistent"},
	})
	if err == nil {
		t.Fatal("expected error for missing template, got nil")
	}
	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status error, got %v", err)
	}
	if st.Code() != codes.NotFound {
		t.Errorf("code = %v, want %v", st.Code(), codes.NotFound)
	}
}

func TestCreateVolume_SnapshotNotFound(t *testing.T) {
	mock := newMockNodeOps()
	// Source snapshot does NOT exist.
	cs := newTestControllerServer(mock)

	_, err := cs.CreateVolume(context.Background(), &csi.CreateVolumeRequest{
		Name: "vol-bad-snap",
		VolumeContentSource: &csi.VolumeContentSource{
			Type: &csi.VolumeContentSource_Snapshot{
				Snapshot: &csi.VolumeContentSource_SnapshotSource{
					SnapshotId: "snap-missing",
				},
			},
		},
	})
	if err == nil {
		t.Fatal("expected error for missing snapshot source, got nil")
	}
	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status error, got %v", err)
	}
	if st.Code() != codes.NotFound {
		t.Errorf("code = %v, want %v", st.Code(), codes.NotFound)
	}
}

func TestCreateVolume_TracksForSync(t *testing.T) {
	mock := newMockNodeOps()
	cs := newTestControllerServer(mock)

	_, err := cs.CreateVolume(context.Background(), &csi.CreateVolumeRequest{
		Name: "vol-track",
	})
	if err != nil {
		t.Fatalf("CreateVolume returned error: %v", err)
	}
	if !mock.tracked["vol-track"] {
		t.Error("TrackVolume was not called for vol-track")
	}
}

// ---------------------------------------------------------------------------
// DeleteVolume tests
// ---------------------------------------------------------------------------

func TestDeleteVolume_Success(t *testing.T) {
	mock := newMockNodeOps()
	mock.subvolumes["volumes/vol-del"] = true
	mock.tracked["vol-del"] = true

	cs := newTestControllerServer(mock)

	_, err := cs.DeleteVolume(context.Background(), &csi.DeleteVolumeRequest{
		VolumeId: "vol-del",
	})
	if err != nil {
		t.Fatalf("DeleteVolume returned error: %v", err)
	}
	if mock.subvolumes["volumes/vol-del"] {
		t.Error("subvolume volumes/vol-del was not deleted")
	}
	if mock.tracked["vol-del"] {
		t.Error("UntrackVolume was not called for vol-del")
	}
}

func TestDeleteVolume_Idempotent(t *testing.T) {
	mock := newMockNodeOps()
	// Volume does NOT exist.
	cs := newTestControllerServer(mock)

	_, err := cs.DeleteVolume(context.Background(), &csi.DeleteVolumeRequest{
		VolumeId: "vol-gone",
	})
	if err != nil {
		t.Fatalf("DeleteVolume should succeed for non-existent volume, got: %v", err)
	}
}

func TestDeleteVolume_MissingID(t *testing.T) {
	mock := newMockNodeOps()
	cs := newTestControllerServer(mock)

	_, err := cs.DeleteVolume(context.Background(), &csi.DeleteVolumeRequest{
		VolumeId: "",
	})
	if err == nil {
		t.Fatal("expected error for missing volume ID, got nil")
	}
	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status error, got %v", err)
	}
	if st.Code() != codes.InvalidArgument {
		t.Errorf("code = %v, want %v", st.Code(), codes.InvalidArgument)
	}
}

// ---------------------------------------------------------------------------
// CreateSnapshot tests
// ---------------------------------------------------------------------------

func TestCreateSnapshot_Success(t *testing.T) {
	mock := newMockNodeOps()
	mock.subvolumes["volumes/vol-src"] = true

	cs := newTestControllerServer(mock)

	resp, err := cs.CreateSnapshot(context.Background(), &csi.CreateSnapshotRequest{
		SourceVolumeId: "vol-src",
		Name:           "snap-new",
	})
	if err != nil {
		t.Fatalf("CreateSnapshot returned error: %v", err)
	}
	if resp.Snapshot.SnapshotId != "snap-new" {
		t.Errorf("SnapshotId = %q, want %q", resp.Snapshot.SnapshotId, "snap-new")
	}
	if resp.Snapshot.SourceVolumeId != "vol-src" {
		t.Errorf("SourceVolumeId = %q, want %q", resp.Snapshot.SourceVolumeId, "vol-src")
	}
	if !resp.Snapshot.ReadyToUse {
		t.Error("ReadyToUse should be true")
	}
	if !mock.subvolumes["snapshots/snap-new"] {
		t.Error("snapshot subvolume snapshots/snap-new was not created")
	}
	if src, ok := cs.snapSourceMap["snap-new"]; !ok || src != "vol-src" {
		t.Errorf("snapSourceMap[snap-new] = %q, want %q", src, "vol-src")
	}
}

func TestCreateSnapshot_Idempotent(t *testing.T) {
	mock := newMockNodeOps()
	mock.subvolumes["volumes/vol-src"] = true
	mock.subvolumes["snapshots/snap-dup"] = true

	cs := newTestControllerServer(mock)

	resp, err := cs.CreateSnapshot(context.Background(), &csi.CreateSnapshotRequest{
		SourceVolumeId: "vol-src",
		Name:           "snap-dup",
	})
	if err != nil {
		t.Fatalf("CreateSnapshot returned error: %v", err)
	}
	if resp.Snapshot.SnapshotId != "snap-dup" {
		t.Errorf("SnapshotId = %q, want %q", resp.Snapshot.SnapshotId, "snap-dup")
	}
}

func TestCreateSnapshot_SourceNotFound(t *testing.T) {
	mock := newMockNodeOps()
	// Source volume does NOT exist.
	cs := newTestControllerServer(mock)

	_, err := cs.CreateSnapshot(context.Background(), &csi.CreateSnapshotRequest{
		SourceVolumeId: "vol-missing",
		Name:           "snap-orphan",
	})
	if err == nil {
		t.Fatal("expected error for missing source volume, got nil")
	}
	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("expected gRPC status error, got %v", err)
	}
	if st.Code() != codes.NotFound {
		t.Errorf("code = %v, want %v", st.Code(), codes.NotFound)
	}
}

// ---------------------------------------------------------------------------
// DeleteSnapshot tests
// ---------------------------------------------------------------------------

func TestDeleteSnapshot_Success(t *testing.T) {
	mock := newMockNodeOps()
	mock.subvolumes["snapshots/snap-del"] = true

	cs := newTestControllerServer(mock)
	cs.snapSourceMap["snap-del"] = "vol-origin"

	_, err := cs.DeleteSnapshot(context.Background(), &csi.DeleteSnapshotRequest{
		SnapshotId: "snap-del",
	})
	if err != nil {
		t.Fatalf("DeleteSnapshot returned error: %v", err)
	}
	if mock.subvolumes["snapshots/snap-del"] {
		t.Error("snapshot subvolume snapshots/snap-del was not deleted")
	}
	if _, ok := cs.snapSourceMap["snap-del"]; ok {
		t.Error("snapSourceMap entry for snap-del was not cleaned up")
	}
}

func TestDeleteSnapshot_Idempotent(t *testing.T) {
	mock := newMockNodeOps()
	// Snapshot does NOT exist.
	cs := newTestControllerServer(mock)

	_, err := cs.DeleteSnapshot(context.Background(), &csi.DeleteSnapshotRequest{
		SnapshotId: "snap-gone",
	})
	if err != nil {
		t.Fatalf("DeleteSnapshot should succeed for non-existent snapshot, got: %v", err)
	}
}

// ---------------------------------------------------------------------------
// ValidateVolumeCapabilities tests
// ---------------------------------------------------------------------------

func TestValidateVolumeCapabilities(t *testing.T) {
	tests := []struct {
		name          string
		volID         string
		volExists     bool
		caps          []*csi.VolumeCapability
		wantCode      codes.Code
		wantConfirmed bool
		wantMessage   string
	}{
		{
			name:      "supported SINGLE_NODE_WRITER mount",
			volID:     "vol-ok",
			volExists: true,
			caps: []*csi.VolumeCapability{
				{
					AccessMode: &csi.VolumeCapability_AccessMode{
						Mode: csi.VolumeCapability_AccessMode_SINGLE_NODE_WRITER,
					},
					AccessType: &csi.VolumeCapability_Mount{
						Mount: &csi.VolumeCapability_MountVolume{},
					},
				},
			},
			wantConfirmed: true,
		},
		{
			name:      "unsupported MULTI_NODE_MULTI_WRITER",
			volID:     "vol-multi",
			volExists: true,
			caps: []*csi.VolumeCapability{
				{
					AccessMode: &csi.VolumeCapability_AccessMode{
						Mode: csi.VolumeCapability_AccessMode_MULTI_NODE_MULTI_WRITER,
					},
					AccessType: &csi.VolumeCapability_Mount{
						Mount: &csi.VolumeCapability_MountVolume{},
					},
				},
			},
			wantConfirmed: false,
			wantMessage:   "unsupported access mode",
		},
		{
			name:      "unsupported block access type",
			volID:     "vol-block",
			volExists: true,
			caps: []*csi.VolumeCapability{
				{
					AccessMode: &csi.VolumeCapability_AccessMode{
						Mode: csi.VolumeCapability_AccessMode_SINGLE_NODE_WRITER,
					},
					AccessType: &csi.VolumeCapability_Block{
						Block: &csi.VolumeCapability_BlockVolume{},
					},
				},
			},
			wantConfirmed: false,
			wantMessage:   "only mount access type is supported",
		},
		{
			name:     "volume not found",
			volID:    "vol-no",
			caps: []*csi.VolumeCapability{
				{
					AccessMode: &csi.VolumeCapability_AccessMode{
						Mode: csi.VolumeCapability_AccessMode_SINGLE_NODE_WRITER,
					},
					AccessType: &csi.VolumeCapability_Mount{
						Mount: &csi.VolumeCapability_MountVolume{},
					},
				},
			},
			wantCode: codes.NotFound,
		},
		{
			name:      "missing volume ID",
			volID:     "",
			volExists: true,
			caps: []*csi.VolumeCapability{
				{
					AccessMode: &csi.VolumeCapability_AccessMode{
						Mode: csi.VolumeCapability_AccessMode_SINGLE_NODE_WRITER,
					},
					AccessType: &csi.VolumeCapability_Mount{
						Mount: &csi.VolumeCapability_MountVolume{},
					},
				},
			},
			wantCode: codes.InvalidArgument,
		},
		{
			name:      "empty capabilities list",
			volID:     "vol-empty-caps",
			volExists: true,
			caps:      nil,
			wantCode:  codes.InvalidArgument,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			mock := newMockNodeOps()
			if tc.volExists {
				mock.subvolumes["volumes/"+tc.volID] = true
			}
			cs := newTestControllerServer(mock)

			resp, err := cs.ValidateVolumeCapabilities(context.Background(),
				&csi.ValidateVolumeCapabilitiesRequest{
					VolumeId:           tc.volID,
					VolumeCapabilities: tc.caps,
				})

			if tc.wantCode != codes.OK {
				if err == nil {
					t.Fatalf("expected error with code %v, got nil", tc.wantCode)
				}
				st, ok := status.FromError(err)
				if !ok {
					t.Fatalf("expected gRPC status error, got %v", err)
				}
				if st.Code() != tc.wantCode {
					t.Errorf("code = %v, want %v", st.Code(), tc.wantCode)
				}
				return
			}

			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}

			if tc.wantConfirmed {
				if resp.Confirmed == nil {
					t.Error("expected Confirmed to be non-nil")
				}
			} else {
				if resp.Confirmed != nil {
					t.Error("expected Confirmed to be nil for unsupported caps")
				}
				if tc.wantMessage != "" && resp.Message == "" {
					t.Errorf("expected non-empty Message containing %q", tc.wantMessage)
				}
			}
		})
	}
}

// ---------------------------------------------------------------------------
// GetCapacity test
// ---------------------------------------------------------------------------

func TestGetCapacity(t *testing.T) {
	mock := newMockNodeOps()
	mock.capacity.total = 100 << 30  // 100 GiB
	mock.capacity.avail = 60 << 30   // 60 GiB

	cs := newTestControllerServer(mock)

	resp, err := cs.GetCapacity(context.Background(), &csi.GetCapacityRequest{})
	if err != nil {
		t.Fatalf("GetCapacity returned error: %v", err)
	}
	if resp.AvailableCapacity != 60<<30 {
		t.Errorf("AvailableCapacity = %d, want %d", resp.AvailableCapacity, 60<<30)
	}
}

// ---------------------------------------------------------------------------
// ListVolumes test
// ---------------------------------------------------------------------------

func TestListVolumes(t *testing.T) {
	mock := newMockNodeOps()
	mock.listResult = []nodeops.SubvolumeInfo{
		{ID: 1, Name: "vol-aaa", Path: "volumes/vol-aaa"},
		{ID: 2, Name: "vol-bbb", Path: "volumes/vol-bbb"},
		{ID: 3, Name: "vol-ccc", Path: "volumes/vol-ccc"},
	}

	cs := newTestControllerServer(mock)

	resp, err := cs.ListVolumes(context.Background(), &csi.ListVolumesRequest{})
	if err != nil {
		t.Fatalf("ListVolumes returned error: %v", err)
	}
	if len(resp.Entries) != 3 {
		t.Fatalf("got %d entries, want 3", len(resp.Entries))
	}

	wantIDs := []string{"vol-aaa", "vol-bbb", "vol-ccc"}
	for i, entry := range resp.Entries {
		if entry.Volume.VolumeId != wantIDs[i] {
			t.Errorf("entry[%d].VolumeId = %q, want %q", i, entry.Volume.VolumeId, wantIDs[i])
		}
	}
}

// ---------------------------------------------------------------------------
// ListSnapshots tests
// ---------------------------------------------------------------------------

func TestListSnapshots_FilterBySource(t *testing.T) {
	allSnaps := []nodeops.SubvolumeInfo{
		{ID: 10, Name: "snap-a", Path: "snapshots/snap-a"},
		{ID: 11, Name: "snap-b", Path: "snapshots/snap-b"},
		{ID: 12, Name: "snap-c", Path: "snapshots/snap-c"},
	}

	tests := []struct {
		name           string
		sourceVolumeID string
		wantCount      int
		wantSnaps      []string
	}{
		{
			name:           "filter by vol-X",
			sourceVolumeID: "vol-X",
			wantCount:      2,
			wantSnaps:      []string{"snap-a", "snap-c"},
		},
		{
			name:           "filter by vol-Y",
			sourceVolumeID: "vol-Y",
			wantCount:      1,
			wantSnaps:      []string{"snap-b"},
		},
		{
			name:           "filter by non-existent source",
			sourceVolumeID: "vol-Z",
			wantCount:      0,
		},
		{
			name:           "no filter returns all",
			sourceVolumeID: "",
			wantCount:      3,
			wantSnaps:      []string{"snap-a", "snap-b", "snap-c"},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			// Fresh mock + controller per subtest because ListSnapshots mutates
			// the entries slice in-place via the [:0] filtering trick.
			mock := newMockNodeOps()
			snapsCopy := make([]nodeops.SubvolumeInfo, len(allSnaps))
			copy(snapsCopy, allSnaps)
			mock.listResult = snapsCopy

			cs := newTestControllerServer(mock)
			cs.snapSourceMap["snap-a"] = "vol-X"
			cs.snapSourceMap["snap-b"] = "vol-Y"
			cs.snapSourceMap["snap-c"] = "vol-X"

			resp, err := cs.ListSnapshots(context.Background(), &csi.ListSnapshotsRequest{
				SourceVolumeId: tc.sourceVolumeID,
			})
			if err != nil {
				t.Fatalf("ListSnapshots returned error: %v", err)
			}
			if len(resp.Entries) != tc.wantCount {
				t.Fatalf("got %d entries, want %d", len(resp.Entries), tc.wantCount)
			}
			for i, entry := range resp.Entries {
				if i < len(tc.wantSnaps) && entry.Snapshot.SnapshotId != tc.wantSnaps[i] {
					t.Errorf("entry[%d].SnapshotId = %q, want %q",
						i, entry.Snapshot.SnapshotId, tc.wantSnaps[i])
				}
			}
		})
	}
}

// ---------------------------------------------------------------------------
// PromoteToTemplate mock tests
// ---------------------------------------------------------------------------

func TestMockPromoteToTemplate_Success(t *testing.T) {
	mock := newMockNodeOps()
	mock.subvolumes["volumes/build-vol"] = true

	err := mock.PromoteToTemplate(context.Background(), "build-vol", "nextjs")
	if err != nil {
		t.Fatalf("PromoteToTemplate returned error: %v", err)
	}

	// Source volume should be deleted.
	if mock.subvolumes["volumes/build-vol"] {
		t.Error("source volume volumes/build-vol should have been deleted")
	}

	// Template should exist.
	if !mock.subvolumes["templates/nextjs"] {
		t.Error("template templates/nextjs should have been created")
	}
}

func TestMockPromoteToTemplate_VolumeNotFound(t *testing.T) {
	mock := newMockNodeOps()

	err := mock.PromoteToTemplate(context.Background(), "nonexistent", "tmpl")
	if err == nil {
		t.Fatal("expected error for nonexistent volume, got nil")
	}
}

func TestMockPromoteToTemplate_RefreshExistingTemplate(t *testing.T) {
	mock := newMockNodeOps()
	mock.subvolumes["volumes/build-vol-2"] = true
	mock.subvolumes["templates/react"] = true // pre-existing template

	err := mock.PromoteToTemplate(context.Background(), "build-vol-2", "react")
	if err != nil {
		t.Fatalf("PromoteToTemplate returned error: %v", err)
	}

	// Template should still exist (replaced).
	if !mock.subvolumes["templates/react"] {
		t.Error("template templates/react should exist after refresh")
	}
	// Source volume should be cleaned up.
	if mock.subvolumes["volumes/build-vol-2"] {
		t.Error("source volume should have been deleted after promote")
	}
}
