package volumehub

import (
	"testing"
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
