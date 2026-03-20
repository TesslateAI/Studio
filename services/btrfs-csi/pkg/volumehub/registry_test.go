package volumehub

import (
	"testing"
)

func TestUnregisterNode_CleansUpVolumeCacheAndOwnership(t *testing.T) {
	r := NewNodeRegistry()

	r.RegisterNode("node-a")
	r.RegisterNode("node-b")

	r.RegisterVolume("vol-1")
	r.SetOwner("vol-1", "node-a")
	r.SetCached("vol-1", "node-a")
	r.SetCached("vol-1", "node-b")

	r.RegisterTemplate("tmpl-nextjs", "node-a")
	r.RegisterTemplate("tmpl-nextjs", "node-b")

	// Unregister node-a
	r.UnregisterNode("node-a")

	// node-a should be gone from registered nodes
	nodes := r.RegisteredNodes()
	if len(nodes) != 1 || nodes[0] != "node-b" {
		t.Errorf("RegisteredNodes = %v, want [node-b]", nodes)
	}

	// Volume ownership should be cleared
	if owner := r.GetOwner("vol-1"); owner != "" {
		t.Errorf("GetOwner(vol-1) = %q, want empty (was node-a)", owner)
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

func TestUnregisterNode_RemovesEmptyTemplateSets(t *testing.T) {
	r := NewNodeRegistry()

	r.RegisterNode("node-a")
	r.RegisterTemplate("tmpl-only-a", "node-a")

	r.UnregisterNode("node-a")

	// Template set should be fully cleaned up
	if nodes := r.GetTemplateNodes("tmpl-only-a"); len(nodes) != 0 {
		t.Errorf("GetTemplateNodes(tmpl-only-a) = %v, want empty", nodes)
	}
}

func TestUnregisterNode_Idempotent(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterNode("node-a")
	r.UnregisterNode("node-a")
	r.UnregisterNode("node-a") // should not panic
}

func TestReconcileNodes_AddsAndRemoves(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterNode("node-old")
	r.RegisterNode("node-keep")

	r.RegisterVolume("vol-on-old")
	r.SetOwner("vol-on-old", "node-old")
	r.SetCached("vol-on-old", "node-old")

	r.RegisterTemplate("tmpl", "node-old")
	r.RegisterTemplate("tmpl", "node-keep")

	added, removed := r.ReconcileNodes([]string{"node-keep", "node-new"})

	if len(removed) != 1 || removed[0] != "node-old" {
		t.Errorf("removed = %v, want [node-old]", removed)
	}
	if len(added) != 1 || added[0] != "node-new" {
		t.Errorf("added = %v, want [node-new]", added)
	}

	nodes := r.RegisteredNodes()
	if len(nodes) != 2 {
		t.Errorf("RegisteredNodes = %v, want [node-keep, node-new]", nodes)
	}

	// Volume owned by removed node should have cleared ownership
	if owner := r.GetOwner("vol-on-old"); owner != "" {
		t.Errorf("GetOwner(vol-on-old) = %q, want empty", owner)
	}

	// Template should only have node-keep
	tmplNodes := r.GetTemplateNodes("tmpl")
	if len(tmplNodes) != 1 || tmplNodes[0] != "node-keep" {
		t.Errorf("GetTemplateNodes = %v, want [node-keep]", tmplNodes)
	}
}

func TestLeastLoadedNode_SkipsRemovedNodes(t *testing.T) {
	r := NewNodeRegistry()
	r.RegisterNode("node-a")
	r.RegisterNode("node-b")

	// Put 5 volumes on node-b so node-a would be "least loaded"
	for i := 0; i < 5; i++ {
		r.SetCached("vol-"+string(rune('0'+i)), "node-b")
	}

	// node-a has 0 volumes — it would win LeastLoaded
	if best := r.LeastLoadedNode(); best != "node-a" {
		t.Fatalf("before removal: LeastLoadedNode = %q, want node-a", best)
	}

	// Remove node-a (simulates scale-down)
	r.UnregisterNode("node-a")

	// Now node-b should be the only candidate
	if best := r.LeastLoadedNode(); best != "node-b" {
		t.Errorf("after removal: LeastLoadedNode = %q, want node-b", best)
	}
}
