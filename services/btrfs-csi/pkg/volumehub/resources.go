package volumehub

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

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

// ResourceWatcher periodically queries the K8s API for node allocatable
// resources and pod resource requests, maintaining a standalone per-node
// headroom map. No dependency on NodeRegistry — purely live K8s data.
type ResourceWatcher struct {
	mu         sync.RWMutex
	resources  map[string]NodeResources // nodeName -> headroom
	httpClient *http.Client
	apiHost    string
	token      string
	interval   time.Duration
}

// NewResourceWatcher creates a ResourceWatcher that polls every interval.
// Accepts a pre-configured HTTP client (should share the TLS transport from
// NodeResolver so cluster CA verification works).
func NewResourceWatcher(httpClient *http.Client, apiHost, token string, interval time.Duration) *ResourceWatcher {
	return &ResourceWatcher{
		resources:  make(map[string]NodeResources),
		httpClient: httpClient,
		apiHost:    apiHost,
		token:      token,
		interval:   interval,
	}
}

// Start launches the background polling loop. Blocks until ctx is cancelled.
func (w *ResourceWatcher) Start(ctx context.Context) {
	klog.Infof("ResourceWatcher: starting (interval=%v)", w.interval)

	// Initial refresh
	if err := w.refresh(ctx); err != nil {
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
			if err := w.refresh(ctx); err != nil {
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

// NodesWithHeadroom returns node names from the candidate set that have
// at least the requested CPU (millicores) and memory (bytes) headroom.
// Nodes with no resource data (not yet populated) are included to avoid
// false rejections during startup.
func (w *ResourceWatcher) NodesWithHeadroom(candidates []string, cpuMillis, memBytes int64) []string {
	w.mu.RLock()
	defer w.mu.RUnlock()

	var result []string
	for _, name := range candidates {
		res, ok := w.resources[name]
		if !ok || res.UpdatedAt.IsZero() {
			// Unknown or no data yet — include (conservative)
			result = append(result, name)
			continue
		}
		if res.HeadroomCPU() >= cpuMillis && res.HeadroomMem() >= memBytes {
			result = append(result, name)
		}
	}
	return result
}

// RankByHeadroom returns the given node names sorted by available headroom
// (most headroom first). Nodes with no resource data sort last.
// This is the replacement for ranking by volume count.
func (w *ResourceWatcher) RankByHeadroom(nodes []string) []string {
	w.mu.RLock()
	defer w.mu.RUnlock()

	type nodeRank struct {
		name       string
		cpuMillis  int64
		hasData    bool
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
		// Nodes with data sort before nodes without
		if ranks[i].hasData != ranks[j].hasData {
			return ranks[i].hasData
		}
		// More headroom first
		if ranks[i].cpuMillis != ranks[j].cpuMillis {
			return ranks[i].cpuMillis > ranks[j].cpuMillis
		}
		// Deterministic tie-break
		return ranks[i].name < ranks[j].name
	})

	out := make([]string, len(ranks))
	for i, r := range ranks {
		out[i] = r.name
	}
	return out
}

// refresh queries K8s for all nodes and non-terminated pods, computes
// per-node headroom, and stores it.
func (w *ResourceWatcher) refresh(ctx context.Context) error {
	nodes, err := w.listNodes(ctx)
	if err != nil {
		return fmt.Errorf("list nodes: %w", err)
	}

	pods, err := w.listPods(ctx)
	if err != nil {
		return fmt.Errorf("list pods: %w", err)
	}

	// Aggregate pod requests per node
	podRequests := make(map[string]*NodeResources) // nodeName -> accumulated requests
	for _, pod := range pods {
		nodeName := pod.Spec.NodeName
		if nodeName == "" {
			continue
		}

		pr, ok := podRequests[nodeName]
		if !ok {
			pr = &NodeResources{}
			podRequests[nodeName] = pr
		}

		// Regular containers: sum of requests
		var regularCPU, regularMem int64
		for _, c := range pod.Spec.Containers {
			regularCPU += parseCPUMillis(c.Resources.Requests.CPU)
			regularMem += parseMemBytes(c.Resources.Requests.Memory)
		}

		// Init containers: max of requests (run sequentially)
		var initCPU, initMem int64
		for _, c := range pod.Spec.InitContainers {
			cpu := parseCPUMillis(c.Resources.Requests.CPU)
			mem := parseMemBytes(c.Resources.Requests.Memory)
			if cpu > initCPU {
				initCPU = cpu
			}
			if mem > initMem {
				initMem = mem
			}
		}

		// K8s effective request = max(sum(regular), max(init))
		effCPU := regularCPU
		if initCPU > effCPU {
			effCPU = initCPU
		}
		effMem := regularMem
		if initMem > effMem {
			effMem = initMem
		}

		pr.RequestedCPU += effCPU
		pr.RequestedMem += effMem
	}

	// Build new resources map atomically
	newResources := make(map[string]NodeResources, len(nodes))
	for _, node := range nodes {
		name := node.Metadata.Name
		allocCPU := parseCPUMillis(node.Status.Allocatable.CPU)
		allocMem := parseMemBytes(node.Status.Allocatable.Memory)

		pr := podRequests[name]
		var reqCPU, reqMem int64
		if pr != nil {
			reqCPU = pr.RequestedCPU
			reqMem = pr.RequestedMem
		}

		newResources[name] = NodeResources{
			AllocatableCPU: allocCPU,
			AllocatableMem: allocMem,
			RequestedCPU:   reqCPU,
			RequestedMem:   reqMem,
			UpdatedAt:      time.Now(),
		}
	}

	// Atomic swap
	w.mu.Lock()
	w.resources = newResources
	w.mu.Unlock()

	klog.V(2).Infof("ResourceWatcher: updated %d nodes", len(nodes))
	return nil
}

// ---------------------------------------------------------------------------
// K8s API calls
// ---------------------------------------------------------------------------

func (w *ResourceWatcher) listNodes(ctx context.Context) ([]k8sNode, error) {
	url := fmt.Sprintf("%s/api/v1/nodes", w.apiHost)
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+w.token)
	req.Header.Set("Accept", "application/json")

	resp, err := w.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return nil, fmt.Errorf("nodes API returned %d: %s", resp.StatusCode, body)
	}

	var list k8sNodeList
	if err := json.NewDecoder(resp.Body).Decode(&list); err != nil {
		return nil, fmt.Errorf("decode nodes: %w", err)
	}
	return list.Items, nil
}

