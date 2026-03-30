package volumehub

import (
	"fmt"
	"runtime"
	"slices"
	"sort"
	"sync"
	"time"

	"k8s.io/klog/v2"
)

// callerInfo returns a short caller location for deprecation warnings.
func callerInfo() string {
	_, file, line, ok := runtime.Caller(2)
	if !ok {
		return "unknown"
	}
	return fmt.Sprintf("%s:%d", file, line)
}

// NodeRegistry tracks which compute nodes have which volumes cached,
// and which node owns each volume.
// This is the Hub's view of the cluster topology.
type NodeRegistry struct {
	mu      sync.RWMutex
	volumes map[string]*volumeEntry // volumeID -> entry
	nodes   map[string]*nodeEntry   // nodeName -> entry
	// templateNodes tracks which nodes have each template cached.
	templateNodes map[string]map[string]struct{} // templateName -> set of nodeNames
}

type volumeEntry struct {
	volumeID       string
	ownerNode      string
	ownerChangedAt time.Time            // when ownership last changed (for eviction grace)
	cachedNodes    map[string]time.Time // nodeName -> cacheTime
	evicting       map[string]struct{}  // nodes currently being evicted (race prevention)
	lastSync       time.Time
	templateName   string // template used to create the volume
	templateHash   string // base blob hash
	latestHash     string // latest layer hash (from manifest)
}

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

type nodeEntry struct {
	name      string
	volumes   map[string]struct{} // set of volumeIDs cached on this node
	resources NodeResources       // resource headroom (updated by ResourceWatcher)
}

// NewNodeRegistry creates a new in-memory NodeRegistry.
func NewNodeRegistry() *NodeRegistry {
	return &NodeRegistry{
		volumes:       make(map[string]*volumeEntry),
		nodes:         make(map[string]*nodeEntry),
		templateNodes: make(map[string]map[string]struct{}),
	}
}

// RegisterVolume registers a volume in the registry. If it already exists this
// is a no-op.
func (r *NodeRegistry) RegisterVolume(volumeID string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if _, ok := r.volumes[volumeID]; ok {
		return
	}
	r.volumes[volumeID] = &volumeEntry{
		volumeID:    volumeID,
		cachedNodes: make(map[string]time.Time),
	}
}

// UnregisterVolume removes a volume and all its cache associations from the
// registry. Idempotent.
func (r *NodeRegistry) UnregisterVolume(volumeID string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	ve, ok := r.volumes[volumeID]
	if !ok {
		return
	}

	for nodeName := range ve.cachedNodes {
		if ne, exists := r.nodes[nodeName]; exists {
			delete(ne.volumes, volumeID)
		}
	}
	delete(r.volumes, volumeID)
}

// SetOwner sets the authoritative owner node for a volume.
func (r *NodeRegistry) SetOwner(volumeID, nodeName string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	ve, ok := r.volumes[volumeID]
	if !ok {
		ve = &volumeEntry{
			volumeID:    volumeID,
			cachedNodes: make(map[string]time.Time),
		}
		r.volumes[volumeID] = ve
	}
	if ve.ownerNode != nodeName {
		ve.ownerChangedAt = time.Now()
	}
	ve.ownerNode = nodeName

	if _, ok := r.nodes[nodeName]; !ok {
		r.nodes[nodeName] = &nodeEntry{
			name:    nodeName,
			volumes: make(map[string]struct{}),
		}
	}
}

// GetOwner returns the owner node for a volume, or "" if unset.
func (r *NodeRegistry) GetOwner(volumeID string) string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if ve, ok := r.volumes[volumeID]; ok {
		return ve.ownerNode
	}
	return ""
}

// SetCached marks a volume as cached on the given node. Both the volume and
// node entries are created lazily if they don't already exist.
func (r *NodeRegistry) SetCached(volumeID, nodeName string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	ve, ok := r.volumes[volumeID]
	if !ok {
		ve = &volumeEntry{
			volumeID:    volumeID,
			cachedNodes: make(map[string]time.Time),
		}
		r.volumes[volumeID] = ve
	}
	ve.cachedNodes[nodeName] = time.Now()

	ne, ok := r.nodes[nodeName]
	if !ok {
		ne = &nodeEntry{
			name:    nodeName,
			volumes: make(map[string]struct{}),
		}
		r.nodes[nodeName] = ne
	}
	ne.volumes[volumeID] = struct{}{}
}

