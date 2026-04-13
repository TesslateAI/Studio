package cas

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"k8s.io/klog/v2"
)

// Manifest describes a volume as a DAG of content-addressed snapshots,
// modeled after git: snapshots are an append-only hash-indexed store,
// HEAD tracks the current position, and branches are named pointers.
//
// Restoring to a snapshot moves HEAD without deleting history. New syncs
// after restore fork the timeline — the old branch is preserved and can
// be restored later.
type Manifest struct {
	VolumeID     string              `json:"volume_id"`
	Base         string              `json:"base"`
	TemplateName string              `json:"template_name,omitempty"`
	Head         string              `json:"head,omitempty"`               // hash of current snapshot (like git HEAD)
	Branches     map[string]string   `json:"branches,omitempty"`           // name → hash (like git refs)
	Snapshots    map[string]Snapshot `json:"snapshots"`                    // hash → snapshot (append-only DAG)

	// legacyList is populated during deserialization when the manifest uses
	// the old []Snapshot format. It is NOT serialized — only used to convert
	// to the hash-indexed map on first read.
	legacyList []Snapshot `json:"-"`
}

// Snapshot is a single btrfs send stream stored as a CAS blob.
// Each snapshot diffs from its Parent — either the previous snapshot
// (incremental) or the previous consolidation/template (consolidation point).
type Snapshot struct {
	Hash          string `json:"hash"`
	Parent        string `json:"parent"`
	Prev          string `json:"prev,omitempty"`           // always the chronologically previous snapshot (for timeline display; unlike Parent which skips for consolidations)
	Role          string `json:"role"`                    // "sync" | "checkpoint"
	Label         string `json:"label,omitempty"`
	Consolidation bool   `json:"consolidation,omitempty"` // true = parent is previous consolidation, not previous snapshot
	TS            string `json:"ts"`
}

// Layer is an alias kept so existing callers compile during migration.
type Layer = Snapshot

// manifestKey returns the S3 object key for a volume manifest.
func manifestKey(volumeID string) string {
	return fmt.Sprintf("manifests/%s.json", volumeID)
}

// ---------------------------------------------------------------------------
// HEAD and branch operations
// ---------------------------------------------------------------------------

// LatestHash returns the HEAD hash, falling back to Base if no snapshots exist.
func (m *Manifest) LatestHash() string {
	if m.Head != "" {
		return m.Head
	}
	return m.Base
}

// SetHead moves HEAD to the given snapshot hash.
func (m *Manifest) SetHead(hash string) {
	m.Head = hash
}

// SaveBranch creates or updates a named branch pointer.
func (m *Manifest) SaveBranch(name, hash string) {
	if m.Branches == nil {
		m.Branches = make(map[string]string)
	}
	m.Branches[name] = hash
}

// DeleteBranch removes a named branch.
func (m *Manifest) DeleteBranch(name string) {
	delete(m.Branches, name)
}

// ---------------------------------------------------------------------------
// Snapshot operations
// ---------------------------------------------------------------------------

// AppendSnapshot adds a snapshot to the DAG and advances HEAD.
func (m *Manifest) AppendSnapshot(s Snapshot) {
	if m.Snapshots == nil {
		m.Snapshots = make(map[string]Snapshot)
	}
	m.Snapshots[s.Hash] = s
	m.Head = s.Hash
}

// AppendLayer is an alias for AppendSnapshot during migration.
func (m *Manifest) AppendLayer(l Layer) {
	m.AppendSnapshot(l)
}

// GetSnapshot returns the snapshot with the given hash, or nil if not found.
func (m *Manifest) GetSnapshot(hash string) *Snapshot {
	s, ok := m.Snapshots[hash]
	if !ok {
		return nil
	}
	return &s
}

// TruncateAfter is a no-op preserved for backward compatibility.
// With the DAG model, restore moves HEAD instead of truncating.
// This method does nothing — callers should use SetHead instead.
func (m *Manifest) TruncateAfter(targetHash string) {
	// No-op: DAG model preserves all snapshots.
	// HEAD is moved by SetHead, called by RestoreToSnapshot.
}

// SnapshotCount returns the total number of snapshots in the DAG.
func (m *Manifest) SnapshotCount() int {
	return len(m.Snapshots)
}

