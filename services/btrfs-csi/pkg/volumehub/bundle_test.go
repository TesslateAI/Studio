package volumehub

import (
	"context"
	"strings"
	"testing"
)

func TestBundleTemplateName(t *testing.T) {
	got := bundleTemplateName("sha256:abc")
	want := "bundle:sha256:abc"
	if got != want {
		t.Fatalf("bundleTemplateName: got %q, want %q", got, want)
	}
}

func TestPublishBundleForVolume_InputValidation(t *testing.T) {
	// A zero-value Server is fine for input validation — CreateSnapshotForVolume
	// is never reached when required fields are missing.
	s := &Server{}
	ctx := context.Background()

	cases := []struct {
		name          string
		volumeID      string
		appID         string
		version       string
		wantErrSubstr string
	}{
		{"missing volume_id", "", "app", "1.0", "volume_id is required"},
		{"missing app_id", "vol-1", "", "1.0", "app_id and version are required"},
		{"missing version", "vol-1", "app", "", "app_id and version are required"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := s.PublishBundleForVolume(ctx, tc.volumeID, tc.appID, tc.version)
			if err == nil {
				t.Fatalf("expected error, got nil")
			}
			if !strings.Contains(err.Error(), tc.wantErrSubstr) {
				t.Fatalf("error %q does not contain %q", err.Error(), tc.wantErrSubstr)
			}
		})
	}
}

func TestCreateVolumeFromBundleOnNode_InputValidation(t *testing.T) {
	s := &Server{}
	_, _, err := s.CreateVolumeFromBundleOnNode(context.Background(), "", "")
	if err == nil {
		t.Fatalf("expected error for empty bundle_hash, got nil")
	}
	if !strings.Contains(err.Error(), "bundle_hash is required") {
		t.Fatalf("error %q missing required-field message", err.Error())
	}
}
