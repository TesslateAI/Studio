package nodeops

import (
	"testing"
)

func TestNewClient_CreatesConnection(t *testing.T) {
	c, err := NewClient("localhost:9999", nil)
	if err != nil {
		t.Fatalf("NewClient returned error: %v", err)
	}
	if c == nil {
		t.Fatal("client should not be nil")
	}
	if c.conn == nil {
		t.Fatal("conn should not be nil")
	}
	if err := c.Close(); err != nil {
		t.Errorf("Close returned error: %v", err)
	}
}

func TestClientJsonCodec(t *testing.T) {
	codec := jsonCodec{}

	if codec.Name() != "json" {
		t.Errorf("Name() = %q, want %q", codec.Name(), "json")
	}

	req := VolumeTrackRequest{VolumeID: "vol-123"}
	data, err := codec.Marshal(req)
	if err != nil {
		t.Fatalf("Marshal error: %v", err)
	}

	var decoded VolumeTrackRequest
	if err := codec.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Unmarshal error: %v", err)
	}
	if decoded.VolumeID != "vol-123" {
		t.Errorf("VolumeID = %q, want %q", decoded.VolumeID, "vol-123")
	}
}