// ---------------------------------------------------------------------------
// Chain traversal (walks parent pointers, like git log)
// ---------------------------------------------------------------------------

// LatestConsolidation returns the most recent consolidation snapshot
// reachable from HEAD, or nil if none exists.
func (m *Manifest) LatestConsolidation() *Snapshot {
	hash := m.Head
	for hash != "" && hash != m.Base {
		s, ok := m.Snapshots[hash]
		if !ok {
			break
		}
		if s.Consolidation {
			return &s
		}
		hash = s.Parent
	}
	return nil
}

// SnapshotsSinceLastConsolidation counts non-consolidation snapshots
// from HEAD backward until a consolidation is found.
func (m *Manifest) SnapshotsSinceLastConsolidation() int {
	count := 0
	hash := m.Head
	for hash != "" && hash != m.Base {
		s, ok := m.Snapshots[hash]
		if !ok {
			break
		}
		if s.Consolidation {
			break
		}
		count++
		hash = s.Parent
	}
	return count
}

// ConsolidationHashes returns all consolidation hashes reachable from HEAD,
// ordered oldest to newest.
func (m *Manifest) ConsolidationHashes() []string {
	var hashes []string
	hash := m.Head
	for hash != "" && hash != m.Base {
		s, ok := m.Snapshots[hash]
		if !ok {
			break
		}
		if s.Consolidation {
			hashes = append([]string{s.Hash}, hashes...)
		}
		hash = s.Parent
	}
	return hashes
}

// BuildRestoreChain returns the ordered list of snapshot hashes needed to
// restore to the given target. Walks backward from target through parent
// pointers, collecting consolidations for efficient restore:
//
//	template → [consolidation chain] → [incrementals to target]
//
// Returns hashes (not indices) since snapshots are hash-indexed.
func (m *Manifest) BuildRestoreChain(targetHash string) []string {
	if targetHash == "" || targetHash == m.Base {
		return nil
	}

	// Walk backward from target to collect the full ancestor chain.
	var fullChain []string
	hash := targetHash
	for hash != "" && hash != m.Base {
		if _, ok := m.Snapshots[hash]; !ok {
			break
		}
		fullChain = append([]string{hash}, fullChain...)
		hash = m.Snapshots[hash].Parent
	}

	if len(fullChain) == 0 {
		return nil
	}

	// Optimize: find the nearest consolidation and skip earlier incrementals.
	// Walk from end toward start to find the latest consolidation.
	lastConsolIdx := -1
	for i := len(fullChain) - 1; i >= 0; i-- {
		if s, ok := m.Snapshots[fullChain[i]]; ok && s.Consolidation {
			lastConsolIdx = i
			break
		}
	}

	if lastConsolIdx < 0 {
		// No consolidation — need the full chain.
		return fullChain
	}

	// Collect consolidation chain (each consolidation's parent may be an
	// earlier consolidation, not the immediately previous entry).
	consolChain := []string{fullChain[lastConsolIdx]}
	ch := m.Snapshots[fullChain[lastConsolIdx]].Parent
	for ch != "" && ch != m.Base {
		s, ok := m.Snapshots[ch]
		if !ok {
			break
		}
		if s.Consolidation {
			consolChain = append([]string{ch}, consolChain...)
		}
		ch = s.Parent
	}

	// Append incrementals from lastConsolIdx+1 to target.
	chain := consolChain
	for i := lastConsolIdx + 1; i < len(fullChain); i++ {
		chain = append(chain, fullChain[i])
	}
	return chain
}

// ListCheckpoints returns all checkpoint snapshots reachable from HEAD,
// ordered newest to oldest (for user-facing snapshot timeline).
func (m *Manifest) ListCheckpoints() []Snapshot {
	var checkpoints []Snapshot
	hash := m.Head
	for hash != "" && hash != m.Base {
		s, ok := m.Snapshots[hash]
		if !ok {
			break
		}
		if s.Role == "checkpoint" {
			checkpoints = append(checkpoints, s)
		}
		hash = s.Parent
	}
	return checkpoints
}

// PruneConsolidations is a no-op placeholder for future consolidation
// retention. Consolidation blobs form a chain, so pruning requires
// re-basing — not yet implemented.
func (m *Manifest) PruneConsolidations(retention int) []string {
	return nil
}

// ---------------------------------------------------------------------------
// Legacy migration
// ---------------------------------------------------------------------------

