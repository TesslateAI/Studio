// Package volumehub implements the Volume Hub gRPC service.
//
// The Hub is a storageless orchestrator — zero storage, zero btrfs. Nodes
// handle all data: CAS sync, templates, peer transfers. The Hub only
// coordinates: volume→owner_node mapping, template→cached_nodes, node→capacity.
//
// Architecture:
//   - Hub runs as a Deployment (not StatefulSet) — no PVC, no SYS_ADMIN.
//   - Nodes (DaemonSet) own all volume data on local btrfs pools.
//   - Hub delegates all operations to nodes via NodeOps gRPC.
//   - Registry is rebuilt from node queries on Hub restart.
//   - FileOps is served only by nodes (:9742), not by Hub.
package volumehub

import "github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"

// VolumeStatus holds the current state of a volume in the Hub registry.
type VolumeStatus struct {
	VolumeID     string   `json:"volume_id"`
	OwnerNode    string   `json:"owner_node"`
	CachedNodes  []string `json:"cached_nodes"`
	LastSync     string   `json:"last_sync,omitempty"`     // ISO 8601 timestamp
	TemplateName string   `json:"template_name,omitempty"`
	TemplateHash string   `json:"template_hash,omitempty"`
	LatestHash   string   `json:"latest_hash,omitempty"`
	LayerCount   int      `json:"layer_count,omitempty"`
	Snapshots    []cas.Layer `json:"snapshots,omitempty"` // layers with type="snapshot"
}
