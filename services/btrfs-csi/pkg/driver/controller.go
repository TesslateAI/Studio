package driver

import (
	"context"
	"fmt"
	"path/filepath"
	"sync"
	"time"

	"github.com/container-storage-interface/spec/lib/go/csi"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
	"k8s.io/klog/v2"
)

// ControllerServer implements the CSI Controller service.
// It delegates all btrfs operations to the node plugin via the nodeOps interface.
type ControllerServer struct {
	csi.UnimplementedControllerServer
	driver *Driver

	// mu protects concurrent volume/snapshot operations against race conditions.
	mu sync.Mutex

	// snapSourceMap tracks which volume each snapshot came from, keyed by snap ID.
	// This enables ListSnapshots source_volume_id filtering.
	snapSourceMap map[string]string
}

// NewControllerServer creates a new ControllerServer.
func NewControllerServer(d *Driver) *ControllerServer {
	return &ControllerServer{
		driver:        d,
		snapSourceMap: make(map[string]string),
	}
}

// CreateVolume creates a new btrfs subvolume. Supports three modes:
//  1. From template: snapshot from /pool/templates/{template}
//  2. From snapshot (restore): snapshot from /pool/snapshots/{snap-id}
//  3. Empty: create a new empty subvolume
func (cs *ControllerServer) CreateVolume(
	ctx context.Context,
	req *csi.CreateVolumeRequest,
) (*csi.CreateVolumeResponse, error) {
	if req.GetName() == "" {
		return nil, status.Error(codes.InvalidArgument, "volume name is required")
	}

	cs.mu.Lock()
	defer cs.mu.Unlock()

	volID := req.GetName()
	volRelPath := filepath.Join("volumes", volID)

	// Check if volume already exists (idempotent create).
	exists, err := cs.driver.nodeOps.SubvolumeExists(ctx, volRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check volume existence: %v", err)
	}
	if exists {
		klog.Infof("Volume %q already exists, returning existing", volID)
		return cs.buildVolumeResponse(volID, req), nil
	}

	params := req.GetParameters()
	contentSource := req.GetVolumeContentSource()

	switch {
	case contentSource != nil && contentSource.GetSnapshot() != nil:
		// Restore from snapshot.
		snapID := contentSource.GetSnapshot().GetSnapshotId()
		snapRelPath := filepath.Join("snapshots", snapID)

		snapExists, err := cs.driver.nodeOps.SubvolumeExists(ctx, snapRelPath)
		if err != nil {
			return nil, status.Errorf(codes.Internal, "check snapshot existence: %v", err)
		}
		if !snapExists {
			return nil, status.Errorf(codes.NotFound, "source snapshot %q not found", snapID)
		}

		klog.Infof("Creating volume %q from snapshot %q", volID, snapID)
		if err := cs.driver.nodeOps.SnapshotSubvolume(ctx, snapRelPath, volRelPath, false); err != nil {
			return nil, status.Errorf(codes.Internal, "failed to create volume from snapshot: %v", err)
		}

	case params["template"] != "":
		// Create from template.
		tmplName := params["template"]
		tmplRelPath := filepath.Join("templates", tmplName)

		// Ensure the template exists (download from S3 if needed).
		if err := cs.driver.nodeOps.EnsureTemplate(ctx, tmplName); err != nil {
			klog.Warningf("EnsureTemplate %q failed: %v", tmplName, err)
		}

		tmplExists, err := cs.driver.nodeOps.SubvolumeExists(ctx, tmplRelPath)
		if err != nil {
			return nil, status.Errorf(codes.Internal, "check template existence: %v", err)
		}
		if !tmplExists {
			return nil, status.Errorf(codes.NotFound, "template %q not found", tmplName)
		}

		klog.Infof("Creating volume %q from template %q", volID, tmplName)
		if err := cs.driver.nodeOps.SnapshotSubvolume(ctx, tmplRelPath, volRelPath, false); err != nil {
			return nil, status.Errorf(codes.Internal, "failed to create volume from template: %v", err)
		}

	default:
		// Create empty subvolume.
		klog.Infof("Creating empty volume %q", volID)
		if err := cs.driver.nodeOps.CreateSubvolume(ctx, volRelPath); err != nil {
			return nil, status.Errorf(codes.Internal, "failed to create subvolume: %v", err)
		}
	}

	// Register the volume for periodic sync.
	if err := cs.driver.nodeOps.TrackVolume(ctx, volID); err != nil {
		klog.Warningf("Failed to track volume %q for sync: %v", volID, err)
	}

	return cs.buildVolumeResponse(volID, req), nil
}

