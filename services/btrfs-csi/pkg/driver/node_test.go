package driver

import (
	"context"
	"testing"

	"github.com/container-storage-interface/spec/lib/go/csi"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestNodeGetInfo(t *testing.T) {
	d := &Driver{
		name:   "btrfs.csi.tesslate.io",
		nodeID: "node-42",
	}
	ns := &NodeServer{driver: d}

	resp, err := ns.NodeGetInfo(context.Background(), &csi.NodeGetInfoRequest{})
	if err != nil {
		t.Fatalf("NodeGetInfo returned error: %v", err)
	}

	if resp.NodeId != "node-42" {
		t.Errorf("NodeId = %q, want %q", resp.NodeId, "node-42")
	}
	if resp.MaxVolumesPerNode != 500 {
		t.Errorf("MaxVolumesPerNode = %d, want %d", resp.MaxVolumesPerNode, 500)
	}

	// Verify topology
	if resp.AccessibleTopology == nil {
		t.Fatal("AccessibleTopology is nil")
	}
	wantKey := "btrfs.csi.tesslate.io/node"
	if val, ok := resp.AccessibleTopology.Segments[wantKey]; !ok {
		t.Errorf("topology missing key %q", wantKey)
	} else if val != "node-42" {
		t.Errorf("topology[%q] = %q, want %q", wantKey, val, "node-42")
	}
}

func TestNodeGetCapabilities(t *testing.T) {
	d := &Driver{
		name:   "btrfs.csi.tesslate.io",
		nodeID: "node-1",
	}
	ns := &NodeServer{driver: d}

	resp, err := ns.NodeGetCapabilities(context.Background(), &csi.NodeGetCapabilitiesRequest{})
	if err != nil {
		t.Fatalf("NodeGetCapabilities returned error: %v", err)
	}

	if len(resp.Capabilities) != 1 {
		t.Fatalf("got %d capabilities, want 1", len(resp.Capabilities))
	}

	rpc := resp.Capabilities[0].GetRpc()
	if rpc == nil {
		t.Fatal("capability RPC is nil")
	}
	if rpc.Type != csi.NodeServiceCapability_RPC_GET_VOLUME_STATS {
		t.Errorf("capability type = %v, want GET_VOLUME_STATS", rpc.Type)
	}
}

func TestNodeStageVolume_Unimplemented(t *testing.T) {
	d := &Driver{
		name:   "btrfs.csi.tesslate.io",
		nodeID: "node-1",
	}
	ns := &NodeServer{driver: d}

	_, err := ns.NodeStageVolume(context.Background(), &csi.NodeStageVolumeRequest{})
	if err == nil {
		t.Fatal("expected error for unimplemented NodeStageVolume")
	}

	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("error is not a gRPC status: %v", err)
	}
	if st.Code() != codes.Unimplemented {
		t.Errorf("error code = %v, want %v", st.Code(), codes.Unimplemented)
	}
}

func TestNodeUnstageVolume_Unimplemented(t *testing.T) {
	d := &Driver{
		name:   "btrfs.csi.tesslate.io",
		nodeID: "node-1",
	}
	ns := &NodeServer{driver: d}

	_, err := ns.NodeUnstageVolume(context.Background(), &csi.NodeUnstageVolumeRequest{})
	if err == nil {
		t.Fatal("expected error for unimplemented NodeUnstageVolume")
	}

	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("error is not a gRPC status: %v", err)
	}
	if st.Code() != codes.Unimplemented {
		t.Errorf("error code = %v, want %v", st.Code(), codes.Unimplemented)
	}
}

func TestNodePublishVolume_MissingVolumeID(t *testing.T) {
	d := &Driver{
		name:     "btrfs.csi.tesslate.io",
		nodeID:   "node-1",
		poolPath: "/pool",
	}
	ns := &NodeServer{driver: d}

	_, err := ns.NodePublishVolume(context.Background(), &csi.NodePublishVolumeRequest{
		VolumeId:   "",
		TargetPath: "/mnt/target",
	})
	if err == nil {
		t.Fatal("expected error for missing volume ID")
	}

	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("error is not a gRPC status: %v", err)
	}
	if st.Code() != codes.InvalidArgument {
		t.Errorf("error code = %v, want %v", st.Code(), codes.InvalidArgument)
	}
}

func TestNodePublishVolume_MissingTargetPath(t *testing.T) {
	d := &Driver{
		name:     "btrfs.csi.tesslate.io",
		nodeID:   "node-1",
		poolPath: "/pool",
	}
	ns := &NodeServer{driver: d}

	_, err := ns.NodePublishVolume(context.Background(), &csi.NodePublishVolumeRequest{
		VolumeId:   "vol-123",
		TargetPath: "",
	})
	if err == nil {
		t.Fatal("expected error for missing target path")
	}

	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("error is not a gRPC status: %v", err)
	}
	if st.Code() != codes.InvalidArgument {
		t.Errorf("error code = %v, want %v", st.Code(), codes.InvalidArgument)
	}
}

func TestNodeUnpublishVolume_MissingVolumeID(t *testing.T) {
	d := &Driver{
		name:   "btrfs.csi.tesslate.io",
		nodeID: "node-1",
	}
	ns := &NodeServer{driver: d}

	_, err := ns.NodeUnpublishVolume(context.Background(), &csi.NodeUnpublishVolumeRequest{
		VolumeId:   "",
		TargetPath: "/mnt/target",
	})
	if err == nil {
		t.Fatal("expected error for missing volume ID")
	}

	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("error is not a gRPC status: %v", err)
	}
	if st.Code() != codes.InvalidArgument {
		t.Errorf("error code = %v, want %v", st.Code(), codes.InvalidArgument)
	}
}
