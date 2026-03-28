package volumehub

import (
	"context"
	"time"

	"k8s.io/klog/v2"
)

const (
	// evictionInterval is how often the eviction loop runs.
	evictionInterval = 5 * time.Minute

	// evictionGracePeriod is the minimum time after ownership transfer
	// before a stale cache can be evicted.
	evictionGracePeriod = 1 * time.Hour
)

// CacheEvictor periodically evicts stale cached volumes from nodes.
//
// Eviction criteria (ALL must be true):
//   - Volume ownership has transferred away from this node
//   - Grace period expired (1 hour since ownership transfer)
//   - Volume is not in EVICTING state already
//
// Race prevention: before evicting, the registry marks the volume as
// EVICTING on that node. Any EnsureCached call for an EVICTING volume
// waits for eviction to complete, then re-materializes if needed.
type CacheEvictor struct {
	registry   *NodeRegistry
	nodeClient NodeClientFactory
}

// NewCacheEvictor creates a new evictor.
func NewCacheEvictor(registry *NodeRegistry, nodeClient NodeClientFactory) *CacheEvictor {
	return &CacheEvictor{
		registry:   registry,
		nodeClient: nodeClient,
	}
}

// Start runs the eviction loop. Blocks until ctx is cancelled.
func (e *CacheEvictor) Start(ctx context.Context) {
	klog.Infof("CacheEvictor: starting (interval=%v, grace=%v)", evictionInterval, evictionGracePeriod)

	ticker := time.NewTicker(evictionInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			klog.Infof("CacheEvictor: stopped")
			return
		case <-ticker.C:
			e.runEviction(ctx)
		}
	}
}

// runEviction scans all volumes for stale caches and evicts them.
func (e *CacheEvictor) runEviction(ctx context.Context) {
	candidates := e.registry.FindEvictableCaches(evictionGracePeriod)
	if len(candidates) == 0 {
		return
	}

	klog.Infof("CacheEvictor: found %d eviction candidates", len(candidates))

	for _, c := range candidates {
		if ctx.Err() != nil {
			return
		}
		e.evictOne(ctx, c.VolumeID, c.NodeName)
	}
}

// evictOne evicts a single stale cache entry.
func (e *CacheEvictor) evictOne(ctx context.Context, volumeID, nodeName string) {
	// Mark as evicting (prevents races with EnsureCached)
	if !e.registry.MarkEvicting(volumeID, nodeName) {
		return // Already evicting or not cached
	}

	klog.Infof("CacheEvictor: evicting volume %s from node %s", volumeID, nodeName)

	// Delete the subvolume via NodeOps
	client, err := e.nodeClient(nodeName)
	if err != nil {
		klog.Warningf("CacheEvictor: cannot connect to node %s for eviction: %v", nodeName, err)
		e.registry.ClearEvicting(volumeID, nodeName)
		return
	}

	volPath := "volumes/" + volumeID
	if err := client.DeleteSubvolume(ctx, volPath); err != nil {
		klog.Warningf("CacheEvictor: failed to delete subvolume %s on %s: %v", volumeID, nodeName, err)
		client.Close()
		e.registry.ClearEvicting(volumeID, nodeName)
		return
	}
	client.Close()

	// Remove from registry
	e.registry.RemoveCached(volumeID, nodeName)
	e.registry.ClearEvicting(volumeID, nodeName)

	klog.Infof("CacheEvictor: evicted volume %s from node %s", volumeID, nodeName)
}