// buildVolumeResponse constructs the CreateVolumeResponse with topology constraints.
func (cs *ControllerServer) buildVolumeResponse(
	volID string,
	req *csi.CreateVolumeRequest,
) *csi.CreateVolumeResponse {
	topologyKey := cs.driver.name + "/node"

	resp := &csi.CreateVolumeResponse{
		Volume: &csi.Volume{
			VolumeId:      volID,
			CapacityBytes: req.GetCapacityRange().GetRequiredBytes(),
			AccessibleTopology: []*csi.Topology{
				{
					Segments: map[string]string{
						topologyKey: cs.driver.nodeID,
					},
				},
			},
		},
	}

	if src := req.GetVolumeContentSource(); src != nil {
		resp.Volume.ContentSource = src
	}

	return resp
}

// DeleteVolume deletes a btrfs subvolume.
func (cs *ControllerServer) DeleteVolume(
	ctx context.Context,
	req *csi.DeleteVolumeRequest,
) (*csi.DeleteVolumeResponse, error) {
	if req.GetVolumeId() == "" {
		return nil, status.Error(codes.InvalidArgument, "volume ID is required")
	}

	cs.mu.Lock()
	defer cs.mu.Unlock()

	volID := req.GetVolumeId()
	volRelPath := filepath.Join("volumes", volID)

	exists, err := cs.driver.nodeOps.SubvolumeExists(ctx, volRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check volume existence: %v", err)
	}
	if !exists {
		klog.Infof("Volume %q does not exist, returning success (idempotent)", volID)
		return &csi.DeleteVolumeResponse{}, nil
	}

	// Untrack from sync before deletion.
	if err := cs.driver.nodeOps.UntrackVolume(ctx, volID); err != nil {
		klog.Warningf("Failed to untrack volume %q from sync: %v", volID, err)
	}

	klog.Infof("Deleting volume %q", volID)
	if err := cs.driver.nodeOps.DeleteSubvolume(ctx, volRelPath); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to delete subvolume: %v", err)
	}

	return &csi.DeleteVolumeResponse{}, nil
}

// CreateSnapshot creates a read-only btrfs snapshot.
func (cs *ControllerServer) CreateSnapshot(
	ctx context.Context,
	req *csi.CreateSnapshotRequest,
) (*csi.CreateSnapshotResponse, error) {
	if req.GetSourceVolumeId() == "" {
		return nil, status.Error(codes.InvalidArgument, "source volume ID is required")
	}
	if req.GetName() == "" {
		return nil, status.Error(codes.InvalidArgument, "snapshot name is required")
	}

	cs.mu.Lock()
	defer cs.mu.Unlock()

	volID := req.GetSourceVolumeId()
	snapID := req.GetName()
	volRelPath := filepath.Join("volumes", volID)
	snapRelPath := filepath.Join("snapshots", snapID)

	// Check if snapshot already exists (idempotent).
	snapExists, err := cs.driver.nodeOps.SubvolumeExists(ctx, snapRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check snapshot existence: %v", err)
	}
	if snapExists {
		klog.Infof("Snapshot %q already exists, returning existing", snapID)
		return cs.buildSnapshotResponse(snapID, volID), nil
	}

	// Verify the source volume exists.
	volExists, err := cs.driver.nodeOps.SubvolumeExists(ctx, volRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check volume existence: %v", err)
	}
	if !volExists {
		return nil, status.Errorf(codes.NotFound, "source volume %q not found", volID)
	}

	klog.Infof("Creating read-only snapshot %q from volume %q", snapID, volID)
	if err := cs.driver.nodeOps.SnapshotSubvolume(ctx, volRelPath, snapRelPath, true); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to create snapshot: %v", err)
	}

	// Track the source volume for ListSnapshots filtering.
	cs.snapSourceMap[snapID] = volID

	return cs.buildSnapshotResponse(snapID, volID), nil
}

