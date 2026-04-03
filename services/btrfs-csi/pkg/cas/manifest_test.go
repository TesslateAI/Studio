package cas

import (
	"testing"
)

func TestSnapshotsSinceLastConsolidation_NoConsolidation(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "h1", Role: "sync"},
			{Hash: "h2", Role: "sync"},
			{Hash: "h3", Role: "checkpoint"},
		},
	}
	if got := m.SnapshotsSinceLastConsolidation(); got != 3 {
		t.Errorf("got %d, want 3", got)
	}
}

func TestSnapshotsSinceLastConsolidation_WithConsolidation(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "h1", Role: "sync"},
			{Hash: "h2", Role: "sync", Consolidation: true},
			{Hash: "h3", Role: "sync"},
			{Hash: "h4", Role: "checkpoint"},
		},
	}
	if got := m.SnapshotsSinceLastConsolidation(); got != 2 {
		t.Errorf("got %d, want 2 (h3, h4 after consolidation h2)", got)
	}
}

func TestSnapshotsSinceLastConsolidation_Empty(t *testing.T) {
	m := &Manifest{VolumeID: "vol-1"}
	if got := m.SnapshotsSinceLastConsolidation(); got != 0 {
		t.Errorf("got %d, want 0", got)
	}
}

func TestConsolidationHashes(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "c1", Consolidation: true},
			{Hash: "s1"},
			{Hash: "s2"},
			{Hash: "c2", Consolidation: true},
			{Hash: "s3"},
		},
	}
	got := m.ConsolidationHashes()
	if len(got) != 2 || got[0] != "c1" || got[1] != "c2" {
		t.Errorf("got %v, want [c1 c2]", got)
	}
}

func TestPruneConsolidations_BelowRetention(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "c1", Consolidation: true},
			{Hash: "s1"},
			{Hash: "c2", Consolidation: true},
		},
	}
	pruned := m.PruneConsolidations(3) // retention=3, only 2 exist
	if len(pruned) != 0 {
		t.Errorf("should not prune when below retention, got %v", pruned)
	}
	// Both should still be marked as consolidations.
	if !m.Snapshots[0].Consolidation || !m.Snapshots[2].Consolidation {
		t.Error("consolidation flags should be unchanged")
	}
}

func TestPruneConsolidations_PrunesOldest(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "c1", Consolidation: true},
			{Hash: "s1"},
			{Hash: "c2", Consolidation: true},
			{Hash: "s2"},
			{Hash: "c3", Consolidation: true},
			{Hash: "s3"},
			{Hash: "c4", Consolidation: true}, // 4 consolidations, retention=3 → prune c1
		},
	}
	pruned := m.PruneConsolidations(3)
	if len(pruned) != 1 || pruned[0] != "c1" {
		t.Errorf("should prune c1, got %v", pruned)
	}
	// c1 should no longer be marked as consolidation.
	if m.Snapshots[0].Consolidation {
		t.Error("c1 should have Consolidation=false after pruning")
	}
	// c2, c3, c4 should still be consolidations.
	if !m.Snapshots[2].Consolidation || !m.Snapshots[4].Consolidation || !m.Snapshots[6].Consolidation {
		t.Error("remaining consolidations should keep their flags")
	}
}

func TestBuildRestoreChain_NoConsolidation(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "s0"},
			{Hash: "s1"},
			{Hash: "s2"},
			{Hash: "s3"},
		},
	}
	chain := m.BuildRestoreChain(3) // restore to s3
	if len(chain) != 4 {
		t.Fatalf("chain length = %d, want 4", len(chain))
	}
	for i, idx := range chain {
		if idx != i {
			t.Errorf("chain[%d] = %d, want %d", i, idx, i)
		}
	}
}