// RemoveCached removes the cache association between a volume and a node.
// Idempotent.
func (r *NodeRegistry) RemoveCached(volumeID, nodeName string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if ve, ok := r.volumes[volumeID]; ok {
		delete(ve.cachedNodes, nodeName)
	}
	if ne, ok := r.nodes[nodeName]; ok {
		delete(ne.volumes, volumeID)
	}
}

// IsCached returns whether the given volume is cached on the given node.
func (r *NodeRegistry) IsCached(volumeID, nodeName string) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()

	ve, ok := r.volumes[volumeID]
	if !ok {
		return false
	}
	_, cached := ve.cachedNodes[nodeName]
	return cached
}

// GetCachedNodes returns a sorted list of node names that have the volume
// cached. Returns nil if the volume is not registered.
func (r *NodeRegistry) GetCachedNodes(volumeID string) []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	ve, ok := r.volumes[volumeID]
	if !ok {
		return nil
	}

	nodes := make([]string, 0, len(ve.cachedNodes))
	for name := range ve.cachedNodes {
		nodes = append(nodes, name)
	}
	sort.Strings(nodes)
	return nodes
}

// MarkSynced records the current time as the last sync time for the volume.
func (r *NodeRegistry) MarkSynced(volumeID string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if ve, ok := r.volumes[volumeID]; ok {
		ve.lastSync = time.Now()
	}
}

// SetVolumeTemplate sets the template context for a volume.
func (r *NodeRegistry) SetVolumeTemplate(volumeID, templateName, templateHash string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	ve, ok := r.volumes[volumeID]
	if !ok {
		return
	}
	ve.templateName = templateName
	ve.templateHash = templateHash
}

// SetLatestHash updates the latest layer hash for a volume.
func (r *NodeRegistry) SetLatestHash(volumeID, hash string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if ve, ok := r.volumes[volumeID]; ok {
		ve.latestHash = hash
	}
}

// GetVolumeStatus returns a snapshot of the volume's current status. Returns
// nil if the volume is not registered.
func (r *NodeRegistry) GetVolumeStatus(volumeID string) *VolumeStatus {
	r.mu.RLock()
	defer r.mu.RUnlock()

	ve, ok := r.volumes[volumeID]
	if !ok {
		return nil
	}

	nodes := make([]string, 0, len(ve.cachedNodes))
	for name := range ve.cachedNodes {
		nodes = append(nodes, name)
	}
	sort.Strings(nodes)

	vs := &VolumeStatus{
		VolumeID:     volumeID,
		OwnerNode:    ve.ownerNode,
		CachedNodes:  nodes,
		TemplateName: ve.templateName,
		TemplateHash: ve.templateHash,
		LatestHash:   ve.latestHash,
	}
	if !ve.lastSync.IsZero() {
		vs.LastSync = ve.lastSync.UTC().Format(time.RFC3339)
	}
	return vs
}

