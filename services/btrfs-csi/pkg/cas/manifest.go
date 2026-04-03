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
