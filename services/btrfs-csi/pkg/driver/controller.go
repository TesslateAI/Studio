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

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/volumehub"
)

// ControllerServer implements the CSI Controller service.
// In Hub mode it delegates volume placement to the VolumeHub (topology-aware).
// In ModeAll (minikube) it delegates to nodeOps directly.
type ControllerServer struct {
	csi.UnimplementedControllerServer
	driver *Driver
	hub    *volumehub.Server // non-nil in Hub mode

	// mu protects concurrent volume/snapshot operations against race conditions.
	mu sync.Mutex

	// snapSourceMap tracks which volume each snapshot came from, keyed by snap ID.
	// This enables ListSnapshots source_volume_id filtering.
	// TODO: replace with a struct to include createdAt timestamp — currently
	// ListSnapshots returns time.Now() instead of actual creation time.
	snapSourceMap map[string]string

	// snapNodeMap tracks which compute node each snapshot lives on (Hub mode).
	snapNodeMap map[string]string
}

// NewControllerServer creates a new ControllerServer. Pass a non-nil hub for
// Hub mode (production K8s) or nil for direct nodeOps mode (ModeAll/minikube).
func NewControllerServer(d *Driver, hub *volumehub.Server) *ControllerServer {
	return &ControllerServer{
		driver:        d,
		hub:           hub,
		snapSourceMap: make(map[string]string),
		snapNodeMap:   make(map[string]string),
	}
}

// ---------------------------------------------------------------------------
// CreateVolume
// ---------------------------------------------------------------------------

// CreateVolume creates a new btrfs subvolume. Supports three modes:
//  1. From template: snapshot from /pool/templates/{template}
//  2. From snapshot (restore): snapshot from /pool/snapshots/{snap-id}
//  3. Empty: create a new empty subvolume
//
// In Hub mode, topology requirements are extracted from the request and passed
// as a hint to the Hub for correct node placement.
func (cs *ControllerServer) CreateVolume(
	ctx context.Context,
	req *csi.CreateVolumeRequest,
) (*csi.CreateVolumeResponse, error) {
	if req.GetName() == "" {
		return nil, status.Error(codes.InvalidArgument, "volume name is required")
	}

	cs.mu.Lock()
	defer cs.mu.Unlock()

	if cs.hub != nil {
		return cs.createVolumeHub(ctx, req)
	}
	return cs.createVolumeDirect(ctx, req)
}