func (w *ResourceWatcher) listPods(ctx context.Context) ([]k8sPod, error) {
	// Exclude terminated pods
	url := fmt.Sprintf(
		"%s/api/v1/pods?fieldSelector=status.phase!=Succeeded,status.phase!=Failed",
		w.apiHost,
	)
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+w.token)
	req.Header.Set("Accept", "application/json")

	resp, err := w.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return nil, fmt.Errorf("pods API returned %d: %s", resp.StatusCode, body)
	}

	var list k8sPodList
	if err := json.NewDecoder(resp.Body).Decode(&list); err != nil {
		return nil, fmt.Errorf("decode pods: %w", err)
	}
	return list.Items, nil
}

// ---------------------------------------------------------------------------
// K8s API response types (minimal — only what we need)
// ---------------------------------------------------------------------------

type k8sNodeList struct {
	Items []k8sNode `json:"items"`
}

type k8sNode struct {
	Metadata k8sObjectMeta `json:"metadata"`
	Status   k8sNodeStatus `json:"status"`
}

type k8sObjectMeta struct {
	Name string `json:"name"`
}

type k8sNodeStatus struct {
	Allocatable k8sResourceList `json:"allocatable"`
}

type k8sResourceList struct {
	CPU    string `json:"cpu"`
	Memory string `json:"memory"`
}

type k8sPodList struct {
	Items []k8sPod `json:"items"`
}

type k8sPod struct {
	Spec k8sPodSpec `json:"spec"`
}

type k8sPodSpec struct {
	NodeName       string         `json:"nodeName"`
	Containers     []k8sContainer `json:"containers"`
	InitContainers []k8sContainer `json:"initContainers"`
}

type k8sContainer struct {
	Resources k8sResourceReqs `json:"resources"`
}

type k8sResourceReqs struct {
	Requests k8sResourceList `json:"requests"`
}

// ---------------------------------------------------------------------------
// Resource string parsers
// ---------------------------------------------------------------------------

// parseCPUMillis parses a K8s CPU string to millicores.
// Examples: "1" → 1000, "500m" → 500, "2.5" → 2500, "100m" → 100.
func parseCPUMillis(s string) int64 {
	s = strings.TrimSpace(s)
	if s == "" || s == "0" {
		return 0
	}
	if strings.HasSuffix(s, "m") {
		v, err := strconv.ParseFloat(s[:len(s)-1], 64)
		if err != nil {
			return 0
		}
		return int64(v)
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 0
	}
	return int64(v * 1000)
}

// parseMemBytes parses a K8s memory string to bytes.
// Examples: "512Mi" → 536870912, "2Gi" → 2147483648, "1024Ki" → 1048576.
func parseMemBytes(s string) int64 {
	s = strings.TrimSpace(s)
	if s == "" || s == "0" {
		return 0
	}

	suffixes := []struct {
		suffix string
		mult   float64
	}{
		{"Ei", math.Pow(1024, 6)},
		{"Pi", math.Pow(1024, 5)},
		{"Ti", math.Pow(1024, 4)},
		{"Gi", math.Pow(1024, 3)},
		{"Mi", math.Pow(1024, 2)},
		{"Ki", 1024},
		{"E", 1e18},
		{"P", 1e15},
		{"T", 1e12},
		{"G", 1e9},
		{"M", 1e6},
		{"k", 1e3},
	}

	for _, sf := range suffixes {
		if strings.HasSuffix(s, sf.suffix) {
			v, err := strconv.ParseFloat(s[:len(s)-len(sf.suffix)], 64)
			if err != nil {
				return 0
			}
			return int64(v * sf.mult)
		}
	}

	// Plain integer (bytes)
	v, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0
	}
	return v
}
