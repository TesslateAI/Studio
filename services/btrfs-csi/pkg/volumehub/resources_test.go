package volumehub

import (
	"context"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/informers"
	"k8s.io/client-go/kubernetes/fake"
)

func mustQty(s string) resource.Quantity {
	q, err := resource.ParseQuantity(s)
	if err != nil {
		panic(err)
	}
	return q
}

func makeNode(name, cpu, mem string) *corev1.Node {
	return &corev1.Node{
		ObjectMeta: metav1.ObjectMeta{Name: name},
		Status: corev1.NodeStatus{
			Allocatable: corev1.ResourceList{
				corev1.ResourceCPU:    mustQty(cpu),
				corev1.ResourceMemory: mustQty(mem),
			},
		},
	}
}

func makePod(name, nodeName string, phase corev1.PodPhase, containers []corev1.Container, initContainers []corev1.Container) *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: "default"},
		Spec: corev1.PodSpec{
			NodeName:       nodeName,
			Containers:     containers,
			InitContainers: initContainers,
		},
		Status: corev1.PodStatus{Phase: phase},
	}
}

func container(cpu, mem string) corev1.Container {
	return corev1.Container{
		Resources: corev1.ResourceRequirements{
			Requests: corev1.ResourceList{
				corev1.ResourceCPU:    mustQty(cpu),
				corev1.ResourceMemory: mustQty(mem),
			},
		},
	}
}

func newResourceWatcherWithObjects(t *testing.T, ctx context.Context, objs ...runtime.Object) *ResourceWatcher {
	t.Helper()
	client := fake.NewClientset(objs...)
	factory := informers.NewSharedInformerFactory(client, 0)
	w := NewResourceWatcher(factory, 100*time.Millisecond)
	factory.Start(ctx.Done())
	if !w.WaitForCacheSync(ctx) {
		t.Fatal("resource watcher cache never synced")
	}
	if err := w.refresh(); err != nil {
		t.Fatalf("initial refresh: %v", err)
	}
	return w
}

func TestRefreshComputesHeadroom(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	nodeA := makeNode("node-a", "4", "8Gi")      // 4000m CPU, 8Gi mem
	nodeB := makeNode("node-b", "2", "4Gi")      // 2000m CPU, 4Gi mem

	// On node-a: two running pods requesting 500m + 1Gi each.
	podA1 := makePod("pod-a1", "node-a", corev1.PodRunning,
		[]corev1.Container{container("500m", "1Gi")}, nil)
	podA2 := makePod("pod-a2", "node-a", corev1.PodRunning,
		[]corev1.Container{container("500m", "1Gi")}, nil)
	// On node-b: one succeeded pod (should NOT count) + one running pod.
	podB1 := makePod("pod-b1", "node-b", corev1.PodSucceeded,
		[]corev1.Container{container("500m", "1Gi")}, nil)
	podB2 := makePod("pod-b2", "node-b", corev1.PodRunning,
		[]corev1.Container{container("1", "2Gi")}, nil)

	w := newResourceWatcherWithObjects(t, ctx, nodeA, nodeB, podA1, podA2, podB1, podB2)

	resA := w.GetNodeResources("node-a")
	if resA.AllocatableCPU != 4000 {
		t.Errorf("node-a alloc CPU = %d, want 4000", resA.AllocatableCPU)
	}
	if resA.RequestedCPU != 1000 {
		t.Errorf("node-a req CPU = %d, want 1000 (500m + 500m)", resA.RequestedCPU)
	}
	if resA.HeadroomCPU() != 3000 {
		t.Errorf("node-a headroom CPU = %d, want 3000", resA.HeadroomCPU())
	}
	if resA.HeadroomMem() != 6*1024*1024*1024 {
		t.Errorf("node-a headroom mem = %d, want 6Gi", resA.HeadroomMem())
	}

	resB := w.GetNodeResources("node-b")
	if resB.RequestedCPU != 1000 {
		t.Errorf("node-b req CPU = %d, want 1000 (only running pod counted, succeeded pod skipped)", resB.RequestedCPU)
	}
	if resB.HeadroomCPU() != 1000 {
		t.Errorf("node-b headroom CPU = %d, want 1000", resB.HeadroomCPU())
	}
}

