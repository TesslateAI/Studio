package cas

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"k8s.io/klog/v2"
)

// Manifest describes a volume as an ordered chain of content-addressed snapshots.
type Manifest struct {
	VolumeID     string     `json:"volume_id"`
	Base         string     `json:"base"`
	TemplateName string     `json:"template_name,omitempty"`
	Snapshots    []Snapshot `json:"snapshots"`
}

// Snapshot is a single btrfs send stream stored as a CAS blob.
// Each snapshot diffs from its Parent — either the previous snapshot
// (incremental) or the previous consolidation/template (consolidation point).
type Snapshot struct {
	Hash          string `json:"hash"`
	Parent        string `json:"parent"`
	Role          string `json:"role"`                    // "sync" | "checkpoint" | "consolidation"
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

// LatestHash returns the hash of the most recent snapshot, or Base if none exist.
func (m *Manifest) LatestHash() string {
	if len(m.Snapshots) > 0 {
		return m.Snapshots[len(m.Snapshots)-1].Hash
	}
	return m.Base
}

// AppendSnapshot adds a snapshot to the manifest chain.
func (m *Manifest) AppendSnapshot(s Snapshot) {
	m.Snapshots = append(m.Snapshots, s)
}

// AppendLayer is an alias for AppendSnapshot during migration.
func (m *Manifest) AppendLayer(l Layer) {
	m.AppendSnapshot(l)
}

// TruncateAfter drops all snapshots after the one matching targetHash.
func (m *Manifest) TruncateAfter(targetHash string) {
	if targetHash == m.Base {
		m.Snapshots = nil
		return
	}
	for i, s := range m.Snapshots {
		if s.Hash == targetHash {
			m.Snapshots = m.Snapshots[:i+1]
			return
		}
	}
}

// LatestConsolidation returns the most recent consolidation snapshot, or nil.
func (m *Manifest) LatestConsolidation() *Snapshot {
	for i := len(m.Snapshots) - 1; i >= 0; i-- {
		if m.Snapshots[i].Consolidation {
			return &m.Snapshots[i]
		}
	}
	return nil
}

// NearestConsolidationBefore returns the index of the consolidation at or before idx, or -1.
func (m *Manifest) NearestConsolidationBefore(idx int) int {
	for i := idx; i >= 0; i-- {
		if m.Snapshots[i].Consolidation {
			return i
		}
	}
	return -1
}

// SnapshotsSinceLastConsolidation returns the number of non-consolidation
// snapshots appended after the most recent consolidation (or from the
// beginning if no consolidation exists).
func (m *Manifest) SnapshotsSinceLastConsolidation() int {
	count := 0
	for i := len(m.Snapshots) - 1; i >= 0; i-- {
		if m.Snapshots[i].Consolidation {
			break
		}
		count++
	}
	return count
}

// ConsolidationHashes returns the hashes of all consolidation snapshots,
// ordered oldest to newest.
func (m *Manifest) ConsolidationHashes() []string {
	var hashes []string
	for _, s := range m.Snapshots {
		if s.Consolidation {
			hashes = append(hashes, s.Hash)
		}
	}
	return hashes
}

// PruneConsolidations removes the Consolidation flag from the oldest
// consolidation entries beyond the retention count and returns the blob
// hashes that should be deleted from CAS. The pruned entries remain in
// the manifest as regular snapshots (their blobs are deleted externally).
func (m *Manifest) PruneConsolidations(retention int) []string {
	hashes := m.ConsolidationHashes()
	if len(hashes) <= retention {
		return nil
	}

	pruneCount := len(hashes) - retention
	pruneSet := make(map[string]bool, pruneCount)
	for i := 0; i < pruneCount; i++ {
		pruneSet[hashes[i]] = true
	}

	for i := range m.Snapshots {
		if pruneSet[m.Snapshots[i].Hash] {
			m.Snapshots[i].Consolidation = false
		}
	}

	pruned := make([]string, 0, pruneCount)
	for h := range pruneSet {
		pruned = append(pruned, h)
	}
	return pruned
}

// BuildRestoreChain returns the ordered list of snapshot indices needed to
// restore to the given target index. The chain walks back through
// consolidations to the template, then includes incrementals up to target:
//
//	template → [consolidation chain] → [incrementals after last consolidation to target]
//
// If no consolidation exists at or before target, the full incremental
// chain from index 0 is returned.
func (m *Manifest) BuildRestoreChain(targetIdx int) []int {
	if targetIdx < 0 || targetIdx >= len(m.Snapshots) {
		return nil
	}

	// Find nearest consolidation at or before target.
	consolIdx := m.NearestConsolidationBefore(targetIdx)

	if consolIdx >= 0 {
		// Walk consolidation chain backward to collect all needed consolidations.
		var consolChain []int
		for i := consolIdx; i >= 0; {
			consolChain = append([]int{i}, consolChain...)
			prev := m.NearestConsolidationBefore(i - 1)
			if prev < 0 {
				break
			}
			i = prev
		}

		// Append incrementals from consolIdx+1 to targetIdx.
		chain := consolChain
		for i := consolIdx + 1; i <= targetIdx; i++ {
			chain = append(chain, i)
		}
		return chain
	}

	// No consolidation — full incremental chain from beginning.
	chain := make([]int, targetIdx+1)
	for i := range chain {
		chain[i] = i
	}
	return chain
}

// NeedsMigration returns true if the manifest has layers that were all
// created with the same parent (old sync algorithm) and no consolidation
// points exist. Covers two cases:
//   - Template-based: all parents == Base hash (non-empty)
//   - Template-less: all parents == "" (full sends)
//
// Marking the latest as consolidation makes restore O(1) instead of O(N).
func (m *Manifest) NeedsMigration() bool {
	if len(m.Snapshots) == 0 {
		return false
	}
	if m.LatestConsolidation() != nil {
		return false
	}
	// All parents must be the same value (either Base hash or "").
	commonParent := m.Snapshots[0].Parent
	for _, s := range m.Snapshots {
		if s.Parent != commonParent {
			return false
		}
	}
	return true
}

// Migrate upgrades a legacy manifest to the incremental chain model by
// marking the latest snapshot as a consolidation point (it's a full diff
// from template, so it IS a valid consolidation). Returns true if modified.
func (m *Manifest) Migrate() bool {
	if !m.NeedsMigration() {
		return false
	}
	m.Snapshots[len(m.Snapshots)-1].Consolidation = true
	return true
}

// ShortHash returns the first 12 hex chars of a "sha256:..." hash.
func ShortHash(hash string) string {
	h := strings.TrimPrefix(hash, "sha256:")
	if len(h) > 12 {
		return h[:12]
	}
	return h
}

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

	klog.V(3).Infof("Saved manifest for volume %s (%d snapshots)", m.VolumeID, len(m.Snapshots))
	return nil
}

