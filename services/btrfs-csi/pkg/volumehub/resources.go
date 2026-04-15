package volumehub

import (
	"context"
	"sort"
	"sync"
	"time"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/client-go/informers"
	corelisters "k8s.io/client-go/listers/core/v1"
	"k8s.io/client-go/tools/cache"
	"k8s.io/klog/v2"
)

// NodeResources holds the resource headroom for a K8s node.
type NodeResources struct {
	AllocatableCPU int64 // millicores
	AllocatableMem int64 // bytes
	RequestedCPU   int64 // sum of pod CPU requests on this node (millicores)
	RequestedMem   int64 // sum of pod memory requests on this node (bytes)
	UpdatedAt      time.Time
}

// HeadroomCPU returns available CPU headroom in millicores.
func (nr *NodeResources) HeadroomCPU() int64 {
	h := nr.AllocatableCPU - nr.RequestedCPU
	if h < 0 {
		return 0
	}
	return h
}

// HeadroomMem returns available memory headroom in bytes.
func (nr *NodeResources) HeadroomMem() int64 {
	h := nr.AllocatableMem - nr.RequestedMem
	if h < 0 {
		return 0
	}
	return h
}

// ResourceWatcher maintains a per-node headroom map by periodically reading
// the shared informer caches for Nodes and Pods. The factory is owned by the
// caller (driver.go); this type only attaches listers and a polling loop.
//
// A 30s cadence is preserved from the previous implementation — lister reads
// are cheap (cache lookups, no API roundtrip), but iterating all pods on every
// pod event would be wasteful since the consumer (placement decisions) reads
// at most every few seconds.
type ResourceWatcher struct {
	mu         sync.RWMutex
	resources  map[string]NodeResources
	nodeLister corelisters.NodeLister
	podLister  corelisters.PodLister
	synced     []cache.InformerSynced
	interval   time.Duration
}

// NewResourceWatcher wires listers off the given cluster-scoped factory. The
// factory must cover Nodes and Pods (cluster-wide); use
// informers.NewSharedInformerFactory(client, resync) without WithNamespace.
func NewResourceWatcher(factory informers.SharedInformerFactory, interval time.Duration) *ResourceWatcher {
	nodeInformer := factory.Core().V1().Nodes().Informer()
	podInformer := factory.Core().V1().Pods().Informer()
	return &ResourceWatcher{
		resources:  make(map[string]NodeResources),
		nodeLister: factory.Core().V1().Nodes().Lister(),
		podLister:  factory.Core().V1().Pods().Lister(),
		synced:     []cache.InformerSynced{nodeInformer.HasSynced, podInformer.HasSynced},
		interval:   interval,
	}
}

// WaitForCacheSync blocks until the node and pod caches are populated.
func (w *ResourceWatcher) WaitForCacheSync(ctx context.Context) bool {
	return cache.WaitForCacheSync(ctx.Done(), w.synced...)
}

// Start launches the background polling loop. Blocks until ctx is cancelled.
func (w *ResourceWatcher) Start(ctx context.Context) {
	klog.Infof("ResourceWatcher: starting (interval=%v)", w.interval)

	// Block until caches are populated before the first refresh — avoids
	// publishing an empty headroom map during startup.
	if !w.WaitForCacheSync(ctx) {
		klog.Infof("ResourceWatcher: cache sync aborted")
		return
	}

	if err := w.refresh(); err != nil {
		klog.Warningf("ResourceWatcher: initial refresh failed: %v", err)
	}

	ticker := time.NewTicker(w.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			klog.Infof("ResourceWatcher: stopped")
			return
		case <-ticker.C:
			if err := w.refresh(); err != nil {
				klog.Warningf("ResourceWatcher: refresh failed: %v", err)
			}
		}
	}
}

// GetNodeResources returns the resource headroom for a node.
func (w *ResourceWatcher) GetNodeResources(nodeName string) NodeResources {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.resources[nodeName]
}

// NodesWithHeadroom returns node names from the candidate set that have at
// least the requested CPU (millicores) and memory (bytes) headroom. Nodes
// with no resource data yet are included to avoid false rejections during
// startup.
func (w *ResourceWatcher) NodesWithHeadroom(candidates []string, cpuMillis, memBytes int64) []string {
	w.mu.RLock()
	defer w.mu.RUnlock()

	var result []string
	for _, name := range candidates {
		res, ok := w.resources[name]
		if !ok || res.UpdatedAt.IsZero() {
			result = append(result, name)
			continue
		}
		if res.HeadroomCPU() >= cpuMillis && res.HeadroomMem() >= memBytes {
			result = append(result, name)
		}
	}
	return result
}

