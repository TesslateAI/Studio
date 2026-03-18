package driver

import (
	"context"
	"os"
	"path/filepath"

	"github.com/container-storage-interface/spec/lib/go/csi"
	"golang.org/x/sys/unix"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"k8s.io/klog/v2"
	"k8s.io/mount-utils"
)

const maxVolumesPerNode = 500

// NodeServer implements the CSI Node service.
type NodeServer struct {
	csi.UnimplementedNodeServer
	driver  *Driver
	mounter mount.Interface
}

// NewNodeServer creates a new NodeServer.
func NewNodeServer(d *Driver) *NodeServer {
	return &NodeServer{
		driver:  d,
		mounter: mount.New(""),
	}
}

// NodePublishVolume bind-mounts the btrfs subvolume to the target path.
func (ns *NodeServer) NodePublishVolume(
	ctx context.Context,
	req *csi.NodePublishVolumeRequest,
) (*csi.NodePublishVolumeResponse, error) {
	if req.GetVolumeId() == "" {
		return nil, status.Error(codes.InvalidArgument, "volume ID is required")
	}
	if req.GetTargetPath() == "" {
		return nil, status.Error(codes.InvalidArgument, "target path is required")
	}

	volID := req.GetVolumeId()
	targetPath := req.GetTargetPath()
	sourcePath := filepath.Join(ns.driver.poolPath, "volumes", volID)

	// Verify the source subvolume exists. If missing, attempt cross-node
	// restore from CAS store (handles node failure recovery).
	if _, err := os.Stat(sourcePath); os.IsNotExist(err) {
		klog.Warningf("Volume %q not found locally, attempting restore from CAS", volID)
		if ns.driver.syncer != nil {
			if restoreErr := ns.driver.syncer.RestoreVolume(ctx, volID); restoreErr != nil {
				klog.Errorf("Failed to restore volume %q from CAS: %v", volID, restoreErr)
				return nil, status.Errorf(codes.NotFound, "volume %q not found locally and CAS restore failed: %v", volID, restoreErr)
			}
			klog.Infof("Volume %q restored from CAS successfully", volID)
		} else {
			return nil, status.Errorf(codes.NotFound, "volume %q not found at %s", volID, sourcePath)
		}
	} else if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to stat source path: %v", err)
	}

	// Check if already mounted (idempotent).
	notMnt, err := ns.mounter.IsLikelyNotMountPoint(targetPath)
	if err != nil {
		if os.IsNotExist(err) {
			// Target doesn't exist yet; create it.
			if mkdirErr := os.MkdirAll(targetPath, 0755); mkdirErr != nil {
				return nil, status.Errorf(codes.Internal, "failed to create target dir %s: %v", targetPath, mkdirErr)
			}
			notMnt = true
		} else {
			return nil, status.Errorf(codes.Internal, "failed to check mount point %s: %v", targetPath, err)
		}
	}

	if !notMnt {
		klog.Infof("Volume %q already mounted at %s", volID, targetPath)
		return &csi.NodePublishVolumeResponse{}, nil
	}

	// Perform bind mount.
	mountOptions := []string{"bind"}
	if req.GetReadonly() {
		mountOptions = append(mountOptions, "ro")
	}

	// Extract mount flags from the volume capability.
	if volCap := req.GetVolumeCapability(); volCap != nil {
		if mnt := volCap.GetMount(); mnt != nil {
			mountOptions = append(mountOptions, mnt.GetMountFlags()...)
		}
	}

	klog.Infof("Bind mounting volume %q: %s -> %s (options: %v)", volID, sourcePath, targetPath, mountOptions)
	if err := ns.mounter.Mount(sourcePath, targetPath, "", mountOptions); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to bind mount %s to %s: %v", sourcePath, targetPath, err)
	}

	return &csi.NodePublishVolumeResponse{}, nil
}

// NodeUnpublishVolume unmounts the volume from the target path.
func (ns *NodeServer) NodeUnpublishVolume(
	ctx context.Context,
	req *csi.NodeUnpublishVolumeRequest,
) (*csi.NodeUnpublishVolumeResponse, error) {
	if req.GetVolumeId() == "" {
		return nil, status.Error(codes.InvalidArgument, "volume ID is required")
	}
	if req.GetTargetPath() == "" {
		return nil, status.Error(codes.InvalidArgument, "target path is required")
	}

	targetPath := req.GetTargetPath()

	// Check if the target path exists at all.
	if _, err := os.Stat(targetPath); os.IsNotExist(err) {
		klog.Infof("Target path %s does not exist, nothing to unmount", targetPath)
		return &csi.NodeUnpublishVolumeResponse{}, nil
	}

	klog.Infof("Unmounting volume %q from %s", req.GetVolumeId(), targetPath)
	if err := ns.mounter.Unmount(targetPath); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to unmount %s: %v", targetPath, err)
	}

	// Remove the target directory after unmounting.
	if err := os.RemoveAll(targetPath); err != nil {
		klog.Warningf("Failed to remove target path %s: %v", targetPath, err)
		// Non-fatal: the unmount succeeded.
	}

	return &csi.NodeUnpublishVolumeResponse{}, nil
}

