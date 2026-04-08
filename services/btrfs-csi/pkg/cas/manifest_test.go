package cas

import (
	"testing"
)

// makeSnaps builds a hash-indexed map and returns (map, head).
// Snapshots are linked via Parent fields already set by the caller.
func makeSnaps(snaps ...Snapshot) (map[string]Snapshot, string) {
	m := make(map[string]Snapshot, len(snaps))
	var head string
	for _, s := range snaps {
		m[s.Hash] = s
		head = s.Hash
	}
	return m, head
}

func TestSnapshotsSinceLastConsolidation_NoConsolidation(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "h1", Parent: "", Role: "sync"},
		Snapshot{Hash: "h2", Parent: "h1", Role: "sync"},
		Snapshot{Hash: "h3", Parent: "h2", Role: "checkpoint"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
	if got := m.SnapshotsSinceLastConsolidation(); got != 3 {
		t.Errorf("got %d, want 3", got)
	}
}

func TestSnapshotsSinceLastConsolidation_WithConsolidation(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "h1", Parent: "", Role: "sync"},
		Snapshot{Hash: "h2", Parent: "h1", Role: "sync", Consolidation: true},
		Snapshot{Hash: "h3", Parent: "h2", Role: "sync"},
		Snapshot{Hash: "h4", Parent: "h3", Role: "checkpoint"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
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
	snaps, head := makeSnaps(
		Snapshot{Hash: "c1", Parent: "", Consolidation: true},
		Snapshot{Hash: "s1", Parent: "c1"},
		Snapshot{Hash: "s2", Parent: "s1"},
		Snapshot{Hash: "c2", Parent: "s2", Consolidation: true},
		Snapshot{Hash: "s3", Parent: "c2"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
	got := m.ConsolidationHashes()
	if len(got) != 2 || got[0] != "c1" || got[1] != "c2" {
		t.Errorf("got %v, want [c1 c2]", got)
	}
}

func TestPruneConsolidations_BelowRetention(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "c1", Parent: "", Consolidation: true},
		Snapshot{Hash: "s1", Parent: "c1"},
		Snapshot{Hash: "c2", Parent: "s1", Consolidation: true},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
	pruned := m.PruneConsolidations(3) // retention=3, only 2 exist
	if len(pruned) != 0 {
		t.Errorf("should not prune when below retention, got %v", pruned)
	}
	// Both should still be marked as consolidations.
	if !m.Snapshots["c1"].Consolidation || !m.Snapshots["c2"].Consolidation {
		t.Error("consolidation flags should be unchanged")
	}
}

func TestPruneConsolidations_NoOp(t *testing.T) {
	// Pruning is disabled (no-op) because consolidation blobs form a chain.
	// Deleting any blob breaks all subsequent restores.
	snaps, head := makeSnaps(
		Snapshot{Hash: "c1", Parent: "", Consolidation: true},
		Snapshot{Hash: "s1", Parent: "c1"},
		Snapshot{Hash: "c2", Parent: "s1", Consolidation: true},
		Snapshot{Hash: "s2", Parent: "c2"},
		Snapshot{Hash: "c3", Parent: "s2", Consolidation: true},
		Snapshot{Hash: "s3", Parent: "c3"},
		Snapshot{Hash: "c4", Parent: "s3", Consolidation: true},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
	pruned := m.PruneConsolidations(3)
	if len(pruned) != 0 {
		t.Errorf("PruneConsolidations should be a no-op, got %v", pruned)
	}
}

func TestBuildRestoreChain_NoConsolidation(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "s0", Parent: ""},
		Snapshot{Hash: "s1", Parent: "s0"},
		Snapshot{Hash: "s2", Parent: "s1"},
		Snapshot{Hash: "s3", Parent: "s2"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
	chain := m.BuildRestoreChain("s3")
	expected := []string{"s0", "s1", "s2", "s3"}
	if len(chain) != len(expected) {
		t.Fatalf("chain length = %d, want %d", len(chain), len(expected))
	}
	for i, hash := range chain {
		if hash != expected[i] {
			t.Errorf("chain[%d] = %s, want %s", i, hash, expected[i])
		}
	}
}

func TestBuildRestoreChain_WithConsolidation(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "s0", Parent: ""},
		Snapshot{Hash: "s1", Parent: "s0"},
		Snapshot{Hash: "c1", Parent: "s1", Consolidation: true},
		Snapshot{Hash: "s3", Parent: "c1"},
		Snapshot{Hash: "s4", Parent: "s3"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}

	// Restore to s4: should be [c1, s3, s4]
	chain := m.BuildRestoreChain("s4")
	expected := []string{"c1", "s3", "s4"}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, hash := range chain {
		if hash != expected[i] {
			t.Errorf("chain[%d] = %s, want %s", i, hash, expected[i])
		}
	}
}

func TestBuildRestoreChain_MultipleConsolidations(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "s0", Parent: ""},
		Snapshot{Hash: "c1", Parent: "s0", Consolidation: true},
		Snapshot{Hash: "s2", Parent: "c1"},
		Snapshot{Hash: "c2", Parent: "c1", Consolidation: true},
		Snapshot{Hash: "s4", Parent: "c2"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}

	// Restore to s4: consolidation chain [c1, c2] + incremental [s4]
	chain := m.BuildRestoreChain("s4")
	expected := []string{"c1", "c2", "s4"}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, hash := range chain {
		if hash != expected[i] {
			t.Errorf("chain[%d] = %s, want %s", i, hash, expected[i])
		}
	}
}