// RegisteredNodes returns a sorted list of all known node names. Useful for
// selecting a cache target when no hint is provided.
// Deprecated: RegisteredNodes returns stale data during autoscaler transitions.
// Use Server.liveNodes() for node selection. This exists only for volume
// metadata bookkeeping (ReconcileNodes). Every call is logged as a warning.
func (r *NodeRegistry) RegisteredNodes() []string {
	klog.Warningf("DEPRECATED: RegisteredNodes() called — this returns stale registry data, use liveNodes() instead (stack: %s)", callerInfo())
	r.mu.RLock()
	defer r.mu.RUnlock()

	names := make([]string, 0, len(r.nodes))
	for name := range r.nodes {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// Deprecated: LeastLoadedNode uses stale registry data. Use
// Server.rankLiveNodes() instead. Every call is logged as an error.
func (r *NodeRegistry) LeastLoadedNode() string {
	klog.Errorf("DEPRECATED: LeastLoadedNode() called — MUST NOT be used for node selection, use liveNodes() (stack: %s)", callerInfo())
	r.mu.RLock()
	defer r.mu.RUnlock()

	var best string
	bestCount := -1
	for name, ne := range r.nodes {
		count := len(ne.volumes)
		if bestCount < 0 || count < bestCount {
			best = name
			bestCount = count
		}
	}
	return best
}

// NodeVolumeCount returns the number of volumes cached on the given node.
// Returns 0 for unknown nodes.
func (r *NodeRegistry) NodeVolumeCount(nodeName string) int {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if ne, ok := r.nodes[nodeName]; ok {
		return len(ne.volumes)
	}
	return 0
}

// UpdateNodeResources stores the latest resource headroom data for a node.
func (r *NodeRegistry) UpdateNodeResources(nodeName string, res NodeResources) {
	r.mu.Lock()
	defer r.mu.Unlock()

	ne, ok := r.nodes[nodeName]
	if !ok {
		ne = &nodeEntry{
			name:    nodeName,
			volumes: make(map[string]struct{}),
		}
		r.nodes[nodeName] = ne
	}
	res.UpdatedAt = time.Now()
	ne.resources = res
}

// GetNodeResources returns the resource headroom for a node.
func (r *NodeRegistry) GetNodeResources(nodeName string) NodeResources {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if ne, ok := r.nodes[nodeName]; ok {
		return ne.resources
	}
	return NodeResources{}
}

// NodesWithHeadroom returns node names from the candidate set that have
// at least the requested CPU (millicores) and memory (bytes) headroom.
// Nodes with no resource data (not yet populated) are included to avoid
// false rejections during startup.
func (r *NodeRegistry) NodesWithHeadroom(candidates []string, cpuMillis, memBytes int64) []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	var result []string
	for _, name := range candidates {
		ne, ok := r.nodes[name]
		if !ok {
			// Unknown node — include it (conservative; don't reject what we haven't measured)
			result = append(result, name)
			continue
		}
		if ne.resources.UpdatedAt.IsZero() {
			// No resource data yet — include it
			result = append(result, name)
			continue
		}
		if ne.resources.HeadroomCPU() >= cpuMillis && ne.resources.HeadroomMem() >= memBytes {
			result = append(result, name)
		}
	}
	return result
}

// MarkEvicting marks a volume as being evicted from a node.
// Returns false if the volume is not cached on the node or already evicting.
func (r *NodeRegistry) MarkEvicting(volumeID, nodeName string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()

	ve, ok := r.volumes[volumeID]
	if !ok {
		return false
	}
	if _, cached := ve.cachedNodes[nodeName]; !cached {
		return false
	}
	if ve.evicting == nil {
		ve.evicting = make(map[string]struct{})
	}
	if _, already := ve.evicting[nodeName]; already {
		return false
	}
	ve.evicting[nodeName] = struct{}{}
	return true
}

// ClearEvicting removes the evicting flag for a volume on a node.
func (r *NodeRegistry) ClearEvicting(volumeID, nodeName string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if ve, ok := r.volumes[volumeID]; ok && ve.evicting != nil {
		delete(ve.evicting, nodeName)
	}
}

// IsEvicting returns whether a volume is being evicted from a node.
func (r *NodeRegistry) IsEvicting(volumeID, nodeName string) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if ve, ok := r.volumes[volumeID]; ok && ve.evicting != nil {
		_, evicting := ve.evicting[nodeName]
		return evicting
	}
	return false
}

// EvictableCache describes a stale cache eligible for eviction.
type EvictableCache struct {
	VolumeID string
	NodeName string
}

