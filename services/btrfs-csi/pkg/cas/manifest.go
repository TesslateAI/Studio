package cas

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"k8s.io/klog/v2"
)

// Manifest describes a volume as an ordered chain of content-addressed layers.
// The Base field is the template blob hash; layers are incremental sends on top.
type Manifest struct {
	VolumeID     string  `json:"volume_id"`
	Base         string  `json:"base"`
	TemplateName string  `json:"template_name,omitempty"`
	Layers       []Layer `json:"layers"`
}

// Layer is a single incremental btrfs send stream stored as a CAS blob.
type Layer struct {
	Hash   string `json:"hash"`
	Parent string `json:"parent"`
	Type   string `json:"type"`            // "sync" | "snapshot"
	Label  string `json:"label,omitempty"`
	TS     string `json:"ts"`
}

// manifestKey returns the S3 object key for a volume manifest.
func manifestKey(volumeID string) string {
	return fmt.Sprintf("manifests/%s.json", volumeID)
}

// LatestHash returns the hash of the most recent layer, or Base if no layers.
func (m *Manifest) LatestHash() string {
	if len(m.Layers) > 0 {
		return m.Layers[len(m.Layers)-1].Hash
	}
	return m.Base
}

// AppendLayer adds a layer to the manifest's layer chain.
func (m *Manifest) AppendLayer(l Layer) {
	m.Layers = append(m.Layers, l)
}

// TruncateAfter drops all layers after the one matching targetHash.
// Used for restore: rewind the manifest to a previous point in time.
// If targetHash equals Base, all layers are removed.
func (m *Manifest) TruncateAfter(targetHash string) {
	if targetHash == m.Base {
		m.Layers = nil
		return
	}
	for i, l := range m.Layers {
		if l.Hash == targetHash {
			m.Layers = m.Layers[:i+1]
			return
		}
	}
}

// ShortHash returns the first 12 hex chars of a full "sha256:..." hash.
// Useful for constructing human-readable local snapshot paths.
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

	klog.V(3).Infof("Saved manifest for volume %s (%d layers)", m.VolumeID, len(m.Layers))
	return nil
}

// GetManifest reads a volume manifest from object storage.
func (s *Store) GetManifest(ctx context.Context, volumeID string) (*Manifest, error) {
	key := manifestKey(volumeID)
	reader, err := s.obj.Download(ctx, key)
	if err != nil {
		return nil, fmt.Errorf("download manifest %s: %w", volumeID, err)
	}
	defer reader.Close()

	var m Manifest
	if err := json.NewDecoder(reader).Decode(&m); err != nil {
		return nil, fmt.Errorf("decode manifest %s: %w", volumeID, err)
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

// PutTombstone writes a deletion tombstone for a volume. This is a durable
// S3 marker that prevents offline nodes from resurrecting the volume when
// they restart and run discoverVolumes. The tombstone must be written
// BEFORE any local cleanup — it is the durable intent record.
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

// DeleteTombstone removes a deletion tombstone. Called after a tombstoned
// volume's local resources have been cleaned up on all nodes.
func (s *Store) DeleteTombstone(ctx context.Context, volumeID string) error {
	return s.obj.Delete(ctx, tombstoneKey(volumeID))
}