func TestRefreshInitContainerMax(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	node := makeNode("node-x", "4", "8Gi")

	// Pod with regular containers summing to 500m, and init containers of
	// 100m, 2000m, 50m → init max = 2000m. Effective CPU = max(500m, 2000m) = 2000m.
	pod := makePod("pod-init", "node-x", corev1.PodRunning,
		[]corev1.Container{container("500m", "512Mi")},
		[]corev1.Container{
			container("100m", "128Mi"),
			container("2", "1Gi"),
			container("50m", "64Mi"),
		},
	)

	w := newResourceWatcherWithObjects(t, ctx, node, pod)

	res := w.GetNodeResources("node-x")
	if res.RequestedCPU != 2000 {
		t.Errorf("RequestedCPU = %d, want 2000 (init max beats regular sum)", res.RequestedCPU)
	}
	if res.RequestedMem != 1024*1024*1024 {
		t.Errorf("RequestedMem = %d, want 1Gi (init 1Gi > regular 512Mi)", res.RequestedMem)
	}
}

func TestRefreshSkipsUnscheduledPods(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	node := makeNode("node-y", "4", "8Gi")
	// Pending pod with no NodeName — should not contribute.
	pod := makePod("pending", "", corev1.PodPending,
		[]corev1.Container{container("500m", "512Mi")}, nil)

	w := newResourceWatcherWithObjects(t, ctx, node, pod)

	res := w.GetNodeResources("node-y")
	if res.RequestedCPU != 0 {
		t.Errorf("RequestedCPU = %d, want 0 (unscheduled pod should not count)", res.RequestedCPU)
	}
}

func TestNodesWithHeadroom(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	// node-small has 1000m + 2Gi; node-big has 8000m + 16Gi.
	nodeSmall := makeNode("node-small", "1", "2Gi")
	nodeBig := makeNode("node-big", "8", "16Gi")
	w := newResourceWatcherWithObjects(t, ctx, nodeSmall, nodeBig)

	got := w.NodesWithHeadroom([]string{"node-small", "node-big"}, 2000, 4*1024*1024*1024)
	if len(got) != 1 || got[0] != "node-big" {
		t.Errorf("NodesWithHeadroom = %v, want [node-big]", got)
	}

	// Request zero — both nodes qualify.
	got = w.NodesWithHeadroom([]string{"node-small", "node-big"}, 0, 0)
	if len(got) != 2 {
		t.Errorf("NodesWithHeadroom(0,0) = %v, want both", got)
	}

	// Unknown node — included (conservative startup behavior).
	got = w.NodesWithHeadroom([]string{"unknown"}, 1000, 1024)
	if len(got) != 1 || got[0] != "unknown" {
		t.Errorf("NodesWithHeadroom(unknown) = %v, want [unknown] (conservative)", got)
	}
}

func TestRankByHeadroom(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	// node-a: 4000m headroom, node-b: 1000m headroom, node-c: no data
	nodeA := makeNode("node-a", "4", "8Gi")
	nodeB := makeNode("node-b", "1", "2Gi")
	w := newResourceWatcherWithObjects(t, ctx, nodeA, nodeB)

	got := w.RankByHeadroom([]string{"node-b", "node-a", "node-c"})
	if len(got) != 3 {
		t.Fatalf("RankByHeadroom len = %d, want 3", len(got))
	}
	if got[0] != "node-a" {
		t.Errorf("rank[0] = %q, want node-a (most headroom)", got[0])
	}
	if got[1] != "node-b" {
		t.Errorf("rank[1] = %q, want node-b", got[1])
	}
	if got[2] != "node-c" {
		t.Errorf("rank[2] = %q, want node-c (no data, sorts last)", got[2])
	}
}

func TestHeadroomNeverNegative(t *testing.T) {
	// If pods request more than allocatable, headroom clamps to 0.
	nr := NodeResources{
		AllocatableCPU: 1000, RequestedCPU: 2000,
		AllocatableMem: 1024, RequestedMem: 2048,
		UpdatedAt: time.Now(),
	}
	if nr.HeadroomCPU() != 0 {
		t.Errorf("HeadroomCPU = %d, want 0 (clamped)", nr.HeadroomCPU())
	}
	if nr.HeadroomMem() != 0 {
		t.Errorf("HeadroomMem = %d, want 0 (clamped)", nr.HeadroomMem())
	}
}
