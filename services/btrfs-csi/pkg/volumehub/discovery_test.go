package volumehub

import (
	"context"
	"sync/atomic"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/informers"
	"k8s.io/client-go/kubernetes/fake"
	"k8s.io/utils/ptr"
)

const (
	testSvc = "test-svc"
	testNs  = "test-ns"
	testPort = 9741
)

func newResolverWithEndpoints(t *testing.T, ctx context.Context, objs ...*corev1.Endpoints) (*NodeResolver, *fake.Clientset, informers.SharedInformerFactory) {
	t.Helper()
	// fake.NewClientset takes ...runtime.Object; convert our typed slice.
	runtimeObjs := make([]runtime.Object, 0, len(objs))
	for _, o := range objs {
		runtimeObjs = append(runtimeObjs, o)
	}
	client := fake.NewClientset(runtimeObjs...)
	factory := informers.NewSharedInformerFactoryWithOptions(client, 0, informers.WithNamespace(testNs))
	r := NewNodeResolver(factory, testSvc, testNs, testPort)
	factory.Start(ctx.Done())
	if !r.WaitForCacheSync(ctx) {
		t.Fatal("cache never synced")
	}
	return r, client, factory
}

func makeEndpoints(subsets ...corev1.EndpointSubset) *corev1.Endpoints {
	return &corev1.Endpoints{
		ObjectMeta: metav1.ObjectMeta{Name: testSvc, Namespace: testNs},
		Subsets:    subsets,
	}
}

func TestResolveFromInformer(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	ep := makeEndpoints(
		corev1.EndpointSubset{
			Addresses: []corev1.EndpointAddress{
				{IP: "10.0.1.10", NodeName: ptr.To("node-a")},
				{IP: "10.0.2.20", NodeName: ptr.To("node-b")},
			},
		},
		corev1.EndpointSubset{
			Addresses: []corev1.EndpointAddress{
				{IP: "10.0.3.30", NodeName: ptr.To("node-c")},
			},
		},
	)

	r, _, _ := newResolverWithEndpoints(t, ctx, ep)
	r.StartWatch(ctx, nil)

	// Initial state is populated when the first AddFunc fires for the pre-seeded
	// object. Allow a brief window for the handler to run.
	waitFor(t, 2*time.Second, func() bool { return r.Resolve("node-a") == "10.0.1.10:9741" })

	if got := r.Resolve("node-a"); got != "10.0.1.10:9741" {
		t.Errorf("node-a = %q, want 10.0.1.10:9741", got)
	}
	if got := r.Resolve("node-b"); got != "10.0.2.20:9741" {
		t.Errorf("node-b = %q, want 10.0.2.20:9741", got)
	}
	if got := r.Resolve("node-c"); got != "10.0.3.30:9741" {
		t.Errorf("node-c = %q, want 10.0.3.30:9741", got)
	}

	names := r.NodeNames()
	if len(names) != 3 {
		t.Errorf("NodeNames len = %d, want 3", len(names))
	}
}

func TestResolveSkipsMissingFields(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	empty := ""
	ep := makeEndpoints(
		corev1.EndpointSubset{
			Addresses: []corev1.EndpointAddress{
				{IP: "10.0.1.10", NodeName: nil},           // nil NodeName
				{IP: "10.0.2.20", NodeName: &empty},        // empty NodeName
				{IP: "", NodeName: ptr.To("node-b")},       // missing IP
				{IP: "10.0.3.30", NodeName: ptr.To("node-c")}, // valid
			},
		},
	)

	r, _, _ := newResolverWithEndpoints(t, ctx, ep)
	r.StartWatch(ctx, nil)
	waitFor(t, 2*time.Second, func() bool { return r.Resolve("node-c") == "10.0.3.30:9741" })

	if got := r.Resolve("node-c"); got != "10.0.3.30:9741" {
		t.Errorf("node-c = %q", got)
	}
	if len(r.NodeNames()) != 1 {
		t.Errorf("NodeNames len = %d, want 1 (only node-c valid)", len(r.NodeNames()))
	}
}