// buildSnapshotResponse constructs the CreateSnapshotResponse.
func (cs *ControllerServer) buildSnapshotResponse(
	snapID, sourceVolID string,
) *csi.CreateSnapshotResponse {
	return &csi.CreateSnapshotResponse{
		Snapshot: &csi.Snapshot{
			SnapshotId:     snapID,
			SourceVolumeId: sourceVolID,
			CreationTime:   timestamppb.Now(),
			ReadyToUse:     true,
		},
	}
}

// DeleteSnapshot deletes a btrfs snapshot.
func (cs *ControllerServer) DeleteSnapshot(
	ctx context.Context,
	req *csi.DeleteSnapshotRequest,
) (*csi.DeleteSnapshotResponse, error) {
	if req.GetSnapshotId() == "" {
		return nil, status.Error(codes.InvalidArgument, "snapshot ID is required")
	}

	cs.mu.Lock()
	defer cs.mu.Unlock()

	snapID := req.GetSnapshotId()
	snapRelPath := filepath.Join("snapshots", snapID)

	snapExists, err := cs.driver.nodeOps.SubvolumeExists(ctx, snapRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check snapshot existence: %v", err)
	}
	if !snapExists {
		klog.Infof("Snapshot %q does not exist, returning success (idempotent)", snapID)
		return &csi.DeleteSnapshotResponse{}, nil
	}

	klog.Infof("Deleting snapshot %q", snapID)
	if err := cs.driver.nodeOps.DeleteSubvolume(ctx, snapRelPath); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to delete snapshot: %v", err)
	}

	delete(cs.snapSourceMap, snapID)

	return &csi.DeleteSnapshotResponse{}, nil
}

// ValidateVolumeCapabilities checks whether the requested capabilities are supported.
func (cs *ControllerServer) ValidateVolumeCapabilities(
	ctx context.Context,
	req *csi.ValidateVolumeCapabilitiesRequest,
) (*csi.ValidateVolumeCapabilitiesResponse, error) {
	if req.GetVolumeId() == "" {
		return nil, status.Error(codes.InvalidArgument, "volume ID is required")
	}
	if len(req.GetVolumeCapabilities()) == 0 {
		return nil, status.Error(codes.InvalidArgument, "volume capabilities are required")
	}

	volRelPath := filepath.Join("volumes", req.GetVolumeId())
	volExists, err := cs.driver.nodeOps.SubvolumeExists(ctx, volRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check volume existence: %v", err)
	}
	if !volExists {
		return nil, status.Errorf(codes.NotFound, "volume %q not found", req.GetVolumeId())
	}

	for _, cap := range req.GetVolumeCapabilities() {
		if cap.GetAccessMode().GetMode() != csi.VolumeCapability_AccessMode_SINGLE_NODE_WRITER {
			return &csi.ValidateVolumeCapabilitiesResponse{
				Message: fmt.Sprintf("unsupported access mode: %v", cap.GetAccessMode().GetMode()),
			}, nil
		}
		if cap.GetMount() == nil {
			return &csi.ValidateVolumeCapabilitiesResponse{
				Message: "only mount access type is supported",
			}, nil
		}
	}

	return &csi.ValidateVolumeCapabilitiesResponse{
		Confirmed: &csi.ValidateVolumeCapabilitiesResponse_Confirmed{
			VolumeCapabilities: req.GetVolumeCapabilities(),
		},
	}, nil
}

