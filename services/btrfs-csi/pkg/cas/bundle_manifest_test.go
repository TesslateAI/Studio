package cas

import (
	"strings"
	"testing"
)

func TestAncestorsOf_LinearChainToBase(t *testing.T) {
	// base=T, chain: T → l1 → l2 → l3 (head)
	snaps, _ := makeSnaps(
		Snapshot{Hash: "l1", Parent: "T", Role: "sync"},
		Snapshot{Hash: "l2", Parent: "l1", Role: "sync"},
		Snapshot{Hash: "l3", Parent: "l2", Role: "sync"},
	)
	m := &Manifest{VolumeID: "vol-x", Base: "T", TemplateName: "nextjs-16", Snapshots: snaps, Head: "l3"}

	chain, err := m.AncestorsOf("l3")
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	got := []string{chain[0].Hash, chain[1].Hash, chain[2].Hash}
	want := []string{"l1", "l2", "l3"}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("chain[%d] = %q, want %q", i, got[i], want[i])
		}
	}
}

func TestAncestorsOf_FullSendRoot(t *testing.T) {
	// No template base; Chain[0] has empty Parent (full send).
	snaps, _ := makeSnaps(
		Snapshot{Hash: "l1", Parent: "", Role: "sync"},
		Snapshot{Hash: "l2", Parent: "l1", Role: "sync"},
	)
	m := &Manifest{VolumeID: "vol-y", Snapshots: snaps, Head: "l2"}

	chain, err := m.AncestorsOf("l2")
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(chain) != 2 || chain[0].Hash != "l1" || chain[1].Hash != "l2" {
		t.Fatalf("got chain %+v, want [l1, l2]", chain)
	}
}

func TestAncestorsOf_HeadMissing(t *testing.T) {
	snaps, _ := makeSnaps(
		Snapshot{Hash: "l1", Parent: "", Role: "sync"},
	)
	m := &Manifest{Snapshots: snaps}
	if _, err := m.AncestorsOf("ghost"); err == nil {
		t.Fatal("expected error for missing head")
	}
}

func TestAncestorsOf_CycleDetected(t *testing.T) {
	// Corrupt chain: l1 ↔ l2 cycle.
	snaps := map[string]Snapshot{
		"l1": {Hash: "l1", Parent: "l2"},
		"l2": {Hash: "l2", Parent: "l1"},
	}
	m := &Manifest{Snapshots: snaps}
	_, err := m.AncestorsOf("l1")
	if err == nil || !strings.Contains(err.Error(), "cycle") {
		t.Fatalf("expected cycle error, got %v", err)
	}
}

func TestAncestorsOf_EmptyHead(t *testing.T) {
	m := &Manifest{Snapshots: map[string]Snapshot{}}
	if _, err := m.AncestorsOf(""); err == nil {
		t.Fatal("expected error for empty head")
	}
}

func TestBundleManifestKey(t *testing.T) {
	h := "abcd1234"
	got := BundleManifestKey(h)
	want := "manifests/bundle:abcd1234.json"
	if got != want {
		t.Errorf("BundleManifestKey(%q) = %q, want %q", h, got, want)
	}
}

func TestBundleManifest_ChainConsistency(t *testing.T) {
	// PutBundleManifest rejects a manifest whose last-Chain.Hash doesn't
	// match Head. This is our only structural guard beyond the basic marshal.
	bm := BundleManifest{
		Head:  "h3",
		Chain: []Snapshot{{Hash: "h1"}, {Hash: "h2"}},
	}
	// Exercise the validation without touching S3: synthesize by calling
	// PutBundleManifest against a Store with a nil obj backend; the
	// validation path short-circuits before the upload.
	s := &Store{}
	err := s.PutBundleManifest(t.Context(), bm)
	if err == nil || !strings.Contains(err.Error(), "inconsistent") {
		t.Fatalf("expected inconsistency error, got %v", err)
	}
}