// createVolumeHub creates a volume via the Hub (topology-aware node selection).
func (cs *ControllerServer) createVolumeHub(
	ctx context.Context,
	req *csi.CreateVolumeRequest,
) (*csi.CreateVolumeResponse, error) {
	volID := req.GetName()
	params := req.GetParameters()
	contentSource := req.GetVolumeContentSource()

	// Idempotent: if the Hub already knows this volume, return it.
	if cs.hub.VolumeRegistered(volID) {
		nodeName := cs.hub.GetOwnerNode(volID)
		return cs.buildVolumeResponseForNode(volID, nodeName, req), nil
	}

	// Extract topology hint from K8s scheduler's preferred or requisite segments.
	// Preferred is a soft hint; Requisite is a hard constraint (CSI spec §5.6).
	topologyKey := cs.driver.name + "/node"
	hintNode := ""
	if topoReq := req.GetAccessibilityRequirements(); topoReq != nil {
		if prefs := topoReq.GetPreferred(); len(prefs) > 0 {
			hintNode = prefs[0].Segments[topologyKey]
		} else if reqs := topoReq.GetRequisite(); len(reqs) > 0 {
			hintNode = reqs[0].Segments[topologyKey]
		}
	}

	switch {
	case contentSource != nil && contentSource.GetSnapshot() != nil:
		// Restore from snapshot — must be on the snapshot's node.
		snapID := contentSource.GetSnapshot().GetSnapshotId()
		snapNode := cs.snapNodeMap[snapID]
		if snapNode == "" {
			// Fallback: scan nodes for the snapshot subvolume. This handles
			// Hub pod restarts where the in-memory snapNodeMap was lost.
			snapNode = cs.findSnapshotNode(ctx, snapID)
		}
		if snapNode == "" {
			return nil, status.Errorf(codes.NotFound, "snapshot %q not found on any node", snapID)
		}

		client, err := cs.hub.NodeClientFor(snapNode)
		if err != nil {
			return nil, status.Errorf(codes.Internal, "connect to node %s: %v", snapNode, err)
		}
		defer client.Close()

		snapRelPath := filepath.Join("snapshots", snapID)
		volRelPath := filepath.Join("volumes", volID)

		// Verify snapshot exists.
		snapExists, err := client.SubvolumeExists(ctx, snapRelPath)
		if err != nil {
			return nil, status.Errorf(codes.Internal, "check snapshot existence: %v", err)
		}
		if !snapExists {
			return nil, status.Errorf(codes.NotFound, "source snapshot %q not found on node %s", snapID, snapNode)
		}

		klog.Infof("Creating volume %q from snapshot %q on node %s", volID, snapID, snapNode)
		if err := client.SnapshotSubvolume(ctx, snapRelPath, volRelPath, false); err != nil {
			return nil, status.Errorf(codes.Internal, "create volume from snapshot: %v", err)
		}

		if err := client.TrackVolume(ctx, volID, "", ""); err != nil {
			klog.Warningf("TrackVolume %s on %s: %v", volID, snapNode, err)
		}

		cs.hub.Registry().RegisterVolume(volID)
		cs.hub.Registry().SetOwner(volID, snapNode)
		cs.hub.Registry().SetCached(volID, snapNode)

		return cs.buildVolumeResponseForNode(volID, snapNode, req), nil

	default:
		// Empty or from template — delegate to Hub for node selection.
		template := params["template"]
		nodeName, err := cs.hub.CreateVolumeOnNode(ctx, volID, template, hintNode)
		if err != nil {
			return nil, status.Errorf(codes.Internal, "%v", err)
		}

		// Apply storage quota if configured.
		cs.applyQuotaHub(ctx, volID, nodeName, params)

		return cs.buildVolumeResponseForNode(volID, nodeName, req), nil
	}
}

// createVolumeDirect creates a volume via nodeOps (ModeAll / minikube).
func (cs *ControllerServer) createVolumeDirect(
	ctx context.Context,
	req *csi.CreateVolumeRequest,
) (*csi.CreateVolumeResponse, error) {
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
		tmplName := params["template"]
		tmplRelPath := filepath.Join("templates", tmplName)

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
		klog.Infof("Creating empty volume %q", volID)
		if err := cs.driver.nodeOps.CreateSubvolume(ctx, volRelPath); err != nil {
			return nil, status.Errorf(codes.Internal, "failed to create subvolume: %v", err)
		}
	}

	// Register the volume for periodic CAS sync.
	templateName := params["template"]
	if err := cs.driver.nodeOps.TrackVolume(ctx, volID, templateName, ""); err != nil {
		klog.Warningf("Failed to track volume %q for sync: %v", volID, err)
	}

	// Apply storage quota if configured.
	quotaStr := params["quota"]
	quotaBytes := cs.driver.defaultQuota
	if quotaStr != "" {
		quotaBytes = ParseQuota(quotaStr)
	}
	if quotaBytes > 0 {
		volName := fmt.Sprintf("volumes/%s", volID)
		if qErr := cs.driver.nodeOps.SetQgroupLimit(ctx, volName, quotaBytes); qErr != nil {
			klog.Warningf("Failed to set quota for %s: %v", volID, qErr)
		}
	}

	return cs.buildVolumeResponse(volID, req), nil
}

