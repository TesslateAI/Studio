package volumehub

import (
	"sort"
	"sync"
	"time"
)

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
	volumeID     string
	ownerNode    string
	cachedNodes  map[string]time.Time // nodeName -> cacheTime
	lastSync     time.Time
	templateName string // template used to create the volume
	templateHash string // base blob hash
	latestHash   string // latest layer hash (from manifest)
}

type nodeEntry struct {
	name    string
	volumes map[string]struct{} // set of volumeIDs cached on this node
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
func (r *NodeRegistry) RegisteredNodes() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	names := make([]string, 0, len(r.nodes))
	for name := range r.nodes {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
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
