package volumehub

import (
	"context"
	"fmt"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
)

// HubClient wraps a gRPC connection to the VolumeHub for manifest-write RPCs.
// Used by CSI nodes to delegate all manifest/tombstone mutations to the Hub
// (single-writer model).
type HubClient struct {
	conn *grpc.ClientConn
}

// NewHubClient connects to the VolumeHub gRPC server at the given address.
func NewHubClient(addr string) (*HubClient, error) {
	conn, err := grpc.NewClient(addr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithDefaultCallOptions(
			grpc.ForceCodec(jsonCodec{}),
			grpc.MaxCallRecvMsgSize(64*1024*1024),
			grpc.MaxCallSendMsgSize(64*1024*1024),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("connect to hub at %s: %w", addr, err)
	}
	klog.V(2).Infof("Hub manifest client connected to %s", addr)
	return &HubClient{conn: conn}, nil
}

// Close closes the underlying gRPC connection.
func (c *HubClient) Close() error { return c.conn.Close() }

func (c *HubClient) invoke(ctx context.Context, method string, req, resp interface{}) error {
	return c.conn.Invoke(ctx, "/volumehub.VolumeHub/"+method, req, resp)
}

// --- Request/response types (shared with server handlers) ---

// AppendSnapshotRequest is the request for the AppendSnapshot RPC.
type AppendSnapshotRequest struct {
	VolumeID string       `json:"volume_id"`
	Snapshot cas.Snapshot `json:"snapshot"`
}

// AppendSnapshotResponse is the response for the AppendSnapshot RPC.
type AppendSnapshotResponse struct {
	Head string `json:"head"`
}

// SetManifestHeadRequest is the request for the SetManifestHead RPC.
type SetManifestHeadRequest struct {
	VolumeID       string `json:"volume_id"`
	TargetHash     string `json:"target_hash"`
	SaveBranchName string `json:"save_branch_name,omitempty"`
}

// SetManifestHeadResponse is the response for the SetManifestHead RPC.
type SetManifestHeadResponse struct {
	Head        string `json:"head"`
	BranchSaved bool   `json:"branch_saved"`
}

// DeleteVolumeManifestRequest is the request for the DeleteVolumeManifest RPC.
type DeleteVolumeManifestRequest struct {
	VolumeID string `json:"volume_id"`
}

// DeleteTombstoneRequest is the request for the DeleteTombstone RPC.
type DeleteTombstoneRequest struct {
	VolumeID string `json:"volume_id"`
}

// --- RPC methods (satisfy sync.HubOps interface) ---

// AppendSnapshot calls the Hub to append a snapshot to the manifest DAG.
func (c *HubClient) AppendSnapshot(ctx context.Context, volumeID string, snap cas.Snapshot) (string, error) {
	var resp AppendSnapshotResponse
	err := c.invoke(ctx, "AppendSnapshot", &AppendSnapshotRequest{
		VolumeID: volumeID,
		Snapshot: snap,
	}, &resp)
	return resp.Head, err
}

// SetManifestHead calls the Hub to move HEAD and optionally save a branch.
func (c *HubClient) SetManifestHead(ctx context.Context, volumeID, targetHash, saveBranchName string) (string, bool, error) {
	var resp SetManifestHeadResponse
	err := c.invoke(ctx, "SetManifestHead", &SetManifestHeadRequest{
		VolumeID:       volumeID,
		TargetHash:     targetHash,
		SaveBranchName: saveBranchName,
	}, &resp)
	return resp.Head, resp.BranchSaved, err
}

// DeleteVolumeManifest calls the Hub to delete a volume's manifest.
func (c *HubClient) DeleteVolumeManifest(ctx context.Context, volumeID string) error {
	return c.invoke(ctx, "DeleteVolumeManifest", &DeleteVolumeManifestRequest{VolumeID: volumeID}, &Empty{})
}

// DeleteTombstone calls the Hub to remove a volume's tombstone.
func (c *HubClient) DeleteTombstone(ctx context.Context, volumeID string) error {
	return c.invoke(ctx, "DeleteTombstone", &DeleteTombstoneRequest{VolumeID: volumeID}, &Empty{})
}
