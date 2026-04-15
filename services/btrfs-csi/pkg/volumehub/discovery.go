package volumehub

import (
	"context"
	"fmt"
	"sync"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/client-go/informers"
	"k8s.io/client-go/tools/cache"
	"k8s.io/klog/v2"
)

// NodeResolver maintains a mapping from K8s node names to CSI node pod IPs
// by watching the headless Service's Endpoints object. The watch is backed by
// a SharedInformerFactory so authentication, TLS, token rotation, list-watch,
// bookmarks, and reconnect on 410 Gone are all handled by client-go.
type NodeResolver struct {
	mu         sync.RWMutex
	nodeToAddr map[string]string // K8s node name → podIP:port

	svcName    string                    // headless service name (filter within namespace)
	port       int                       // NodeOps gRPC port on the CSI node pods
	epInformer cache.SharedIndexInformer // endpoints informer (namespace-scoped)
	synced     cache.InformerSynced
}

// NewNodeResolver constructs a NodeResolver backed by the given factory's
// Endpoints informer. The factory is expected to be namespace-scoped to the
// service's namespace. Caller is responsible for Start() and WaitForCacheSync.
func NewNodeResolver(factory informers.SharedInformerFactory, svcName, namespace string, port int) *NodeResolver {
	_ = namespace // retained for signature symmetry / future filtering; factory is already scoped
	epInformer := factory.Core().V1().Endpoints().Informer()
	return &NodeResolver{
		nodeToAddr: make(map[string]string),
		svcName:    svcName,
		port:       port,
		epInformer: epInformer,
		synced:     epInformer.HasSynced,
	}
}

// WaitForCacheSync blocks until the underlying informer's cache is populated
// or ctx is cancelled. Returns true if the cache synced, false on cancel.
func (r *NodeResolver) WaitForCacheSync(ctx context.Context) bool {
	return cache.WaitForCacheSync(ctx.Done(), r.synced)
}

// Resolve returns the gRPC address (podIP:port) for the given K8s node name.
// Returns empty string if unknown.
func (r *NodeResolver) Resolve(nodeName string) string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.nodeToAddr[nodeName]
}

// NodeNames returns all known K8s node names.
func (r *NodeResolver) NodeNames() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	names := make([]string, 0, len(r.nodeToAddr))
	for name := range r.nodeToAddr {
		names = append(names, name)
	}
	return names
}

// StartWatch attaches event handlers to the endpoints informer. The informer
// itself is started by the factory owner; this call only registers callbacks.
// onChange runs after each map update (use for DiscoverNodes + RebuildRegistry).
func (r *NodeResolver) StartWatch(ctx context.Context, onChange func()) {
	_ = ctx // handler registration is lifecycle-bound to the informer, which stops with the factory

	rebuild := func(obj interface{}) {
		ep, ok := toEndpoints(obj)
		if !ok || ep.Name != r.svcName {
			return
		}
		newMap := parseEndpointsObject(ep, r.port)

		r.mu.Lock()
		old := r.nodeToAddr
		r.nodeToAddr = newMap
		r.mu.Unlock()

		r.logChanges(old, newMap)
		if onChange != nil {
			onChange()
		}
	}
	clear := func(obj interface{}) {
		ep, ok := toEndpoints(obj)
		if !ok || ep.Name != r.svcName {
			return
		}
		r.mu.Lock()
		old := r.nodeToAddr
		r.nodeToAddr = make(map[string]string)
		r.mu.Unlock()

		r.logChanges(old, r.nodeToAddr)
		if onChange != nil {
			onChange()
		}
	}

	r.epInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc:    rebuild,
		UpdateFunc: func(_, n interface{}) { rebuild(n) },
		DeleteFunc: clear,
	})
}

// toEndpoints extracts *corev1.Endpoints from an informer event, handling the
// tombstone wrapper that DeleteFinalStateUnknown produces on missed deletes.
func toEndpoints(obj interface{}) (*corev1.Endpoints, bool) {
	if ep, ok := obj.(*corev1.Endpoints); ok {
		return ep, true
	}
	tomb, ok := obj.(cache.DeletedFinalStateUnknown)
	if !ok {
		return nil, false
	}
	ep, ok := tomb.Obj.(*corev1.Endpoints)
	return ep, ok
}

// parseEndpointsObject builds a nodeName→podIP:port map from a typed Endpoints
// object. `addr.NodeName` is *string in corev1 — nil and empty are skipped.
func parseEndpointsObject(ep *corev1.Endpoints, port int) map[string]string {
	m := make(map[string]string)
	for _, sub := range ep.Subsets {
		for _, addr := range sub.Addresses {
			if addr.NodeName == nil || *addr.NodeName == "" || addr.IP == "" {
				continue
			}
			m[*addr.NodeName] = fmt.Sprintf("%s:%d", addr.IP, port)
		}
	}
	return m
}

// logChanges logs node IP changes at info level for observability.
func (r *NodeResolver) logChanges(old, new map[string]string) {
	for name, addr := range new {
		oldAddr, existed := old[name]
		if !existed {
			klog.Infof("NodeResolver: node %s appeared (%s)", name, addr)
		} else if oldAddr != addr {
			klog.Infof("NodeResolver: node %s IP changed (%s → %s)", name, oldAddr, addr)
		}
	}
	for name := range old {
		if _, exists := new[name]; !exists {
			klog.Infof("NodeResolver: node %s removed", name)
		}
	}
	klog.V(2).Infof("NodeResolver: %d nodes in endpoints", len(new))
}