// RankByHeadroom returns the given node names sorted by available CPU
// headroom (most first). Nodes with no resource data sort last.
func (w *ResourceWatcher) RankByHeadroom(nodes []string) []string {
	w.mu.RLock()
	defer w.mu.RUnlock()

	type nodeRank struct {
		name      string
		cpuMillis int64
		hasData   bool
	}
	ranks := make([]nodeRank, len(nodes))
	for i, n := range nodes {
		res, ok := w.resources[n]
		ranks[i] = nodeRank{
			name:      n,
			cpuMillis: res.HeadroomCPU(),
			hasData:   ok && !res.UpdatedAt.IsZero(),
		}
	}
	sort.Slice(ranks, func(i, j int) bool {
		if ranks[i].hasData != ranks[j].hasData {
			return ranks[i].hasData
		}
		if ranks[i].cpuMillis != ranks[j].cpuMillis {
			return ranks[i].cpuMillis > ranks[j].cpuMillis
		}
		return ranks[i].name < ranks[j].name
	})

	out := make([]string, len(ranks))
	for i, r := range ranks {
		out[i] = r.name
	}
	return out
}

// refresh reads all nodes and non-terminated pods from the informer cache,
// computes per-node headroom, and swaps in a new resources map.
func (w *ResourceWatcher) refresh() error {
	nodes, err := w.nodeLister.List(labels.Everything())
	if err != nil {
		return err
	}
	pods, err := w.podLister.List(labels.Everything())
	if err != nil {
		return err
	}

	// Aggregate pod requests per node.
	podRequests := make(map[string]*NodeResources)
	for _, pod := range pods {
		if pod.Spec.NodeName == "" {
			continue
		}
		// Skip terminated pods — their resources are released.
		if pod.Status.Phase == corev1.PodSucceeded || pod.Status.Phase == corev1.PodFailed {
			continue
		}

		pr, ok := podRequests[pod.Spec.NodeName]
		if !ok {
			pr = &NodeResources{}
			podRequests[pod.Spec.NodeName] = pr
		}

		effCPU, effMem := podEffectiveRequests(pod)
		pr.RequestedCPU += effCPU
		pr.RequestedMem += effMem
	}

	newResources := make(map[string]NodeResources, len(nodes))
	for _, node := range nodes {
		name := node.Name
		cpu := node.Status.Allocatable.Cpu()
		mem := node.Status.Allocatable.Memory()

		pr := podRequests[name]
		var reqCPU, reqMem int64
		if pr != nil {
			reqCPU = pr.RequestedCPU
			reqMem = pr.RequestedMem
		}
		newResources[name] = NodeResources{
			AllocatableCPU: cpu.MilliValue(),
			AllocatableMem: mem.Value(),
			RequestedCPU:   reqCPU,
			RequestedMem:   reqMem,
			UpdatedAt:      time.Now(),
		}
	}

	w.mu.Lock()
	w.resources = newResources
	w.mu.Unlock()

	klog.V(2).Infof("ResourceWatcher: updated %d nodes", len(nodes))
	return nil
}

// podEffectiveRequests computes the K8s effective resource requests for a pod:
// effective = max(sum(regular containers), max(init containers)).
// Init containers run sequentially, so their effective request is the max of
// any single init container, not the sum.
func podEffectiveRequests(pod *corev1.Pod) (cpuMillis, memBytes int64) {
	var regCPU, regMem int64
	for i := range pod.Spec.Containers {
		c := &pod.Spec.Containers[i]
		regCPU += c.Resources.Requests.Cpu().MilliValue()
		regMem += c.Resources.Requests.Memory().Value()
	}

	var initCPU, initMem int64
	for i := range pod.Spec.InitContainers {
		c := &pod.Spec.InitContainers[i]
		if v := c.Resources.Requests.Cpu().MilliValue(); v > initCPU {
			initCPU = v
		}
		if v := c.Resources.Requests.Memory().Value(); v > initMem {
			initMem = v
		}
	}

	cpuMillis = regCPU
	if initCPU > cpuMillis {
		cpuMillis = initCPU
	}
	memBytes = regMem
	if initMem > memBytes {
		memBytes = initMem
	}
	return
}
