package volumehub

import (
	"testing"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/lease"
)

func TestCleanStaleReferences_CleansOwnerAndCache(t *testing.T) {
	r := NewNodeRegistry()

	r.RegisterVolume("vol-1")
	r.SetOwner("vol-1", "node-a")
	r.SetCached("vol-1", "node-a")
	r.SetCached("vol-1", "node-b")

	r.RegisterTemplate("tmpl-nextjs", "node-a")
	r.RegisterTemplate("tmpl-nextjs", "node-b")

	// node-a dies — only node-b is live
	cleaned := r.CleanStaleReferences([]string{"node-b"})

	if cleaned != 3 { // owner cleared + cache entry removed + template entry removed
		t.Errorf("cleaned = %d, want 2", cleaned)
	}

	// Volume ownership should be cleared (was node-a)
	if owner := r.GetOwner("vol-1"); owner != "" {
		t.Errorf("GetOwner(vol-1) = %q, want empty", owner)
	}

	// Volume should still be cached on node-b but not node-a
	cached := r.GetCachedNodes("vol-1")
	if len(cached) != 1 || cached[0] != "node-b" {
		t.Errorf("GetCachedNodes(vol-1) = %v, want [node-b]", cached)
	}

	// Template should only list node-b
	tmplNodes := r.GetTemplateNodes("tmpl-nextjs")
	if len(tmplNodes) != 1 || tmplNodes[0] != "node-b" {
		t.Errorf("GetTemplateNodes = %v, want [node-b]", tmplNodes)
	}
}

func TestCleanStaleReferences_RemovesEmptyTemplateSets(t *testing.T) {
	r := NewNodeRegistry()

	r.RegisterTemplate("tmpl-only-a", "node-a")

	r.CleanStaleReferences([]string{"node-b"})

	if nodes := r.GetTemplateNodes("tmpl-only-a"); len(nodes) != 0 {
		t.Errorf("GetTemplateNodes(tmpl-only-a) = %v, want empty", nodes)
	}
}

func TestCleanStaleReferences_NoopWhenAllLive(t *testing.T) {
	r := NewNodeRegistry()

	r.RegisterVolume("vol-1")
	r.SetOwner("vol-1", "node-a")
	r.SetCached("vol-1", "node-a")
	r.SetCached("vol-1", "node-b")

	cleaned := r.CleanStaleReferences([]string{"node-a", "node-b"})

	if cleaned != 0 {
		t.Errorf("cleaned = %d, want 0", cleaned)
	}

	if owner := r.GetOwner("vol-1"); owner != "node-a" {
		t.Errorf("GetOwner = %q, want node-a", owner)
	}
}

func TestVolumeLifecycle(t *testing.T) {
	r := NewNodeRegistry()

	r.RegisterVolume("vol-1")
	r.SetOwner("vol-1", "node-a")
	r.SetCached("vol-1", "node-a")

	if owner := r.GetOwner("vol-1"); owner != "node-a" {
		t.Errorf("GetOwner = %q, want node-a", owner)
	}
	if !r.IsCached("vol-1", "node-a") {
		t.Error("IsCached(vol-1, node-a) = false, want true")
	}

	r.UnregisterVolume("vol-1")

	if owner := r.GetOwner("vol-1"); owner != "" {
		t.Errorf("after unregister: GetOwner = %q, want empty", owner)
	}
}

func TestEvictionHelpers(t *testing.T) {
	r := NewNodeRegistry()

	r.RegisterVolume("vol-1")
	r.SetCached("vol-1", "node-a")

	if !r.MarkEvicting("vol-1", "node-a") {
		t.Error("MarkEvicting should return true")
	}
	if r.MarkEvicting("vol-1", "node-a") {
		t.Error("second MarkEvicting should return false (already evicting)")
	}
	if !r.IsEvicting("vol-1", "node-a") {
		t.Error("IsEvicting should return true")
	}

	r.ClearEvicting("vol-1", "node-a")
	if r.IsEvicting("vol-1", "node-a") {
		t.Error("IsEvicting should return false after clear")
	}
}

