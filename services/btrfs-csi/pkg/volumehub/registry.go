package volumehub

import (
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/lease"
)

// ---------------------------------------------------------------------------
// VolumeStore — pure volume metadata, zero node roster
// ---------------------------------------------------------------------------

// NodeRegistry tracks volume metadata: ownership, cache locations, templates,
// sync state. It has NO concept of "which nodes exist" — node liveness is
// always sourced from the live resolver. Node names appear only as strings
// referenced by volume entries.
type NodeRegistry struct {
	mu      sync.RWMutex
	volumes map[string]*volumeEntry // volumeID -> entry
	// templateNodes tracks which nodes have each template cached.
	templateNodes map[string]map[string]struct{} // templateName -> set of nodeNames
}

// volumeLease tracks an exclusive lease on a volume. All volume lifecycle
// operations (sync, restore, delete, migrate) must acquire a lease before
// proceeding. This eliminates races between the sync daemon's per-volume
// locks and the Hub's manifest locks by providing a single coordination point.
type volumeLease struct {
	holder    string    // "{nodeName}:{operation}:{nonce}" or "hub::{operation}:{nonce}"
	expiresAt time.Time // TTL-based expiry; renewed by heartbeat while operation runs
	revoked   bool      // set by delete preemption; holder checks via RenewLease
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
	lease          *volumeLease
}

// NewNodeRegistry creates a new in-memory NodeRegistry.
func NewNodeRegistry() *NodeRegistry {
	return &NodeRegistry{
		volumes:       make(map[string]*volumeEntry),
		templateNodes: make(map[string]map[string]struct{}),
	}
}

// ---------------------------------------------------------------------------
// Volume lifecycle
// ---------------------------------------------------------------------------

// RegisterVolume registers a volume in the store. If it already exists this
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

// UnregisterVolume removes a volume and all its cache associations.
// Idempotent.
func (r *NodeRegistry) UnregisterVolume(volumeID string) {
	r.mu.Lock()
	defer r.mu.Unlock()

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

// SetCached marks a volume as cached on the given node.
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
}