func TestBuildRestoreChain_WithConsolidation(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "s0"},                        // 0
			{Hash: "s1"},                        // 1
			{Hash: "c1", Consolidation: true},   // 2 (consolidation)
			{Hash: "s3"},                        // 3
			{Hash: "s4"},                        // 4
		},
	}

	// Restore to s4 (idx=4): should be [c1(2), s3(3), s4(4)]
	chain := m.BuildRestoreChain(4)
	expected := []int{2, 3, 4}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, idx := range chain {
		if idx != expected[i] {
			t.Errorf("chain[%d] = %d, want %d", i, idx, expected[i])
		}
	}
}

func TestBuildRestoreChain_MultipleConsolidations(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "s0"},                        // 0
			{Hash: "c1", Consolidation: true},   // 1
			{Hash: "s2"},                        // 2
			{Hash: "c2", Consolidation: true},   // 3
			{Hash: "s4"},                        // 4
		},
	}

	// Restore to s4 (idx=4): consolidation chain [c1(1), c2(3)] + incremental [s4(4)]
	chain := m.BuildRestoreChain(4)
	expected := []int{1, 3, 4}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, idx := range chain {
		if idx != expected[i] {
			t.Errorf("chain[%d] = %d, want %d", i, idx, expected[i])
		}
	}
}

func TestBuildRestoreChain_RestoreToConsolidation(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "s0"},                        // 0
			{Hash: "c1", Consolidation: true},   // 1
			{Hash: "s2"},                        // 2
			{Hash: "c2", Consolidation: true},   // 3
		},
	}

	// Restore to c2 (idx=3): consolidation chain [c1(1), c2(3)]
	chain := m.BuildRestoreChain(3)
	expected := []int{1, 3}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, idx := range chain {
		if idx != expected[i] {
			t.Errorf("chain[%d] = %d, want %d", i, idx, expected[i])
		}
	}
}

func TestBuildRestoreChain_RestoreBeforeConsolidation(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "s0"},                        // 0
			{Hash: "s1"},                        // 1
			{Hash: "c1", Consolidation: true},   // 2
			{Hash: "s3"},                        // 3
		},
	}

	// Restore to s1 (idx=1): before any consolidation → full chain [s0(0), s1(1)]
	chain := m.BuildRestoreChain(1)
	expected := []int{0, 1}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, idx := range chain {
		if idx != expected[i] {
			t.Errorf("chain[%d] = %d, want %d", i, idx, expected[i])
		}
	}
}

func TestBuildRestoreChain_InvalidIndex(t *testing.T) {
	m := &Manifest{VolumeID: "vol-1", Snapshots: []Snapshot{{Hash: "s0"}}}
	if chain := m.BuildRestoreChain(-1); chain != nil {
		t.Errorf("negative index should return nil, got %v", chain)
	}
	if chain := m.BuildRestoreChain(5); chain != nil {
		t.Errorf("out-of-bounds index should return nil, got %v", chain)
	}
}

func TestLatestConsolidation(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "c1", Consolidation: true},
			{Hash: "s1"},
			{Hash: "c2", Consolidation: true},
			{Hash: "s2"},
		},
	}
	got := m.LatestConsolidation()
	if got == nil || got.Hash != "c2" {
		t.Errorf("got %v, want c2", got)
	}
}

func TestLatestConsolidation_None(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "s1"},
			{Hash: "s2"},
		},
	}
	if got := m.LatestConsolidation(); got != nil {
		t.Errorf("got %v, want nil", got)
	}
}

// ---------------------------------------------------------------------------
// Manifest migration tests
// ---------------------------------------------------------------------------

func TestNeedsMigration_LegacyManifest(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Base:     "sha256:tmpl",
		Snapshots: []Snapshot{
			{Hash: "s1", Parent: "sha256:tmpl", Role: "sync"},
			{Hash: "s2", Parent: "sha256:tmpl", Role: "sync"},
			{Hash: "s3", Parent: "sha256:tmpl", Role: "checkpoint"},
		},
	}
	if !m.NeedsMigration() {
		t.Error("legacy manifest (all parents=template) should need migration")
	}
}

func TestNeedsMigration_AlreadyMigrated(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Base:     "sha256:tmpl",
		Snapshots: []Snapshot{
			{Hash: "s1", Parent: "sha256:tmpl", Role: "sync"},
			{Hash: "s2", Parent: "sha256:tmpl", Role: "sync", Consolidation: true},
		},
	}
	if m.NeedsMigration() {
		t.Error("manifest with consolidation should NOT need migration")
	}
}

