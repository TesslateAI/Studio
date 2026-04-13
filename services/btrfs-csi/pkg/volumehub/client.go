package volumehub

import (
	"context"
	"fmt"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/lease"
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

// GetManifestGraphRequest is the request for the GetManifestGraph RPC.
type GetManifestGraphRequest struct {
	VolumeID string `json:"volume_id"`
}

// GetManifestGraphResponse is the response for the GetManifestGraph RPC.
type GetManifestGraphResponse struct {
	Head      string            `json:"head"`
	Branches  map[string]string `json:"branches"`  // name → hash
	Snapshots []cas.Snapshot    `json:"snapshots"`  // ALL snapshots in the DAG
}

// CreateBranchRequest is the request for the CreateBranch RPC.
type CreateBranchRequest struct {
	VolumeID string `json:"volume_id"`
	Name     string `json:"name"`
	Hash     string `json:"hash"` // snapshot hash to point the branch at
}

// CreateBranchResponse is the response for the CreateBranch RPC.
type CreateBranchResponse struct {
	Name string `json:"name"`
	Hash string `json:"hash"`
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

// GetManifestGraph returns the full manifest DAG for a volume.
func (c *HubClient) GetManifestGraph(ctx context.Context, volumeID string) (*GetManifestGraphResponse, error) {
	var resp GetManifestGraphResponse
	err := c.invoke(ctx, "GetManifestGraph", &GetManifestGraphRequest{VolumeID: volumeID}, &resp)
	if err != nil {
		return nil, err
	}
	return &resp, nil
}

// CreateBranch saves a named branch pointer on the volume's manifest.
func (c *HubClient) CreateBranch(ctx context.Context, volumeID, name, hash string) error {
	return c.invoke(ctx, "CreateBranch", &CreateBranchRequest{
		VolumeID: volumeID,
		Name:     name,
		Hash:     hash,
	}, &CreateBranchResponse{})
}

// --- Lease RPC methods (satisfy sync.HubOps interface) ---

// AcquireVolumeLease attempts to acquire an exclusive lease on a volume.
func (c *HubClient) AcquireVolumeLease(ctx context.Context, volumeID, holder string, ttl time.Duration) (bool, string, error) {
	var resp AcquireVolumeLeaseResponse
	err := c.invoke(ctx, "AcquireVolumeLease", &AcquireVolumeLeaseRequest{
		VolumeID:  volumeID,
		Holder:    holder,
		TTLMillis: ttl.Milliseconds(),
	}, &resp)
	return resp.Acquired, resp.CurrentHolder, err
}

// ReleaseVolumeLease releases a previously acquired lease.
func (c *HubClient) ReleaseVolumeLease(ctx context.Context, volumeID, holder string) error {
	return c.invoke(ctx, "ReleaseVolumeLease", &ReleaseVolumeLeaseRequest{
		VolumeID: volumeID,
		Holder:   holder,
	}, &Empty{})
}

// RenewVolumeLease extends the TTL of a held lease. Returns revoked=true if
// the lease was revoked (holder should abort).
func (c *HubClient) RenewVolumeLease(ctx context.Context, volumeID, holder string, ttl time.Duration) (bool, bool, error) {
	var resp RenewVolumeLeaseResponse
	err := c.invoke(ctx, "RenewVolumeLease", &RenewVolumeLeaseRequest{
		VolumeID:  volumeID,
		Holder:    holder,
		TTLMillis: ttl.Milliseconds(),
	}, &resp)
	return resp.Renewed, resp.Revoked, err
}

// BatchAcquireLease acquires leases for multiple volumes atomically.
func (c *HubClient) BatchAcquireLease(ctx context.Context, requests []lease.BatchReq) ([]lease.BatchResult, error) {
	items := make([]LeaseRequestItem, len(requests))
	for i, r := range requests {
		items[i] = LeaseRequestItem{
			VolumeID:  r.VolumeID,
			Holder:    r.Holder,
			TTLMillis: r.TTL.Milliseconds(),
		}
	}
	var resp BatchAcquireLeaseResponse
	err := c.invoke(ctx, "BatchAcquireLease", &BatchAcquireLeaseRequest{Leases: items}, &resp)
	if err != nil {
		return nil, err
	}
	results := make([]lease.BatchResult, len(resp.Results))
	for i, r := range resp.Results {
		results[i] = lease.BatchResult{
			VolumeID:      r.VolumeID,
			Acquired:      r.Acquired,
			CurrentHolder: r.CurrentHolder,
		}
	}
	return results, nil
}