// NodeGetInfo returns information about the node, including topology.
func (ns *NodeServer) NodeGetInfo(
	ctx context.Context,
	req *csi.NodeGetInfoRequest,
) (*csi.NodeGetInfoResponse, error) {
	topologyKey := ns.driver.name + "/node"

	return &csi.NodeGetInfoResponse{
		NodeId:            ns.driver.nodeID,
		MaxVolumesPerNode: maxVolumesPerNode,
		AccessibleTopology: &csi.Topology{
			Segments: map[string]string{
				topologyKey: ns.driver.nodeID,
			},
		},
	}, nil
}

// NodeGetCapabilities reports node capabilities.
func (ns *NodeServer) NodeGetCapabilities(
	ctx context.Context,
	req *csi.NodeGetCapabilitiesRequest,
) (*csi.NodeGetCapabilitiesResponse, error) {
	return &csi.NodeGetCapabilitiesResponse{
		Capabilities: []*csi.NodeServiceCapability{
			{
				Type: &csi.NodeServiceCapability_Rpc{
					Rpc: &csi.NodeServiceCapability_RPC{
						Type: csi.NodeServiceCapability_RPC_GET_VOLUME_STATS,
					},
				},
			},
		},
	}, nil
}

// NodeGetVolumeStats returns usage statistics for a volume.
func (ns *NodeServer) NodeGetVolumeStats(
	ctx context.Context,
	req *csi.NodeGetVolumeStatsRequest,
) (*csi.NodeGetVolumeStatsResponse, error) {
	if req.GetVolumeId() == "" {
		return nil, status.Error(codes.InvalidArgument, "volume ID is required")
	}
	if req.GetVolumePath() == "" {
		return nil, status.Error(codes.InvalidArgument, "volume path is required")
	}

	volumePath := req.GetVolumePath()

	// Verify the path exists.
	if _, err := os.Stat(volumePath); os.IsNotExist(err) {
		return nil, status.Errorf(codes.NotFound, "volume path %s does not exist", volumePath)
	} else if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to stat volume path: %v", err)
	}

	// Get per-subvolume usage via btrfs qgroups (falls back to statfs).
	volRelPath := "volumes/" + req.GetVolumeId()
	usedBytes, err := ns.driver.btrfs.GetSubvolumeSize(ctx, volRelPath)
	if err != nil {
		klog.Warningf("Failed to get subvolume size for %s, falling back to statfs: %v", volRelPath, err)
	}

	// Get filesystem-level stats for total/available.
	var statfs unix.Statfs_t
	if err := unix.Statfs(volumePath, &statfs); err != nil {
		return nil, status.Errorf(codes.Internal, "failed to statfs %s: %v", volumePath, err)
	}

	totalBytes := int64(statfs.Blocks) * int64(statfs.Bsize)
	availableBytes := int64(statfs.Bavail) * int64(statfs.Bsize)
	if usedBytes == 0 {
		usedBytes = totalBytes - availableBytes
	}

	totalInodes := int64(statfs.Files)
	freeInodes := int64(statfs.Ffree)
	usedInodes := totalInodes - freeInodes

	return &csi.NodeGetVolumeStatsResponse{
		Usage: []*csi.VolumeUsage{
			{
				Unit:      csi.VolumeUsage_BYTES,
				Total:     totalBytes,
				Available: availableBytes,
				Used:      usedBytes,
			},
			{
				Unit:      csi.VolumeUsage_INODES,
				Total:     totalInodes,
				Available: freeInodes,
				Used:      usedInodes,
			},
		},
	}, nil
}

// NodeStageVolume is not needed for bind-mount based drivers.
func (ns *NodeServer) NodeStageVolume(
	ctx context.Context,
	req *csi.NodeStageVolumeRequest,
) (*csi.NodeStageVolumeResponse, error) {
	return nil, status.Error(codes.Unimplemented, "NodeStageVolume is not supported")
}

// NodeUnstageVolume is not needed for bind-mount based drivers.
func (ns *NodeServer) NodeUnstageVolume(
	ctx context.Context,
	req *csi.NodeUnstageVolumeRequest,
) (*csi.NodeUnstageVolumeResponse, error) {
	return nil, status.Error(codes.Unimplemented, "NodeUnstageVolume is not supported")
}