// GetCapacity returns the available capacity on the btrfs pool.
func (cs *ControllerServer) GetCapacity(
	ctx context.Context,
	req *csi.GetCapacityRequest,
) (*csi.GetCapacityResponse, error) {
	_, available, err := cs.driver.nodeOps.GetCapacity(ctx)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to get pool capacity: %v", err)
	}

	return &csi.GetCapacityResponse{
		AvailableCapacity: available,
	}, nil
}

// ListVolumes lists all btrfs subvolumes under /pool/volumes/.
func (cs *ControllerServer) ListVolumes(
	ctx context.Context,
	req *csi.ListVolumesRequest,
) (*csi.ListVolumesResponse, error) {
	entries, err := cs.driver.nodeOps.ListSubvolumes(ctx, "volumes/")
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to list volumes: %v", err)
	}

	var volEntries []*csi.ListVolumesResponse_Entry
	_ = req.GetStartingToken()

	for _, info := range entries {
		volEntries = append(volEntries, &csi.ListVolumesResponse_Entry{
			Volume: &csi.Volume{
				VolumeId: info.Name,
			},
		})
	}

	return &csi.ListVolumesResponse{
		Entries: volEntries,
	}, nil
}

// ListSnapshots lists btrfs snapshots with optional source_volume_id filtering.
func (cs *ControllerServer) ListSnapshots(
	ctx context.Context,
	req *csi.ListSnapshotsRequest,
) (*csi.ListSnapshotsResponse, error) {
	entries, err := cs.driver.nodeOps.ListSubvolumes(ctx, "snapshots/")
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to list snapshots: %v", err)
	}

	// Filter by snapshot ID if specified.
	if req.GetSnapshotId() != "" {
		filtered := entries[:0]
		for _, e := range entries {
			if e.Name == req.GetSnapshotId() {
				filtered = append(filtered, e)
			}
		}
		entries = filtered
	}

	// Filter by source volume ID if specified.
	if req.GetSourceVolumeId() != "" {
		cs.mu.Lock()
		filtered := entries[:0]
		for _, e := range entries {
			if srcVol, ok := cs.snapSourceMap[e.Name]; ok && srcVol == req.GetSourceVolumeId() {
				filtered = append(filtered, e)
			}
		}
		cs.mu.Unlock()
		entries = filtered
	}

	var snapEntries []*csi.ListSnapshotsResponse_Entry
	for _, info := range entries {
		creationTime := timestamppb.New(time.Now())
		sourceVolID := cs.snapSourceMap[info.Name]

		snapEntries = append(snapEntries, &csi.ListSnapshotsResponse_Entry{
			Snapshot: &csi.Snapshot{
				SnapshotId:     info.Name,
				SourceVolumeId: sourceVolID,
				CreationTime:   creationTime,
				ReadyToUse:     true,
			},
		})
	}

	return &csi.ListSnapshotsResponse{
		Entries: snapEntries,
	}, nil
}

// ControllerGetCapabilities reports controller capabilities.
func (cs *ControllerServer) ControllerGetCapabilities(
	ctx context.Context,
	req *csi.ControllerGetCapabilitiesRequest,
) (*csi.ControllerGetCapabilitiesResponse, error) {
	caps := []csi.ControllerServiceCapability_RPC_Type{
		csi.ControllerServiceCapability_RPC_CREATE_DELETE_VOLUME,
		csi.ControllerServiceCapability_RPC_CREATE_DELETE_SNAPSHOT,
		csi.ControllerServiceCapability_RPC_GET_CAPACITY,
		csi.ControllerServiceCapability_RPC_LIST_VOLUMES,
		csi.ControllerServiceCapability_RPC_LIST_SNAPSHOTS,
	}

	var csiCaps []*csi.ControllerServiceCapability
	for _, c := range caps {
		csiCaps = append(csiCaps, &csi.ControllerServiceCapability{
			Type: &csi.ControllerServiceCapability_Rpc{
				Rpc: &csi.ControllerServiceCapability_RPC{
					Type: c,
				},
			},
		})
	}

	return &csi.ControllerGetCapabilitiesResponse{
		Capabilities: csiCaps,
	}, nil
}