// ---------------------------------------------------------------------------
// Volume lease tests
// ---------------------------------------------------------------------------

func TestAcquireLease_Basic(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterVolume("vol-1")

	ok, current := r.AcquireLease("vol-1", "node-a:sync:1", 5*time.Second)
	if !ok {
		t.Fatal("AcquireLease should succeed on unleased volume")
	}
	if current != "" {
		t.Errorf("currentHolder = %q, want empty on success", current)
	}
	if !r.IsLeased("vol-1") {
		t.Error("IsLeased should return true after acquire")
	}
}

func TestAcquireLease_AlreadyHeld(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterVolume("vol-1")

	r.AcquireLease("vol-1", "node-a:sync:1", 5*time.Second)

	ok, current := r.AcquireLease("vol-1", "node-b:sync:2", 5*time.Second)
	if ok {
		t.Fatal("AcquireLease should fail when lease is held by another")
	}
	if current != "node-a:sync:1" {
		t.Errorf("currentHolder = %q, want node-a:sync:1", current)
	}
}

func TestAcquireLease_SameHolderCanReacquireExpired(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterVolume("vol-1")

	// Acquire with a very short TTL.
	r.AcquireLease("vol-1", "node-a:sync:1", 1*time.Millisecond)
	time.Sleep(5 * time.Millisecond)

	// Expired — another holder can acquire.
	ok, _ := r.AcquireLease("vol-1", "node-b:sync:2", 5*time.Second)
	if !ok {
		t.Fatal("AcquireLease should succeed after lease expires")
	}
}

func TestReleaseLease_MatchesHolder(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterVolume("vol-1")
	r.AcquireLease("vol-1", "node-a:sync:1", 5*time.Second)

	// Wrong holder cannot release.
	if r.ReleaseLease("vol-1", "node-b:sync:2") {
		t.Error("ReleaseLease should fail for wrong holder")
	}
	if !r.IsLeased("vol-1") {
		t.Error("lease should still be held")
	}

	// Correct holder releases.
	if !r.ReleaseLease("vol-1", "node-a:sync:1") {
		t.Error("ReleaseLease should succeed for correct holder")
	}
	if r.IsLeased("vol-1") {
		t.Error("lease should be released")
	}
}

func TestRenewLease_ExtendsAndDetectsRevocation(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterVolume("vol-1")
	r.AcquireLease("vol-1", "node-a:sync:1", 5*time.Second)

	// Normal renewal.
	renewed, revoked := r.RenewLease("vol-1", "node-a:sync:1", 5*time.Second)
	if !renewed || revoked {
		t.Errorf("RenewLease = (renewed=%v, revoked=%v), want (true, false)", renewed, revoked)
	}

	// Wrong holder can't renew.
	renewed, _ = r.RenewLease("vol-1", "node-b:sync:2", 5*time.Second)
	if renewed {
		t.Error("RenewLease should fail for wrong holder")
	}

	// Revoke the lease.
	r.RevokeLease("vol-1")

	// Renewal returns revoked=true.
	renewed, revoked = r.RenewLease("vol-1", "node-a:sync:1", 5*time.Second)
	if renewed {
		t.Error("RenewLease should fail after revocation")
	}
	if !revoked {
		t.Error("RenewLease should indicate revocation")
	}
}

func TestRevokeLease(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterVolume("vol-1")
	r.AcquireLease("vol-1", "node-a:sync:1", 5*time.Second)

	holder := r.RevokeLease("vol-1")
	if holder != "node-a:sync:1" {
		t.Errorf("RevokeLease returned %q, want node-a:sync:1", holder)
	}

	// Revoked lease is treated as free for new acquisition.
	ok, _ := r.AcquireLease("vol-1", "node-b:delete:1", 5*time.Second)
	if !ok {
		t.Fatal("AcquireLease should succeed on revoked lease")
	}
}