// FindEvictableCaches returns volumes cached on non-owner nodes where
// the ownership transfer grace period has expired and no eviction is
// in progress.
func (r *NodeRegistry) FindEvictableCaches(gracePeriod time.Duration) []EvictableCache {
	r.mu.RLock()
	defer r.mu.RUnlock()

	now := time.Now()
	var result []EvictableCache

	for volID, ve := range r.volumes {
		owner := ve.ownerNode
		if owner == "" {
			continue
		}
		// Skip if ownership hasn't changed (ownerChangedAt is zero) or
		// grace period hasn't elapsed since ownership transfer.
		if ve.ownerChangedAt.IsZero() || now.Sub(ve.ownerChangedAt) < gracePeriod {
			continue
		}
		for nodeName := range ve.cachedNodes {
			if nodeName == owner {
				continue // Don't evict from owner node
			}
			if ve.evicting != nil {
				if _, evicting := ve.evicting[nodeName]; evicting {
					continue
				}
			}
			result = append(result, EvictableCache{VolumeID: volID, NodeName: nodeName})
		}
	}
	return result
}

// RegisterNode adds a node to the registry. Idempotent.
func (r *NodeRegistry) RegisterNode(nodeName string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if _, ok := r.nodes[nodeName]; !ok {
		r.nodes[nodeName] = &nodeEntry{
			name:    nodeName,
			volumes: make(map[string]struct{}),
		}
	}
}

// UnregisterNode removes a node and cleans up all references to it:
// volume cache associations, volume ownership, and template cache entries.
func (r *NodeRegistry) UnregisterNode(nodeName string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	ne, ok := r.nodes[nodeName]
	if !ok {
		return
	}

	// Remove this node from all volume cache associations.
	for volID := range ne.volumes {
		if ve, exists := r.volumes[volID]; exists {
			delete(ve.cachedNodes, nodeName)
			// If this node was the owner, clear ownership.
			if ve.ownerNode == nodeName {
				ve.ownerNode = ""
			}
		}
	}

	// Remove this node from all template cache sets.
	for tmpl, nodes := range r.templateNodes {
		delete(nodes, nodeName)
		if len(nodes) == 0 {
			delete(r.templateNodes, tmpl)
		}
	}

	delete(r.nodes, nodeName)
}

// ReconcileNodes keeps only the given set of node names in the registry.
// Nodes not in liveNodes are unregistered; new nodes are registered.
func (r *NodeRegistry) ReconcileNodes(liveNodes []string) (added, removed []string) {
	live := make(map[string]struct{}, len(liveNodes))
	for _, n := range liveNodes {
		live[n] = struct{}{}
	}

	// Snapshot current node list directly (avoid deprecated RegisteredNodes
	// which logs warnings — this is legitimate internal bookkeeping).
	r.mu.RLock()
	current := make([]string, 0, len(r.nodes))
	for name := range r.nodes {
		current = append(current, name)
	}
	r.mu.RUnlock()
	for _, n := range current {
		if _, ok := live[n]; !ok {
			r.UnregisterNode(n)
			removed = append(removed, n)
		}
	}

	// Register any new nodes.
	for _, n := range liveNodes {
		if !slices.Contains(current, n) {
			r.RegisterNode(n)
			added = append(added, n)
		}
	}
	return added, removed
}

// RegisterTemplate records that a template is cached on a given node.
func (r *NodeRegistry) RegisterTemplate(templateName, nodeName string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	nodes, ok := r.templateNodes[templateName]
	if !ok {
		nodes = make(map[string]struct{})
		r.templateNodes[templateName] = nodes
	}
	nodes[nodeName] = struct{}{}
}

// AllVolumeIDs returns a sorted list of all registered volume IDs.
func (r *NodeRegistry) AllVolumeIDs() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	ids := make([]string, 0, len(r.volumes))
	for id := range r.volumes {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

// GetTemplateNodes returns a sorted list of nodes that have the template cached.
func (r *NodeRegistry) GetTemplateNodes(templateName string) []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	nodes, ok := r.templateNodes[templateName]
	if !ok {
		return nil
	}

	result := make([]string, 0, len(nodes))
	for name := range nodes {
		result = append(result, name)
	}
	sort.Strings(result)
	return result
}
