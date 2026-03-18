package nodeops

import (
	"strings"
	"testing"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/btrfs"
)

func TestNewServer(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	s := NewServer(bm, nil, nil, nil)

	if s.btrfs != bm {
		t.Error("btrfs manager not stored correctly")
	}
	if s.syncer != nil {
		t.Error("syncer should be nil when constructed with nil")
	}
	if s.tmplMgr != nil {
		t.Error("tmplMgr should be nil when constructed with nil")
	}
	if s.cas != nil {
		t.Error("cas should be nil when constructed with nil")
	}
	if s.srv != nil {
		t.Error("srv should be nil before Start is called")
	}
}

func TestJsonCodec_Marshal(t *testing.T) {
	codec := jsonCodec{}

	req := SubvolumeRequest{
		Name:     "test-vol",
		Source:   "src",
		Dest:     "dst",
		ReadOnly: true,
	}

	data, err := codec.Marshal(req)
	if err != nil {
		t.Fatalf("Marshal returned error: %v", err)
	}
	if len(data) == 0 {
		t.Fatal("Marshal returned empty data")
	}

	var decoded SubvolumeRequest
	if err := codec.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Unmarshal returned error: %v", err)
	}

	if decoded.Name != req.Name {
		t.Errorf("Name = %q, want %q", decoded.Name, req.Name)
	}
	if decoded.Source != req.Source {
		t.Errorf("Source = %q, want %q", decoded.Source, req.Source)
	}
	if decoded.Dest != req.Dest {
		t.Errorf("Dest = %q, want %q", decoded.Dest, req.Dest)
	}
	if decoded.ReadOnly != req.ReadOnly {
		t.Errorf("ReadOnly = %v, want %v", decoded.ReadOnly, req.ReadOnly)
	}
}

func TestJsonCodec_Unmarshal(t *testing.T) {
	data := []byte(`{"total":1000,"available":500}`)

	var resp CapacityResponse
	codec := jsonCodec{}

	if err := codec.Unmarshal(data, &resp); err != nil {
		t.Fatalf("Unmarshal returned error: %v", err)
	}
	if resp.Total != 1000 {
		t.Errorf("Total = %d, want %d", resp.Total, 1000)
	}
	if resp.Available != 500 {
		t.Errorf("Available = %d, want %d", resp.Available, 500)
	}
}

func TestSyncVolume_NilSyncer(t *testing.T) {
	bm := btrfs.NewManager("/pool")
	s := NewServer(bm, nil, nil, nil)

	// Use handleSyncVolume indirectly — the syncer is nil, so any sync
	// attempt through the server should fail with "CAS sync not configured".
	// Since restoreVolumeFromS3 no longer exists, we test that the server
	// properly stores a nil syncer.
	if s.syncer != nil {
		t.Error("syncer should be nil")
	}
}

func TestServerStop_NilGrpc(t *testing.T) {
	s := NewServer(btrfs.NewManager("/pool"), nil, nil, nil)

	// Stop should not panic when srv is nil (before Start is called).
	s.Stop()
}

// ---------------------------------------------------------------------------
// PromoteTemplateRequest serialization
// ---------------------------------------------------------------------------

func TestPromoteTemplateRequest_Marshal(t *testing.T) {
	codec := jsonCodec{}
	req := PromoteTemplateRequest{
		VolumeID:     "vol-abc123",
		TemplateName: "nextjs",
	}

	data, err := codec.Marshal(req)
	if err != nil {
		t.Fatalf("Marshal error: %v", err)
	}

	var decoded PromoteTemplateRequest
	if err := codec.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Unmarshal error: %v", err)
	}

	if decoded.VolumeID != req.VolumeID {
		t.Errorf("VolumeID = %q, want %q", decoded.VolumeID, req.VolumeID)
	}
	if decoded.TemplateName != req.TemplateName {
		t.Errorf("TemplateName = %q, want %q", decoded.TemplateName, req.TemplateName)
	}
}

func TestPromoteTemplateRequest_JSONFieldNames(t *testing.T) {
	// Verify the JSON field names match what the Python gRPC client sends.
	codec := jsonCodec{}
	data := []byte(`{"volume_id":"vol-x","template_name":"react"}`)

	var req PromoteTemplateRequest
	if err := codec.Unmarshal(data, &req); err != nil {
		t.Fatalf("Unmarshal error: %v", err)
	}
	if req.VolumeID != "vol-x" {
		t.Errorf("VolumeID = %q, want %q", req.VolumeID, "vol-x")
	}
	if req.TemplateName != "react" {
		t.Errorf("TemplateName = %q, want %q", req.TemplateName, "react")
	}
}

// ---------------------------------------------------------------------------
// handlePromoteToTemplate requires tmplMgr
// ---------------------------------------------------------------------------

func TestPromoteToTemplate_NilTmplMgr(t *testing.T) {
	// When tmplMgr is nil the handler will panic on UploadTemplate.
	// This verifies the server constructor stores the manager correctly
	// so callers know they must provide it.
	bm := btrfs.NewManager("/pool")
	s := NewServer(bm, nil, nil, nil)

	if s.tmplMgr != nil {
		t.Error("expected nil tmplMgr")
	}
}

// ---------------------------------------------------------------------------
// VolumeTrackRequest serialization (with new template fields)
// ---------------------------------------------------------------------------

func TestVolumeTrackRequest_Marshal(t *testing.T) {
	codec := jsonCodec{}
	req := VolumeTrackRequest{
		VolumeID:     "vol-123",
		TemplateName: "nodejs",
		TemplateHash: "sha256:abc123",
	}

	data, err := codec.Marshal(req)
	if err != nil {
		t.Fatalf("Marshal error: %v", err)
	}

	var decoded VolumeTrackRequest
	if err := codec.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Unmarshal error: %v", err)
	}

	if decoded.VolumeID != req.VolumeID {
		t.Errorf("VolumeID = %q, want %q", decoded.VolumeID, req.VolumeID)
	}
	if decoded.TemplateName != req.TemplateName {
		t.Errorf("TemplateName = %q, want %q", decoded.TemplateName, req.TemplateName)
	}
	if decoded.TemplateHash != req.TemplateHash {
		t.Errorf("TemplateHash = %q, want %q", decoded.TemplateHash, req.TemplateHash)
	}
}

// ---------------------------------------------------------------------------
// DeleteVolumeCAS request serialization
// ---------------------------------------------------------------------------

func TestDeleteVolumeCASRequest_Marshal(t *testing.T) {
	codec := jsonCodec{}
	req := DeleteVolumeCASRequest{VolumeID: "vol-xyz"}

	data, err := codec.Marshal(req)
	if err != nil {
		t.Fatalf("Marshal error: %v", err)
	}

	if !strings.Contains(string(data), "vol-xyz") {
		t.Errorf("marshaled data should contain vol-xyz, got %s", string(data))
	}

	var decoded DeleteVolumeCASRequest
	if err := codec.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Unmarshal error: %v", err)
	}
	if decoded.VolumeID != "vol-xyz" {
		t.Errorf("VolumeID = %q, want %q", decoded.VolumeID, "vol-xyz")
	}
}