func TestUpdateEventRefreshesMap(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	initial := makeEndpoints(corev1.EndpointSubset{
		Addresses: []corev1.EndpointAddress{
			{IP: "10.0.1.10", NodeName: ptr.To("node-a")},
		},
	})

	r, client, _ := newResolverWithEndpoints(t, ctx, initial)

	changeCount := atomic.Int32{}
	r.StartWatch(ctx, func() { changeCount.Add(1) })
	waitFor(t, 2*time.Second, func() bool { return r.Resolve("node-a") == "10.0.1.10:9741" })

	// Update the endpoints via the fake client — the informer should deliver an
	// UPDATE event that triggers a rebuild.
	updated := makeEndpoints(corev1.EndpointSubset{
		Addresses: []corev1.EndpointAddress{
			{IP: "10.0.9.99", NodeName: ptr.To("node-updated")},
		},
	})
	updated.ResourceVersion = "200"
	if _, err := client.CoreV1().Endpoints(testNs).Update(ctx, updated, metav1.UpdateOptions{}); err != nil {
		t.Fatalf("update: %v", err)
	}

	waitFor(t, 3*time.Second, func() bool { return r.Resolve("node-updated") == "10.0.9.99:9741" })

	if r.Resolve("node-updated") != "10.0.9.99:9741" {
		t.Fatalf("node-updated not resolved after update event; map=%v", r.NodeNames())
	}
	if r.Resolve("node-a") != "" {
		t.Errorf("node-a should be gone after update, got %q", r.Resolve("node-a"))
	}
	if changeCount.Load() < 2 {
		t.Errorf("changeCount = %d, want >= 2 (add + update)", changeCount.Load())
	}
}

func TestIgnoresUnrelatedService(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	// Pre-seed TWO endpoints objects in the namespace — one matching svcName,
	// one not. Only the matching one should populate the map.
	match := makeEndpoints(corev1.EndpointSubset{
		Addresses: []corev1.EndpointAddress{
			{IP: "10.0.1.10", NodeName: ptr.To("node-match")},
		},
	})
	other := &corev1.Endpoints{
		ObjectMeta: metav1.ObjectMeta{Name: "some-other-svc", Namespace: testNs},
		Subsets: []corev1.EndpointSubset{{
			Addresses: []corev1.EndpointAddress{
				{IP: "10.0.5.50", NodeName: ptr.To("node-other")},
			},
		}},
	}

	r, _, _ := newResolverWithEndpoints(t, ctx, match, other)
	r.StartWatch(ctx, nil)
	waitFor(t, 2*time.Second, func() bool { return r.Resolve("node-match") == "10.0.1.10:9741" })

	if r.Resolve("node-other") != "" {
		t.Errorf("node-other leaked into the map (svc filter broken)")
	}
	if len(r.NodeNames()) != 1 || r.NodeNames()[0] != "node-match" {
		t.Errorf("NodeNames = %v, want [node-match]", r.NodeNames())
	}
}

func TestDeleteEventClearsMap(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	initial := makeEndpoints(corev1.EndpointSubset{
		Addresses: []corev1.EndpointAddress{
			{IP: "10.0.1.10", NodeName: ptr.To("node-a")},
		},
	})

	r, client, _ := newResolverWithEndpoints(t, ctx, initial)
	r.StartWatch(ctx, nil)
	waitFor(t, 2*time.Second, func() bool { return r.Resolve("node-a") == "10.0.1.10:9741" })

	if err := client.CoreV1().Endpoints(testNs).Delete(ctx, testSvc, metav1.DeleteOptions{}); err != nil {
		t.Fatalf("delete: %v", err)
	}
	waitFor(t, 3*time.Second, func() bool { return r.Resolve("node-a") == "" })

	if len(r.NodeNames()) != 0 {
		t.Errorf("NodeNames len = %d, want 0 after delete", len(r.NodeNames()))
	}
}

func TestParseEndpointsObject(t *testing.T) {
	ep := &corev1.Endpoints{
		Subsets: []corev1.EndpointSubset{
			{
				Addresses: []corev1.EndpointAddress{
					{IP: "10.0.1.10", NodeName: ptr.To("node-a")},
				},
			},
		},
	}
	m := parseEndpointsObject(ep, 9741)
	if m["node-a"] != "10.0.1.10:9741" {
		t.Errorf("parseEndpointsObject[node-a] = %q", m["node-a"])
	}
	if len(m) != 1 {
		t.Errorf("map size = %d, want 1", len(m))
	}
}

func TestLogChanges(t *testing.T) {
	r := &NodeResolver{}
	// Verify no panic on various inputs.
	r.logChanges(nil, map[string]string{"a": "1"})
	r.logChanges(map[string]string{"a": "1"}, nil)
	r.logChanges(map[string]string{"a": "1"}, map[string]string{"a": "2"})
	r.logChanges(map[string]string{"a": "1"}, map[string]string{"a": "1", "b": "2"})
}

// waitFor polls until cond returns true or the deadline expires.
func waitFor(t *testing.T, d time.Duration, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("condition never became true within %v", d)
}