// NeedsMigration returns true if the manifest has layers that were all
// created with the same parent (old sync algorithm) and no consolidation
// points exist.
func (m *Manifest) NeedsMigration() bool {
	if len(m.Snapshots) == 0 {
		return false
	}
	if m.LatestConsolidation() != nil {
		return false
	}
	// All parents from HEAD chain must be the same value.
	var commonParent *string
	hash := m.Head
	for hash != "" && hash != m.Base {
		s, ok := m.Snapshots[hash]
		if !ok {
			break
		}
		if commonParent == nil {
			cp := s.Parent
			commonParent = &cp
		} else if s.Parent != *commonParent {
			return false
		}
		hash = s.Parent
	}
	return commonParent != nil
}

// Migrate upgrades a legacy manifest by marking the HEAD snapshot as a
// consolidation point. Returns true if modified.
func (m *Manifest) Migrate() bool {
	if !m.NeedsMigration() {
		return false
	}
	if s, ok := m.Snapshots[m.Head]; ok {
		s.Consolidation = true
		m.Snapshots[m.Head] = s
		return true
	}
	return false
}

// ShortHash returns the first 12 hex chars of a "sha256:..." hash.
func ShortHash(hash string) string {
	h := strings.TrimPrefix(hash, "sha256:")
	if len(h) > 12 {
		return h[:12]
	}
	return h
}

// ---------------------------------------------------------------------------
// S3 persistence
// ---------------------------------------------------------------------------

// PutManifest writes a volume manifest to object storage.
func (s *Store) PutManifest(ctx context.Context, m *Manifest) error {
	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal manifest %s: %w", m.VolumeID, err)
	}

	key := manifestKey(m.VolumeID)
	if err := s.obj.Upload(ctx, key, bytes.NewReader(data), int64(len(data))); err != nil {
		return fmt.Errorf("upload manifest %s: %w", m.VolumeID, err)
	}

	klog.V(3).Infof("Saved manifest for volume %s (%d snapshots, head=%s)",
		m.VolumeID, len(m.Snapshots), ShortHash(m.Head))
	return nil
}

// GetManifest reads a volume manifest from object storage.
// Handles three formats:
//  1. Current: hash-indexed map with head/branches
//  2. Legacy v2: "snapshots" as []Snapshot (ordered list)
//  3. Legacy v1: "layers" with per-entry "type" field
//
// Legacy formats are auto-converted to the DAG model in memory.
// The next PutManifest persists the upgrade.
func (s *Store) GetManifest(ctx context.Context, volumeID string) (*Manifest, error) {
	key := manifestKey(volumeID)
	reader, err := s.obj.Download(ctx, key)
	if err != nil {
		return nil, fmt.Errorf("download manifest %s: %w", volumeID, err)
	}
	defer reader.Close()

	var buf bytes.Buffer
	if _, err := buf.ReadFrom(reader); err != nil {
		return nil, fmt.Errorf("read manifest %s: %w", volumeID, err)
	}

	// Try decoding as current format first (map-indexed snapshots).
	var m Manifest
	if err := json.Unmarshal(buf.Bytes(), &m); err != nil {
		return nil, fmt.Errorf("decode manifest %s: %w", volumeID, err)
	}

	// Detect legacy format: if Snapshots is nil/empty but raw JSON has
	// "snapshots" as an array or "layers", convert from list format.
	if len(m.Snapshots) == 0 {
		converted, convErr := convertLegacyManifest(buf.Bytes(), volumeID)
		if convErr != nil {
			// Not a conversion error — might just be an empty manifest.
			return &m, nil
		}
		if converted != nil {
			return converted, nil
		}
	}

	// Ensure HEAD is set (manifests upgraded from legacy may not have it).
	if m.Head == "" && len(m.Snapshots) > 0 {
		m.Head = findChainTip(m.Snapshots)
	}

	return &m, nil
}