func TestBuildRestoreChain_RestoreToConsolidation(t *testing.T) {
	snaps, _ := makeSnaps(
		Snapshot{Hash: "s0", Parent: ""},
		Snapshot{Hash: "c1", Parent: "s0", Consolidation: true},
		Snapshot{Hash: "s2", Parent: "c1"},
		Snapshot{Hash: "c2", Parent: "c1", Consolidation: true},
	)
	m := &Manifest{VolumeID: "vol-1", Head: "c2", Snapshots: snaps}

	// Restore to c2: consolidation chain [c1, c2]
	chain := m.BuildRestoreChain("c2")
	expected := []string{"c1", "c2"}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, hash := range chain {
		if hash != expected[i] {
			t.Errorf("chain[%d] = %s, want %s", i, hash, expected[i])
		}
	}
}

func TestBuildRestoreChain_RestoreBeforeConsolidation(t *testing.T) {
	snaps, _ := makeSnaps(
		Snapshot{Hash: "s0", Parent: ""},
		Snapshot{Hash: "s1", Parent: "s0"},
		Snapshot{Hash: "c1", Parent: "s1", Consolidation: true},
		Snapshot{Hash: "s3", Parent: "c1"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: "s3", Snapshots: snaps}

	// Restore to s1: before any consolidation → full chain [s0, s1]
	chain := m.BuildRestoreChain("s1")
	expected := []string{"s0", "s1"}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, hash := range chain {
		if hash != expected[i] {
			t.Errorf("chain[%d] = %s, want %s", i, hash, expected[i])
		}
	}
}

func TestBuildRestoreChain_InvalidHash(t *testing.T) {
	snaps, head := makeSnaps(Snapshot{Hash: "s0", Parent: ""})
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
	if chain := m.BuildRestoreChain(""); chain != nil {
		t.Errorf("empty hash should return nil, got %v", chain)
	}
	if chain := m.BuildRestoreChain("nonexistent"); chain != nil {
		t.Errorf("nonexistent hash should return nil, got %v", chain)
	}
}

func TestLatestConsolidation(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "c1", Parent: "", Consolidation: true},
		Snapshot{Hash: "s1", Parent: "c1"},
		Snapshot{Hash: "c2", Parent: "s1", Consolidation: true},
		Snapshot{Hash: "s2", Parent: "c2"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
	got := m.LatestConsolidation()
	if got == nil || got.Hash != "c2" {
		t.Errorf("got %v, want c2", got)
	}
}

func TestLatestConsolidation_None(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "s1", Parent: ""},
		Snapshot{Hash: "s2", Parent: "s1"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
	if got := m.LatestConsolidation(); got != nil {
		t.Errorf("got %v, want nil", got)
	}
}

// ---------------------------------------------------------------------------
// Manifest migration tests
// ---------------------------------------------------------------------------

func TestNeedsMigration_LegacyManifest(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "s1", Parent: "sha256:tmpl", Role: "sync"},
		Snapshot{Hash: "s2", Parent: "sha256:tmpl", Role: "sync"},
		Snapshot{Hash: "s3", Parent: "sha256:tmpl", Role: "checkpoint"},
	)
	m := &Manifest{VolumeID: "vol-1", Base: "sha256:tmpl", Head: head, Snapshots: snaps}
	if !m.NeedsMigration() {
		t.Error("legacy manifest (all parents=template) should need migration")
	}
}