// applyQuotaHub applies storage quota on the given node if configured.
func (cs *ControllerServer) applyQuotaHub(ctx context.Context, volID, nodeName string, params map[string]string) {
	quotaStr := params["quota"]
	quotaBytes := cs.driver.defaultQuota
	if quotaStr != "" {
		quotaBytes = ParseQuota(quotaStr)
	}
	if quotaBytes > 0 {
		client, err := cs.hub.NodeClientFor(nodeName)
		if err != nil {
			klog.Warningf("Failed to connect to %s for quota: %v", nodeName, err)
			return
		}
		defer client.Close()
		if qErr := client.SetQgroupLimit(ctx, "volumes/"+volID, quotaBytes); qErr != nil {
			klog.Warningf("Failed to set quota for %s on %s: %v", volID, nodeName, qErr)
		}
	}
}

// ---------------------------------------------------------------------------
// Volume response builders
// ---------------------------------------------------------------------------

// buildVolumeResponse constructs the CreateVolumeResponse with local node
// topology (ModeAll — single-node, uses driver.nodeID).
func (cs *ControllerServer) buildVolumeResponse(
	volID string,
	req *csi.CreateVolumeRequest,
) *csi.CreateVolumeResponse {
	return cs.buildVolumeResponseForNode(volID, cs.driver.nodeID, req)
}

// buildVolumeResponseForNode constructs the CreateVolumeResponse with the
// given node as the accessible topology.
func (cs *ControllerServer) buildVolumeResponseForNode(
	volID, nodeName string,
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
						topologyKey: nodeName,
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

// ---------------------------------------------------------------------------
// DeleteVolume
// ---------------------------------------------------------------------------

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

	if cs.hub != nil {
		if err := cs.hub.DeleteVolumeFromNode(ctx, volID); err != nil {
			return nil, status.Errorf(codes.Internal, "%v", err)
		}
		return &csi.DeleteVolumeResponse{}, nil
	}

	// Direct nodeOps path (ModeAll).
	volRelPath := filepath.Join("volumes", volID)

	exists, err := cs.driver.nodeOps.SubvolumeExists(ctx, volRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check volume existence: %v", err)
	}
	if !exists {
		klog.Infof("Volume %q does not exist, returning success (idempotent)", volID)
		return &csi.DeleteVolumeResponse{}, nil
	}

	if err := cs.driver.nodeOps.UntrackVolume(ctx, volID); err != nil {
		klog.Warningf("Failed to untrack volume %q from sync: %v", volID, err)
	}

	klog.Infof("Deleting volume %q", volID)
	if err := cs.driver.nodeOps.DeleteSubvolume(ctx, volRelPath); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to delete subvolume: %v", err)
	}

	return &csi.DeleteVolumeResponse{}, nil
}

// ---------------------------------------------------------------------------
// CreateSnapshot / DeleteSnapshot
// ---------------------------------------------------------------------------

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

	if cs.hub != nil {
		return cs.createSnapshotHub(ctx, volID, snapID)
	}
	return cs.createSnapshotDirect(ctx, volID, snapID)
}