func TestNeedsMigration_IncrementalChain(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Base:     "sha256:tmpl",
		Snapshots: []Snapshot{
			{Hash: "s1", Parent: "sha256:tmpl", Role: "sync"},
			{Hash: "s2", Parent: "sha256:s1", Role: "sync"},
		},
	}
	if m.NeedsMigration() {
		t.Error("incremental chain should NOT need migration")
	}
}

func TestNeedsMigration_Empty(t *testing.T) {
	m := &Manifest{VolumeID: "vol-1", Base: "sha256:tmpl"}
	if m.NeedsMigration() {
		t.Error("empty manifest should NOT need migration")
	}
}

func TestNeedsMigration_TemplateLess(t *testing.T) {
	// Template-less volumes: all parents = "" (full sends).
	// These SHOULD be migrated — latest marked as consolidation.
	m := &Manifest{
		VolumeID: "vol-1",
		Snapshots: []Snapshot{
			{Hash: "s1", Parent: "", Role: "sync"},
			{Hash: "s2", Parent: "", Role: "sync"},
		},
	}
	if !m.NeedsMigration() {
		t.Error("template-less volume with all same parents should need migration")
	}
}

func TestNeedsMigration_SingleSnapshot(t *testing.T) {
	m := &Manifest{
		VolumeID:  "vol-1",
		Snapshots: []Snapshot{{Hash: "s1", Parent: "", Role: "sync"}},
	}
	if !m.NeedsMigration() {
		t.Error("single snapshot should need migration")
	}
}

func TestMigrate_MarksLatestAsConsolidation(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Base:     "sha256:tmpl",
		Snapshots: []Snapshot{
			{Hash: "s1", Parent: "sha256:tmpl", Role: "sync"},
			{Hash: "s2", Parent: "sha256:tmpl", Role: "sync"},
			{Hash: "s3", Parent: "sha256:tmpl", Role: "checkpoint"},
		},
	}
	if !m.Migrate() {
		t.Fatal("Migrate should return true for legacy manifest")
	}
	if !m.Snapshots[2].Consolidation {
		t.Error("latest snapshot should be marked as consolidation")
	}
	if m.Snapshots[0].Consolidation || m.Snapshots[1].Consolidation {
		t.Error("only the latest snapshot should be consolidation")
	}
}

func TestMigrate_Idempotent(t *testing.T) {
	m := &Manifest{
		VolumeID:  "vol-1",
		Base:      "sha256:tmpl",
		Snapshots: []Snapshot{{Hash: "s1", Parent: "sha256:tmpl", Consolidation: true}},
	}
	if m.Migrate() {
		t.Error("Migrate on already-migrated manifest should return false")
	}
}

func TestMigrate_RestoreChainAfterMigration(t *testing.T) {
	m := &Manifest{
		VolumeID: "vol-1",
		Base:     "sha256:tmpl",
		Snapshots: []Snapshot{
			{Hash: "s1", Parent: "sha256:tmpl", Role: "sync"},
			{Hash: "s2", Parent: "sha256:tmpl", Role: "sync"},
			{Hash: "s3", Parent: "sha256:tmpl", Role: "sync"},
			{Hash: "s4", Parent: "sha256:tmpl", Role: "sync"},
			{Hash: "s5", Parent: "sha256:tmpl", Role: "checkpoint"},
		},
	}
	// Before migration: full chain [0,1,2,3,4]
	chain := m.BuildRestoreChain(4)
	if len(chain) != 5 {
		t.Fatalf("pre-migration chain length = %d, want 5", len(chain))
	}
	m.Migrate()
	// After migration: only [4] (latest is consolidation)
	chain = m.BuildRestoreChain(4)
	if len(chain) != 1 || chain[0] != 4 {
		t.Errorf("post-migration chain = %v, want [4]", chain)
	}
}