func TestNeedsMigration_AlreadyMigrated(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "s1", Parent: "sha256:tmpl", Role: "sync"},
		Snapshot{Hash: "s2", Parent: "sha256:tmpl", Role: "sync", Consolidation: true},
	)
	m := &Manifest{VolumeID: "vol-1", Base: "sha256:tmpl", Head: head, Snapshots: snaps}
	if m.NeedsMigration() {
		t.Error("manifest with consolidation should NOT need migration")
	}
}

func TestNeedsMigration_IncrementalChain(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "s1", Parent: "sha256:tmpl", Role: "sync"},
		Snapshot{Hash: "s2", Parent: "s1", Role: "sync"},
	)
	m := &Manifest{VolumeID: "vol-1", Base: "sha256:tmpl", Head: head, Snapshots: snaps}
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
	snaps, head := makeSnaps(
		Snapshot{Hash: "s1", Parent: "", Role: "sync"},
		Snapshot{Hash: "s2", Parent: "", Role: "sync"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
	if !m.NeedsMigration() {
		t.Error("template-less volume with all same parents should need migration")
	}
}

func TestNeedsMigration_SingleSnapshot(t *testing.T) {
	snaps, head := makeSnaps(Snapshot{Hash: "s1", Parent: "", Role: "sync"})
	m := &Manifest{VolumeID: "vol-1", Head: head, Snapshots: snaps}
	if !m.NeedsMigration() {
		t.Error("single snapshot should need migration")
	}
}

func TestMigrate_MarksLatestAsConsolidation(t *testing.T) {
	snaps, head := makeSnaps(
		Snapshot{Hash: "s1", Parent: "sha256:tmpl", Role: "sync"},
		Snapshot{Hash: "s2", Parent: "sha256:tmpl", Role: "sync"},
		Snapshot{Hash: "s3", Parent: "sha256:tmpl", Role: "checkpoint"},
	)
	m := &Manifest{VolumeID: "vol-1", Base: "sha256:tmpl", Head: head, Snapshots: snaps}
	if !m.Migrate() {
		t.Fatal("Migrate should return true for legacy manifest")
	}
	if !m.Snapshots["s3"].Consolidation {
		t.Error("HEAD snapshot should be marked as consolidation")
	}
	if m.Snapshots["s1"].Consolidation || m.Snapshots["s2"].Consolidation {
		t.Error("only the HEAD snapshot should be consolidation")
	}
}

func TestMigrate_Idempotent(t *testing.T) {
	snaps, head := makeSnaps(Snapshot{Hash: "s1", Parent: "sha256:tmpl", Consolidation: true})
	m := &Manifest{VolumeID: "vol-1", Base: "sha256:tmpl", Head: head, Snapshots: snaps}
	if m.Migrate() {
		t.Error("Migrate on already-migrated manifest should return false")
	}
}

func TestMigrate_RestoreChainAfterMigration(t *testing.T) {
	// Legacy-style manifest: all snapshots diff from template (same parent).
	// In the DAG model, BuildRestoreChain walks parent pointers, so each
	// snapshot's chain is just [itself] since parent=Base stops the walk.
	// Migration marks HEAD as consolidation — chain is still [s5].
	snaps, head := makeSnaps(
		Snapshot{Hash: "s1", Parent: "sha256:tmpl", Role: "sync"},
		Snapshot{Hash: "s2", Parent: "sha256:tmpl", Role: "sync"},
		Snapshot{Hash: "s3", Parent: "sha256:tmpl", Role: "sync"},
		Snapshot{Hash: "s4", Parent: "sha256:tmpl", Role: "sync"},
		Snapshot{Hash: "s5", Parent: "sha256:tmpl", Role: "checkpoint"},
	)
	m := &Manifest{VolumeID: "vol-1", Base: "sha256:tmpl", Head: head, Snapshots: snaps}
	// Pre-migration: each snapshot diffs from template base → chain is [s5].
	chain := m.BuildRestoreChain("s5")
	if len(chain) != 1 {
		t.Fatalf("pre-migration chain length = %d, want 1 (each snapshot diffs from base)", len(chain))
	}
	m.Migrate()
	// After migration: s5 is marked as consolidation, chain is still [s5].
	chain = m.BuildRestoreChain("s5")
	if len(chain) != 1 || chain[0] != "s5" {
		t.Errorf("post-migration chain = %v, want [s5]", chain)
	}
	if !m.Snapshots["s5"].Consolidation {
		t.Error("HEAD should be marked as consolidation after Migrate")
	}
}

// ---------------------------------------------------------------------------
// DAG / branching tests
// ---------------------------------------------------------------------------

func TestSetHead_MovesWithoutTruncation(t *testing.T) {
	// Simulate: create a chain, then restore to an earlier point.
	// All snapshots must remain in the manifest.
	snaps, _ := makeSnaps(
		Snapshot{Hash: "s0", Parent: ""},
		Snapshot{Hash: "s1", Parent: "s0"},
		Snapshot{Hash: "s2", Parent: "s1"},
		Snapshot{Hash: "s3", Parent: "s2"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: "s3", Snapshots: snaps}

	// "Restore" to s1 — move HEAD, don't delete.
	m.SetHead("s1")

	if m.Head != "s1" {
		t.Errorf("Head = %s, want s1", m.Head)
	}
	// All 4 snapshots must still exist.
	if len(m.Snapshots) != 4 {
		t.Errorf("SnapshotCount = %d, want 4 (no truncation)", len(m.Snapshots))
	}
	// s3 must still be accessible by hash.
	if _, ok := m.Snapshots["s3"]; !ok {
		t.Error("s3 should still exist in manifest after SetHead")
	}
}

func TestDAG_ForkAfterRestore(t *testing.T) {
	// Build initial chain: s0 → s1 → s2 → s3
	snaps, _ := makeSnaps(
		Snapshot{Hash: "s0", Parent: ""},
		Snapshot{Hash: "s1", Parent: "s0"},
		Snapshot{Hash: "s2", Parent: "s1"},
		Snapshot{Hash: "s3", Parent: "s2"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: "s3", Snapshots: snaps}

	// Restore to s1 — save old HEAD as branch.
	m.SaveBranch("pre-restore", m.Head)
	m.SetHead("s1")

	// New syncs after restore fork from s1.
	m.AppendSnapshot(Snapshot{Hash: "s4", Parent: "s1", Role: "sync"})
	m.AppendSnapshot(Snapshot{Hash: "s5", Parent: "s4", Role: "sync"})

	// The DAG now looks like:
	//   s0 → s1 → s2 → s3          (branch "pre-restore")
	//           ↘ s4 → s5           (HEAD)

	if m.Head != "s5" {
		t.Errorf("Head = %s, want s5", m.Head)
	}
	if m.Branches["pre-restore"] != "s3" {
		t.Errorf("Branch pre-restore = %s, want s3", m.Branches["pre-restore"])
	}
	if len(m.Snapshots) != 6 {
		t.Errorf("SnapshotCount = %d, want 6", len(m.Snapshots))
	}

	// BuildRestoreChain from HEAD follows the new fork.
	chain := m.BuildRestoreChain("s5")
	expected := []string{"s0", "s1", "s4", "s5"}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, h := range chain {
		if h != expected[i] {
			t.Errorf("chain[%d] = %s, want %s", i, h, expected[i])
		}
	}

	// BuildRestoreChain for the old branch still works.
	oldChain := m.BuildRestoreChain("s3")
	expectedOld := []string{"s0", "s1", "s2", "s3"}
	if len(oldChain) != len(expectedOld) {
		t.Fatalf("old chain = %v, want %v", oldChain, expectedOld)
	}
	for i, h := range oldChain {
		if h != expectedOld[i] {
			t.Errorf("oldChain[%d] = %s, want %s", i, h, expectedOld[i])
		}
	}
}

func TestDAG_RestoreToBranchTip(t *testing.T) {
	// Build a forked DAG, then restore to the old branch tip.
	snaps := map[string]Snapshot{
		"s0": {Hash: "s0", Parent: ""},
		"s1": {Hash: "s1", Parent: "s0"},
		"s2": {Hash: "s2", Parent: "s1"},                        // old timeline
		"s3": {Hash: "s3", Parent: "s2", Role: "checkpoint"},    // old branch tip
		"s4": {Hash: "s4", Parent: "s1"},                        // new timeline (fork from s1)
		"s5": {Hash: "s5", Parent: "s4", Role: "checkpoint"},    // current HEAD
	}
	m := &Manifest{
		VolumeID: "vol-1",
		Head:     "s5",
		Branches: map[string]string{"old-branch": "s3"},
		Snapshots: snaps,
	}

	// Restore to s3 (the old branch tip).
	m.SaveBranch("pre-restore-2", m.Head)
	m.SetHead("s3")

	// BuildRestoreChain for s3 follows the old timeline.
	chain := m.BuildRestoreChain("s3")
	expected := []string{"s0", "s1", "s2", "s3"}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, h := range chain {
		if h != expected[i] {
			t.Errorf("chain[%d] = %s, want %s", i, h, expected[i])
		}
	}

	// Both branches still accessible.
	if m.Branches["old-branch"] != "s3" {
		t.Error("old-branch should still point to s3")
	}
	if m.Branches["pre-restore-2"] != "s5" {
		t.Error("pre-restore-2 should point to s5")
	}
	// All 6 snapshots preserved.
	if len(m.Snapshots) != 6 {
		t.Errorf("SnapshotCount = %d, want 6", len(m.Snapshots))
	}
}

func TestDAG_ListCheckpoints_FollowsHEAD(t *testing.T) {
	// Forked DAG: checkpoints on both branches.
	snaps := map[string]Snapshot{
		"s0": {Hash: "s0", Parent: "", Role: "sync"},
		"s1": {Hash: "s1", Parent: "s0", Role: "checkpoint"},
		"s2": {Hash: "s2", Parent: "s1", Role: "checkpoint"},    // old branch
		"s3": {Hash: "s3", Parent: "s1", Role: "sync"},          // new branch
		"s4": {Hash: "s4", Parent: "s3", Role: "checkpoint"},    // new branch checkpoint
	}
	m := &Manifest{VolumeID: "vol-1", Head: "s4", Snapshots: snaps}

	// ListCheckpoints from HEAD=s4 should follow: s4 → s3 → s1 → s0
	// Checkpoints on this path: s4, s1
	cps := m.ListCheckpoints()
	if len(cps) != 2 {
		t.Fatalf("got %d checkpoints, want 2", len(cps))
	}
	if cps[0].Hash != "s4" {
		t.Errorf("checkpoints[0] = %s, want s4", cps[0].Hash)
	}
	if cps[1].Hash != "s1" {
		t.Errorf("checkpoints[1] = %s, want s1", cps[1].Hash)
	}

	// Switch HEAD to old branch — checkpoints change.
	m.SetHead("s2")
	cps = m.ListCheckpoints()
	if len(cps) != 2 {
		t.Fatalf("got %d checkpoints, want 2", len(cps))
	}
	if cps[0].Hash != "s2" || cps[1].Hash != "s1" {
		t.Errorf("checkpoints = [%s, %s], want [s2, s1]", cps[0].Hash, cps[1].Hash)
	}
}

func TestDAG_ConsolidationOnForkedBranch(t *testing.T) {
	// Consolidation on the new branch shouldn't affect old branch.
	snaps := map[string]Snapshot{
		"s0":  {Hash: "s0", Parent: ""},
		"s1":  {Hash: "s1", Parent: "s0"},
		"s2":  {Hash: "s2", Parent: "s1"},                                    // old branch
		"s3":  {Hash: "s3", Parent: "s1"},                                    // new branch fork
		"c4":  {Hash: "c4", Parent: "s3", Consolidation: true},              // consolidation on new branch
		"s5":  {Hash: "s5", Parent: "c4"},
	}
	m := &Manifest{VolumeID: "vol-1", Head: "s5", Snapshots: snaps}

	// LatestConsolidation from HEAD: c4
	lc := m.LatestConsolidation()
	if lc == nil || lc.Hash != "c4" {
		t.Errorf("LatestConsolidation = %v, want c4", lc)
	}

	// SnapshotsSinceLastConsolidation: only s5 (after c4)
	if got := m.SnapshotsSinceLastConsolidation(); got != 1 {
		t.Errorf("SnapshotsSinceLastConsolidation = %d, want 1", got)
	}

	// BuildRestoreChain to s5: [c4, s5] (skips s3 because c4 consolidates from s3)
	chain := m.BuildRestoreChain("s5")
	expected := []string{"c4", "s5"}
	if len(chain) != len(expected) {
		t.Fatalf("chain = %v, want %v", chain, expected)
	}
	for i, h := range chain {
		if h != expected[i] {
			t.Errorf("chain[%d] = %s, want %s", i, h, expected[i])
		}
	}

	// Restore to old branch s2: chain doesn't include c4
	oldChain := m.BuildRestoreChain("s2")
	expectedOld := []string{"s0", "s1", "s2"}
	if len(oldChain) != len(expectedOld) {
		t.Fatalf("old chain = %v, want %v", oldChain, expectedOld)
	}
}

func TestDAG_LatestHash_ReturnsHead(t *testing.T) {
	m := &Manifest{VolumeID: "vol-1", Head: "abc123", Base: "base"}
	if got := m.LatestHash(); got != "abc123" {
		t.Errorf("LatestHash = %s, want abc123", got)
	}
	// With empty head, falls back to base.
	m.Head = ""
	if got := m.LatestHash(); got != "base" {
		t.Errorf("LatestHash = %s, want base", got)
	}
}

func TestDAG_SaveAndDeleteBranch(t *testing.T) {
	m := &Manifest{VolumeID: "vol-1"}
	m.SaveBranch("feature", "hash1")
	m.SaveBranch("hotfix", "hash2")

	if m.Branches["feature"] != "hash1" {
		t.Error("feature branch not saved")
	}
	if m.Branches["hotfix"] != "hash2" {
		t.Error("hotfix branch not saved")
	}

	m.DeleteBranch("feature")
	if _, ok := m.Branches["feature"]; ok {
		t.Error("feature branch should be deleted")
	}
	if m.Branches["hotfix"] != "hash2" {
		t.Error("hotfix should survive feature deletion")
	}
}

func TestDAG_TruncateAfter_IsNoOp(t *testing.T) {
	snaps, _ := makeSnaps(
		Snapshot{Hash: "s0", Parent: ""},
		Snapshot{Hash: "s1", Parent: "s0"},
		Snapshot{Hash: "s2", Parent: "s1"},
	)
	m := &Manifest{VolumeID: "vol-1", Head: "s2", Snapshots: snaps}

	// TruncateAfter should be a no-op — DAG model never truncates.
	m.TruncateAfter("s0")

	if len(m.Snapshots) != 3 {
		t.Errorf("TruncateAfter should be no-op, but SnapshotCount = %d", len(m.Snapshots))
	}
	if m.Head != "s2" {
		t.Errorf("HEAD should be unchanged, got %s", m.Head)
	}
}

func TestDAG_MultipleRestoreCycles(t *testing.T) {
	// Simulate multiple restore cycles — the scenario that broke truncation.
	m := &Manifest{
		VolumeID:  "vol-1",
		Snapshots: make(map[string]Snapshot),
	}

	// Timeline 1: s0 → s1 → s2
	m.AppendSnapshot(Snapshot{Hash: "s0", Parent: "", Role: "sync"})
	m.AppendSnapshot(Snapshot{Hash: "s1", Parent: "s0", Role: "sync"})
	m.AppendSnapshot(Snapshot{Hash: "s2", Parent: "s1", Role: "checkpoint"})

	// Restore to s0 — save branch.
	m.SaveBranch("timeline-1", m.Head) // timeline-1 → s2
	m.SetHead("s0")

	// Timeline 2: s3 → s4
	m.AppendSnapshot(Snapshot{Hash: "s3", Parent: "s0", Role: "sync"})
	m.AppendSnapshot(Snapshot{Hash: "s4", Parent: "s3", Role: "checkpoint"})

	// Restore to s2 (back to timeline 1).
	m.SaveBranch("timeline-2", m.Head) // timeline-2 → s4
	m.SetHead("s2")

	// Timeline 3: s5 → s6
	m.AppendSnapshot(Snapshot{Hash: "s5", Parent: "s2", Role: "sync"})
	m.AppendSnapshot(Snapshot{Hash: "s6", Parent: "s5", Role: "checkpoint"})

	// Verify all 7 snapshots exist.
	if len(m.Snapshots) != 7 {
		t.Fatalf("SnapshotCount = %d, want 7", len(m.Snapshots))
	}

	// HEAD chain: s6 → s5 → s2 → s1 → s0
	chain := m.BuildRestoreChain("s6")
	expected := []string{"s0", "s1", "s2", "s5", "s6"}
	if len(chain) != len(expected) {
		t.Fatalf("HEAD chain = %v, want %v", chain, expected)
	}
	for i, h := range chain {
		if h != expected[i] {
			t.Errorf("chain[%d] = %s, want %s", i, h, expected[i])
		}
	}

	// Timeline-1 chain: s2 → s1 → s0
	chain1 := m.BuildRestoreChain(m.Branches["timeline-1"])
	if len(chain1) != 3 {
		t.Fatalf("timeline-1 chain = %v, want [s0,s1,s2]", chain1)
	}

	// Timeline-2 chain: s4 → s3 → s0
	chain2 := m.BuildRestoreChain(m.Branches["timeline-2"])
	expected2 := []string{"s0", "s3", "s4"}
	if len(chain2) != len(expected2) {
		t.Fatalf("timeline-2 chain = %v, want %v", chain2, expected2)
	}
	for i, h := range chain2 {
		if h != expected2[i] {
			t.Errorf("chain2[%d] = %s, want %s", i, h, expected2[i])
		}
	}
}
