package driver

import (
	"context"
	"testing"

	"github.com/container-storage-interface/spec/lib/go/csi"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestGetPluginInfo(t *testing.T) {
	d := &Driver{
		name:    "btrfs.csi.tesslate.io",
		version: "0.1.0",
	}
	is := NewIdentityServer(d)

	resp, err := is.GetPluginInfo(context.Background(), &csi.GetPluginInfoRequest{})
	if err != nil {
		t.Fatalf("GetPluginInfo returned error: %v", err)
	}
	if resp.Name != "btrfs.csi.tesslate.io" {
		t.Errorf("Name = %q, want %q", resp.Name, "btrfs.csi.tesslate.io")
	}
	if resp.VendorVersion != "0.1.0" {
		t.Errorf("VendorVersion = %q, want %q", resp.VendorVersion, "0.1.0")
	}
}

func TestGetPluginInfo_MissingName(t *testing.T) {
	d := &Driver{
		name:    "",
		version: "0.1.0",
	}
	is := NewIdentityServer(d)

	_, err := is.GetPluginInfo(context.Background(), &csi.GetPluginInfoRequest{})
	if err == nil {
		t.Fatal("expected error when name is empty")
	}

	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("error is not a gRPC status: %v", err)
	}
	if st.Code() != codes.Unavailable {
		t.Errorf("error code = %v, want %v", st.Code(), codes.Unavailable)
	}
}

func TestGetPluginInfo_MissingVersion(t *testing.T) {
	d := &Driver{
		name:    "btrfs.csi.tesslate.io",
		version: "",
	}
	is := NewIdentityServer(d)

	_, err := is.GetPluginInfo(context.Background(), &csi.GetPluginInfoRequest{})
	if err == nil {
		t.Fatal("expected error when version is empty")
	}

	st, ok := status.FromError(err)
	if !ok {
		t.Fatalf("error is not a gRPC status: %v", err)
	}
	if st.Code() != codes.Unavailable {
		t.Errorf("error code = %v, want %v", st.Code(), codes.Unavailable)
	}
}

func TestGetPluginCapabilities(t *testing.T) {
	d := &Driver{
		name:    "btrfs.csi.tesslate.io",
		version: "0.1.0",
	}
	is := NewIdentityServer(d)

	resp, err := is.GetPluginCapabilities(context.Background(), &csi.GetPluginCapabilitiesRequest{})
	if err != nil {
		t.Fatalf("GetPluginCapabilities returned error: %v", err)
	}

	if len(resp.Capabilities) != 2 {
		t.Fatalf("got %d capabilities, want 2", len(resp.Capabilities))
	}

	expectedTypes := map[csi.PluginCapability_Service_Type]bool{
		csi.PluginCapability_Service_CONTROLLER_SERVICE:              false,
		csi.PluginCapability_Service_VOLUME_ACCESSIBILITY_CONSTRAINTS: false,
	}

	for _, cap := range resp.Capabilities {
		svc := cap.GetService()
		if svc == nil {
			t.Error("capability has nil Service type")
			continue
		}
		svcType := svc.GetType()
		if _, ok := expectedTypes[svcType]; !ok {
			t.Errorf("unexpected capability type: %v", svcType)
		} else {
			expectedTypes[svcType] = true
		}
	}

	for capType, found := range expectedTypes {
		if !found {
			t.Errorf("expected capability %v not found", capType)
		}
	}
}

func TestProbe(t *testing.T) {
	d := &Driver{
		name:    "btrfs.csi.tesslate.io",
		version: "0.1.0",
	}
	is := NewIdentityServer(d)

	resp, err := is.Probe(context.Background(), &csi.ProbeRequest{})
	if err != nil {
		t.Fatalf("Probe returned error: %v", err)
	}
	if resp.Ready == nil {
		t.Fatal("Ready is nil")
	}
	if !resp.Ready.Value {
		t.Error("Ready.Value should be true")
	}
}