// RemoveCached removes the cache association between a volume and a node.
// Idempotent.
func (r *NodeRegistry) RemoveCached(volumeID, nodeName string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if ve, ok := r.volumes[volumeID]; ok {
		delete(ve.cachedNodes, nodeName)
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

// ---------------------------------------------------------------------------
// Eviction helpers
// ---------------------------------------------------------------------------

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
		if ve.ownerChangedAt.IsZero() || now.Sub(ve.ownerChangedAt) < gracePeriod {
			continue
		}
		for nodeName := range ve.cachedNodes {
			if nodeName == owner {
				continue
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

// ---------------------------------------------------------------------------
// Volume leases
// ---------------------------------------------------------------------------

// AcquireLease attempts to acquire an exclusive lease on the volume.
// Returns (true, "") on success, (false, currentHolder) if already held.
// Expired leases are treated as free.
func (r *NodeRegistry) AcquireLease(volumeID, holder string, ttl time.Duration) (ok bool, currentHolder string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	ve, exists := r.volumes[volumeID]
	if !exists {
		return false, ""
	}
	now := time.Now()

	if ve.lease != nil && now.Before(ve.lease.expiresAt) && !ve.lease.revoked {
		return false, ve.lease.holder
	}

	ve.lease = &volumeLease{
		holder:    holder,
		expiresAt: now.Add(ttl),
	}
	return true, ""
}

// ReleaseLease releases a lease only if the holder matches.
// Returns true if the lease was released.
func (r *NodeRegistry) ReleaseLease(volumeID, holder string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()

	ve, ok := r.volumes[volumeID]
	if !ok || ve.lease == nil {
		return false
	}
	if ve.lease.holder != holder {
		return false
	}
	ve.lease = nil
	return true
}

// RenewLease extends the TTL of an existing lease. Returns renewed=true on
// success, revoked=true if the lease was revoked (holder should abort).
// Returns renewed=false if the holder doesn't match or the lease expired.
func (r *NodeRegistry) RenewLease(volumeID, holder string, ttl time.Duration) (renewed bool, revoked bool) {
	r.mu.Lock()
	defer r.mu.Unlock()

	ve, ok := r.volumes[volumeID]
	if !ok || ve.lease == nil || ve.lease.holder != holder {
		return false, false
	}
	if ve.lease.revoked {
		return false, true
	}
	ve.lease.expiresAt = time.Now().Add(ttl)
	return true, false
}

// RevokeLease marks an existing lease as revoked. The holder's renewal
// goroutine will detect this and stop renewing, letting the lease expire.
// Returns the holder that was revoked, or "" if no active lease.
func (r *NodeRegistry) RevokeLease(volumeID string) string {
	r.mu.Lock()
	defer r.mu.Unlock()

	ve, ok := r.volumes[volumeID]
	if !ok || ve.lease == nil {
		return ""
	}
	if time.Now().After(ve.lease.expiresAt) {
		ve.lease = nil
		return ""
	}
	ve.lease.revoked = true
	return ve.lease.holder
}

// ForceReleaseLease unconditionally clears the lease regardless of holder.
// Used after delete preemption timeout.
func (r *NodeRegistry) ForceReleaseLease(volumeID string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if ve, ok := r.volumes[volumeID]; ok {
		ve.lease = nil
	}
}

// IsLeased returns whether the volume has an active (non-expired) lease.
func (r *NodeRegistry) IsLeased(volumeID string) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()

	ve, ok := r.volumes[volumeID]
	if !ok || ve.lease == nil {
		return false
	}
	return time.Now().Before(ve.lease.expiresAt)
}

// BatchAcquireLease atomically acquires leases for multiple volumes.
// Each request is independent — partial success is possible.
func (r *NodeRegistry) BatchAcquireLease(requests []lease.BatchReq) []lease.BatchResult {
	r.mu.Lock()
	defer r.mu.Unlock()

	now := time.Now()
	results := make([]lease.BatchResult, len(requests))

	for i, req := range requests {
		results[i].VolumeID = req.VolumeID

		ve, exists := r.volumes[req.VolumeID]
		if !exists {
			results[i].Acquired = false
			continue
		}

		if ve.lease != nil && now.Before(ve.lease.expiresAt) && !ve.lease.revoked {
			results[i].Acquired = false
			results[i].CurrentHolder = ve.lease.holder
			continue
		}

		ve.lease = &volumeLease{
			holder:    req.Holder,
			expiresAt: now.Add(req.TTL),
		}
		results[i].Acquired = true
	}

	return results
}

// ReapExpiredLeases scans all volumes and clears expired leases.
// Returns the number of leases cleared.
func (r *NodeRegistry) ReapExpiredLeases() int {
	r.mu.Lock()
	defer r.mu.Unlock()

	now := time.Now()
	cleared := 0
	for _, ve := range r.volumes {
		if ve.lease != nil && now.After(ve.lease.expiresAt) {
			ve.lease = nil
			cleared++
		}
	}
	return cleared
}

// ForceReleaseDeadNodeLeases clears all leases held by nodes not in the
// live set. The holder format is "{nodeName}:{operation}:{nonce}" — the
// node name is extracted from the first segment. Hub-held leases
// (holder starts with "hub::") are never force-released by this method.
func (r *NodeRegistry) ForceReleaseDeadNodeLeases(liveNodes map[string]bool) int {
	r.mu.Lock()
	defer r.mu.Unlock()

	cleared := 0
	for _, ve := range r.volumes {
		if ve.lease == nil {
			continue
		}
		// Extract node name from holder "{nodeName}:{op}:{nonce}".
		nodeName := ve.lease.holder
		if idx := strings.IndexByte(nodeName, ':'); idx > 0 {
			nodeName = nodeName[:idx]
		}
		// Skip Hub-held leases.
		if nodeName == "hub" {
			continue
		}
		if !liveNodes[nodeName] {
			ve.lease = nil
			cleared++
		}
	}
	return cleared
}

// ---------------------------------------------------------------------------
// Stale reference cleanup
// ---------------------------------------------------------------------------

// CleanStaleReferences removes cache and owner references to nodes not in
// the provided live set. Also cleans up template entries for dead nodes.
// This replaces the old ReconcileNodes + UnregisterNode approach — there is
// no node roster to reconcile, just volume/template references to clean.
func (r *NodeRegistry) CleanStaleReferences(liveNodes []string) (cleaned int) {
	live := make(map[string]struct{}, len(liveNodes))
	for _, n := range liveNodes {
		live[n] = struct{}{}
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	// Clean volume owner and cache references.
	for _, ve := range r.volumes {
		if ve.ownerNode != "" {
			if _, alive := live[ve.ownerNode]; !alive {
				ve.ownerNode = ""
				cleaned++
			}
		}
		for nodeName := range ve.cachedNodes {
			if _, alive := live[nodeName]; !alive {
				delete(ve.cachedNodes, nodeName)
				cleaned++
			}
		}
	}

	// Clean template node references.
	for tmpl, nodes := range r.templateNodes {
		for nodeName := range nodes {
			if _, alive := live[nodeName]; !alive {
				delete(nodes, nodeName)
				cleaned++
			}
		}
		if len(nodes) == 0 {
			delete(r.templateNodes, tmpl)
		}
	}

	return cleaned
}

// ---------------------------------------------------------------------------
// Template tracking
// ---------------------------------------------------------------------------

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