// GetManifest reads a volume manifest from object storage.
// If the manifest is in legacy format ("layers"/"type"), it is normalized
// to the current format in-memory. The next PutManifest will persist the upgrade.
func (s *Store) GetManifest(ctx context.Context, volumeID string) (*Manifest, error) {
	key := manifestKey(volumeID)
	reader, err := s.obj.Download(ctx, key)
	if err != nil {
		return nil, fmt.Errorf("download manifest %s: %w", volumeID, err)
	}
	defer reader.Close()

	// Decode into raw map to detect legacy keys.
	var raw map[string]json.RawMessage
	var buf bytes.Buffer
	if _, err := buf.ReadFrom(reader); err != nil {
		return nil, fmt.Errorf("read manifest %s: %w", volumeID, err)
	}
	if err := json.Unmarshal(buf.Bytes(), &raw); err != nil {
		return nil, fmt.Errorf("decode manifest %s: %w", volumeID, err)
	}

	// Normalize legacy format: "layers" → "snapshots", per-entry "type" → "role".
	if _, hasLayers := raw["layers"]; hasLayers {
		if _, hasSnapshots := raw["snapshots"]; !hasSnapshots {
			// Rename per-entry "type" → "role" inside the array.
			var entries []map[string]json.RawMessage
			if err := json.Unmarshal(raw["layers"], &entries); err == nil {
				for i := range entries {
					if t, ok := entries[i]["type"]; ok {
						entries[i]["role"] = t
						delete(entries[i], "type")
					}
				}
				if patched, err := json.Marshal(entries); err == nil {
					raw["snapshots"] = patched
				}
			}
			delete(raw, "layers")
		}
	}

	normalized, err := json.Marshal(raw)
	if err != nil {
		return nil, fmt.Errorf("re-encode manifest %s: %w", volumeID, err)
	}
	var m Manifest
	if err := json.Unmarshal(normalized, &m); err != nil {
		return nil, fmt.Errorf("unmarshal manifest %s: %w", volumeID, err)
	}

	// Normalize role values: legacy "snapshot" → "checkpoint", empty → "sync".
	for i := range m.Snapshots {
		switch m.Snapshots[i].Role {
		case "snapshot":
			m.Snapshots[i].Role = "checkpoint"
		case "":
			m.Snapshots[i].Role = "sync"
		}
	}

	return &m, nil
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
