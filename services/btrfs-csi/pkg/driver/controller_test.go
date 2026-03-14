package driver

import (
	"context"
	"testing"

	"github.com/container-storage-interface/spec/lib/go/csi"
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