func TestForceReleaseLease(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterVolume("vol-1")
	r.AcquireLease("vol-1", "node-a:sync:1", 5*time.Second)

	r.ForceReleaseLease("vol-1")

	if r.IsLeased("vol-1") {
		t.Error("lease should be force-released")
	}
}

func TestBatchAcquireLease_PartialSuccess(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterVolume("vol-1")
	r.RegisterVolume("vol-2")
	r.RegisterVolume("vol-3")

	// Pre-lease vol-2.
	r.AcquireLease("vol-2", "node-x:restore:1", 5*time.Second)

	results := r.BatchAcquireLease([]lease.BatchReq{
		{VolumeID: "vol-1", Holder: "node-a:sync:1", TTL: 5 * time.Second},
		{VolumeID: "vol-2", Holder: "node-a:sync:2", TTL: 5 * time.Second},
		{VolumeID: "vol-3", Holder: "node-a:sync:3", TTL: 5 * time.Second},
		{VolumeID: "vol-unknown", Holder: "node-a:sync:4", TTL: 5 * time.Second},
	})

	if len(results) != 4 {
		t.Fatalf("got %d results, want 4", len(results))
	}
	if !results[0].Acquired {
		t.Error("vol-1 should be acquired")
	}
	if results[1].Acquired {
		t.Error("vol-2 should NOT be acquired (already held)")
	}
	if results[1].CurrentHolder != "node-x:restore:1" {
		t.Errorf("vol-2 currentHolder = %q, want node-x:restore:1", results[1].CurrentHolder)
	}
	if !results[2].Acquired {
		t.Error("vol-3 should be acquired")
	}
	if results[3].Acquired {
		t.Error("vol-unknown should NOT be acquired (not registered)")
	}
}

func TestReapExpiredLeases(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterVolume("vol-1")
	r.RegisterVolume("vol-2")

	r.AcquireLease("vol-1", "node-a:sync:1", 1*time.Millisecond)
	r.AcquireLease("vol-2", "node-a:sync:2", 1*time.Hour)

	time.Sleep(5 * time.Millisecond)

	cleared := r.ReapExpiredLeases()
	if cleared != 1 {
		t.Errorf("ReapExpiredLeases cleared %d, want 1", cleared)
	}

	if r.IsLeased("vol-1") {
		t.Error("vol-1 lease should be reaped (expired)")
	}
	if !r.IsLeased("vol-2") {
		t.Error("vol-2 lease should still be active")
	}
}

func TestForceReleaseDeadNodeLeases(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterVolume("vol-1")
	r.RegisterVolume("vol-2")
	r.RegisterVolume("vol-3")

	r.AcquireLease("vol-1", "node-a:sync:1", 1*time.Hour)
	r.AcquireLease("vol-2", "node-b:sync:1", 1*time.Hour)
	r.AcquireLease("vol-3", "hub::delete::1", 1*time.Hour)

	// node-a is dead, node-b is alive.
	liveSet := map[string]bool{"node-b": true}
	cleared := r.ForceReleaseDeadNodeLeases(liveSet)

	if cleared != 1 {
		t.Errorf("ForceReleaseDeadNodeLeases cleared %d, want 1 (only node-a)", cleared)
	}
	if r.IsLeased("vol-1") {
		t.Error("vol-1 should be released (node-a is dead)")
	}
	if !r.IsLeased("vol-2") {
		t.Error("vol-2 should still be held (node-b is alive)")
	}
	if !r.IsLeased("vol-3") {
		t.Error("vol-3 should still be held (hub leases are never force-released)")
	}
}

func TestAcquireLease_UnregisteredVolume(t *testing.T) {
	r := NewNodeRegistry()

	ok, _ := r.AcquireLease("vol-nonexistent", "node-a:sync:1", 5*time.Second)
	if ok {
		t.Error("AcquireLease should fail for unregistered volume")
	}
}
