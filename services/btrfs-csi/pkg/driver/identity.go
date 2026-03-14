package driver

import (
	"context"

	"github.com/container-storage-interface/spec/lib/go/csi"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/wrapperspb"
	"k8s.io/klog/v2"
)

// IdentityServer implements the CSI Identity service.
type IdentityServer struct {
	csi.UnimplementedIdentityServer
	driver *Driver
}

// NewIdentityServer creates a new IdentityServer.
func NewIdentityServer(d *Driver) *IdentityServer {
	return &IdentityServer{driver: d}
}

// GetPluginInfo returns metadata about the CSI plugin.
func (s *IdentityServer) GetPluginInfo(
	ctx context.Context,
	req *csi.GetPluginInfoRequest,
) (*csi.GetPluginInfoResponse, error) {
	klog.V(5).Info("GetPluginInfo called")

	if s.driver.name == "" {
		return nil, status.Error(codes.Unavailable, "driver name not configured")
	}
	if s.driver.version == "" {
		return nil, status.Error(codes.Unavailable, "driver version not configured")
	}

	return &csi.GetPluginInfoResponse{
		Name:          s.driver.name,
		VendorVersion: s.driver.version,
	}, nil
}

// GetPluginCapabilities reports what optional features this driver supports.
func (s *IdentityServer) GetPluginCapabilities(
	ctx context.Context,
	req *csi.GetPluginCapabilitiesRequest,
) (*csi.GetPluginCapabilitiesResponse, error) {
	klog.V(5).Info("GetPluginCapabilities called")

	return &csi.GetPluginCapabilitiesResponse{
		Capabilities: []*csi.PluginCapability{
			{
				Type: &csi.PluginCapability_Service_{
					Service: &csi.PluginCapability_Service{
						Type: csi.PluginCapability_Service_CONTROLLER_SERVICE,
					},
				},
			},
			{
				Type: &csi.PluginCapability_Service_{
					Service: &csi.PluginCapability_Service{
						Type: csi.PluginCapability_Service_VOLUME_ACCESSIBILITY_CONSTRAINTS,
					},
				},
			},
		},
	}, nil
}

// Probe checks if the plugin is healthy and ready to serve requests.
func (s *IdentityServer) Probe(
	ctx context.Context,
	req *csi.ProbeRequest,
) (*csi.ProbeResponse, error) {
	klog.V(5).Info("Probe called")

	return &csi.ProbeResponse{
		Ready: wrapperspb.Bool(true),
	}, nil
}