// convertLegacyManifest handles the old []Snapshot and []Layer formats.
func convertLegacyManifest(data []byte, volumeID string) (*Manifest, error) {
	// Decode into raw map to detect legacy keys.
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, err
	}

	// Determine which key holds the list: "layers" (v1) or "snapshots" (v2 list).
	listKey := ""
	if _, ok := raw["layers"]; ok {
		listKey = "layers"
	} else if _, ok := raw["snapshots"]; ok {
		listKey = "snapshots"
	} else {
		return nil, nil // no list found, not a legacy format
	}

	// Try to decode as array.
	var list []json.RawMessage
	if err := json.Unmarshal(raw[listKey], &list); err != nil {
		return nil, nil // not an array — might be the new map format with zero entries
	}
	if len(list) == 0 {
		return nil, nil
	}

	klog.V(2).Infof("Converting legacy manifest for %s (%d entries from %q key)",
		volumeID, len(list), listKey)

	// Parse each entry, handling "type" → "role" rename.
	var snapshots []Snapshot
	for _, raw := range list {
		var entry map[string]json.RawMessage
		if err := json.Unmarshal(raw, &entry); err != nil {
			continue
		}
		// Rename "type" → "role" for v1.
		if t, ok := entry["type"]; ok {
			entry["role"] = t
			delete(entry, "type")
		}
		patched, _ := json.Marshal(entry)
		var s Snapshot
		if err := json.Unmarshal(patched, &s); err != nil {
			continue
		}
		// Normalize role values.
		switch s.Role {
		case "snapshot":
			s.Role = "checkpoint"
		case "":
			s.Role = "sync"
		}
		snapshots = append(snapshots, s)
	}

	// Build the hash-indexed map.
	m := &Manifest{
		Snapshots: make(map[string]Snapshot, len(snapshots)),
	}

	// Decode top-level fields.
	if v, ok := raw["volume_id"]; ok {
		json.Unmarshal(v, &m.VolumeID)
	}
	if v, ok := raw["base"]; ok {
		json.Unmarshal(v, &m.Base)
	}
	if v, ok := raw["template_name"]; ok {
		json.Unmarshal(v, &m.TemplateName)
	}

	for _, s := range snapshots {
		m.Snapshots[s.Hash] = s
	}

	// HEAD = last entry in the list (legacy format was ordered).
	if len(snapshots) > 0 {
		m.Head = snapshots[len(snapshots)-1].Hash
	}

	return m, nil
}

// findChainTip finds the snapshot hash that is not referenced as a parent
// by any other snapshot — the tip of the longest chain. If ambiguous,
// returns the one with the latest timestamp.
func findChainTip(snaps map[string]Snapshot) string {
	isParent := make(map[string]bool, len(snaps))
	for _, s := range snaps {
		if s.Parent != "" {
			isParent[s.Parent] = true
		}
	}
	var tip string
	var tipTS string
	for hash, s := range snaps {
		if !isParent[hash] {
			if tip == "" || s.TS > tipTS {
				tip = hash
				tipTS = s.TS
			}
		}
	}
	if tip != "" {
		return tip
	}
	// Fallback: just pick any.
	for hash := range snaps {
		return hash
	}
	return ""
}

// DeleteManifest removes a volume manifest from object storage.
func (s *Store) DeleteManifest(ctx context.Context, volumeID string) error {
	return s.obj.Delete(ctx, manifestKey(volumeID))
}

// HasManifest returns true if a manifest exists for the given volume.
func (s *Store) HasManifest(ctx context.Context, volumeID string) (bool, error) {
	return s.obj.Exists(ctx, manifestKey(volumeID))
}

// tombstoneKey returns the S3 object key for a volume deletion tombstone.
func tombstoneKey(volumeID string) string {
	return fmt.Sprintf("tombstones/%s", volumeID)
}

// PutTombstone writes a deletion tombstone for a volume.
func (s *Store) PutTombstone(ctx context.Context, volumeID string) error {
	if err := s.obj.Upload(ctx, tombstoneKey(volumeID), bytes.NewReader([]byte{0}), 1); err != nil {
		return fmt.Errorf("write tombstone for %s: %w", volumeID, err)
	}
	klog.V(2).Infof("Wrote tombstone for volume %s", volumeID)
	return nil
}

// HasTombstone returns true if a deletion tombstone exists for the volume.
func (s *Store) HasTombstone(ctx context.Context, volumeID string) (bool, error) {
	return s.obj.Exists(ctx, tombstoneKey(volumeID))
}

// DeleteTombstone removes a deletion tombstone.
func (s *Store) DeleteTombstone(ctx context.Context, volumeID string) error {
	return s.obj.Delete(ctx, tombstoneKey(volumeID))
}