// createSnapshotHub creates a read-only snapshot on the volume's owner node.
func (cs *ControllerServer) createSnapshotHub(
	ctx context.Context,
	volID, snapID string,
) (*csi.CreateSnapshotResponse, error) {
	ownerNode := cs.hub.GetOwnerNode(volID)
	if ownerNode == "" {
		return nil, status.Errorf(codes.NotFound, "source volume %q not registered", volID)
	}

	client, err := cs.hub.NodeClientFor(ownerNode)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "connect to owner %s: %v", ownerNode, err)
	}
	defer client.Close()

	snapRelPath := filepath.Join("snapshots", snapID)
	volRelPath := filepath.Join("volumes", volID)

	// Idempotent: if snapshot already exists, return it.
	snapExists, err := client.SubvolumeExists(ctx, snapRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check snapshot existence: %v", err)
	}
	if snapExists {
		klog.Infof("Snapshot %q already exists on %s, returning existing", snapID, ownerNode)
		return cs.buildSnapshotResponse(snapID, volID), nil
	}

	// Verify source volume exists on the node.
	volExists, err := client.SubvolumeExists(ctx, volRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check volume existence: %v", err)
	}
	if !volExists {
		return nil, status.Errorf(codes.NotFound, "source volume %q not found on node %s", volID, ownerNode)
	}

	klog.Infof("Creating read-only snapshot %q from volume %q on node %s", snapID, volID, ownerNode)
	if err := client.SnapshotSubvolume(ctx, volRelPath, snapRelPath, true); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to create snapshot: %v", err)
	}

	cs.snapSourceMap[snapID] = volID
	cs.snapNodeMap[snapID] = ownerNode

	return cs.buildSnapshotResponse(snapID, volID), nil
}

// createSnapshotDirect creates a read-only snapshot via nodeOps (ModeAll).
func (cs *ControllerServer) createSnapshotDirect(
	ctx context.Context,
	volID, snapID string,
) (*csi.CreateSnapshotResponse, error) {
	volRelPath := filepath.Join("volumes", volID)
	snapRelPath := filepath.Join("snapshots", snapID)

	snapExists, err := cs.driver.nodeOps.SubvolumeExists(ctx, snapRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check snapshot existence: %v", err)
	}
	if snapExists {
		klog.Infof("Snapshot %q already exists, returning existing", snapID)
		return cs.buildSnapshotResponse(snapID, volID), nil
	}

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

	if cs.hub != nil {
		return cs.deleteSnapshotHub(ctx, snapID)
	}
	return cs.deleteSnapshotDirect(ctx, snapID)
}

// deleteSnapshotHub deletes a snapshot on the tracked node.
func (cs *ControllerServer) deleteSnapshotHub(
	ctx context.Context,
	snapID string,
) (*csi.DeleteSnapshotResponse, error) {
	nodeName := cs.snapNodeMap[snapID]
	if nodeName == "" {
		// Snapshot not tracked — may have been created before the merge.
		// Return success (idempotent) since we can't find it.
		klog.Infof("Snapshot %q not tracked, returning success (idempotent)", snapID)
		return &csi.DeleteSnapshotResponse{}, nil
	}

	client, err := cs.hub.NodeClientFor(nodeName)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "connect to node %s: %v", nodeName, err)
	}
	defer client.Close()

	snapRelPath := filepath.Join("snapshots", snapID)

	snapExists, err := client.SubvolumeExists(ctx, snapRelPath)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "check snapshot existence: %v", err)
	}
	if !snapExists {
		klog.Infof("Snapshot %q not on node %s, returning success (idempotent)", snapID, nodeName)
		delete(cs.snapSourceMap, snapID)
		delete(cs.snapNodeMap, snapID)
		return &csi.DeleteSnapshotResponse{}, nil
	}

	klog.Infof("Deleting snapshot %q on node %s", snapID, nodeName)
	if err := client.DeleteSubvolume(ctx, snapRelPath); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to delete snapshot: %v", err)
	}

	delete(cs.snapSourceMap, snapID)
	delete(cs.snapNodeMap, snapID)

	return &csi.DeleteSnapshotResponse{}, nil
}

// deleteSnapshotDirect deletes a snapshot via nodeOps (ModeAll).
func (cs *ControllerServer) deleteSnapshotDirect(
	ctx context.Context,
	snapID string,
) (*csi.DeleteSnapshotResponse, error) {
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

// findSnapshotNode scans all registered nodes for a snapshot subvolume.
// Used as a fallback when snapNodeMap is empty (e.g., after Hub pod restart).
func (cs *ControllerServer) findSnapshotNode(ctx context.Context, snapID string) string {
	snapRelPath := filepath.Join("snapshots", snapID)
	for _, nodeName := range cs.hub.Registry().RegisteredNodes() {
		client, err := cs.hub.NodeClientFor(nodeName)
		if err != nil {
			continue
		}
		exists, err := client.SubvolumeExists(ctx, snapRelPath)
		client.Close()
		if err == nil && exists {
			// Re-populate the map so subsequent calls don't need to scan.
			cs.snapNodeMap[snapID] = nodeName
			klog.Infof("Found snapshot %q on node %s (recovered after restart)", snapID, nodeName)
			return nodeName
		}
	}
	return ""
}

// ---------------------------------------------------------------------------
// ValidateVolumeCapabilities
// ---------------------------------------------------------------------------

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

	// Check volume existence.
	if cs.hub != nil {
		if !cs.hub.VolumeRegistered(req.GetVolumeId()) {
			return nil, status.Errorf(codes.NotFound, "volume %q not found", req.GetVolumeId())
		}
	} else {
		volRelPath := filepath.Join("volumes", req.GetVolumeId())
		volExists, err := cs.driver.nodeOps.SubvolumeExists(ctx, volRelPath)
		if err != nil {
			return nil, status.Errorf(codes.Internal, "check volume existence: %v", err)
		}
		if !volExists {
			return nil, status.Errorf(codes.NotFound, "volume %q not found", req.GetVolumeId())
		}
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

// ---------------------------------------------------------------------------
// GetCapacity / ListVolumes / ListSnapshots
// ---------------------------------------------------------------------------

// GetCapacity returns the available capacity on the btrfs pool.
func (cs *ControllerServer) GetCapacity(
	ctx context.Context,
	req *csi.GetCapacityRequest,
) (*csi.GetCapacityResponse, error) {
	if cs.hub != nil {
		available, err := cs.hub.AggregateCapacity(ctx)
		if err != nil {
			return nil, status.Errorf(codes.Internal, "aggregate capacity: %v", err)
		}
		return &csi.GetCapacityResponse{AvailableCapacity: available}, nil
	}

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
	if cs.hub != nil {
		ids := cs.hub.RegisteredVolumeIDs()
		var entries []*csi.ListVolumesResponse_Entry
		for _, id := range ids {
			entries = append(entries, &csi.ListVolumesResponse_Entry{
				Volume: &csi.Volume{VolumeId: id},
			})
		}
		return &csi.ListVolumesResponse{Entries: entries}, nil
	}

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
	if cs.hub != nil {
		return cs.listSnapshotsHub(ctx, req)
	}
	return cs.listSnapshotsDirect(ctx, req)
}

// listSnapshotsHub lists snapshots from the in-process tracking maps.
func (cs *ControllerServer) listSnapshotsHub(
	_ context.Context,
	req *csi.ListSnapshotsRequest,
) (*csi.ListSnapshotsResponse, error) {
	cs.mu.Lock()
	defer cs.mu.Unlock()

	var entries []*csi.ListSnapshotsResponse_Entry
	for snapID, sourceVol := range cs.snapSourceMap {
		if req.GetSnapshotId() != "" && snapID != req.GetSnapshotId() {
			continue
		}
		if req.GetSourceVolumeId() != "" && sourceVol != req.GetSourceVolumeId() {
			continue
		}
		entries = append(entries, &csi.ListSnapshotsResponse_Entry{
			Snapshot: &csi.Snapshot{
				SnapshotId:     snapID,
				SourceVolumeId: sourceVol,
				CreationTime:   timestamppb.New(time.Now()),
				ReadyToUse:     true,
			},
		})
	}

	return &csi.ListSnapshotsResponse{Entries: entries}, nil
}

// listSnapshotsDirect lists snapshots via nodeOps (ModeAll).
func (cs *ControllerServer) listSnapshotsDirect(
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

// ---------------------------------------------------------------------------
// ControllerGetCapabilities
// ---------------------------------------------------------------------------

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
