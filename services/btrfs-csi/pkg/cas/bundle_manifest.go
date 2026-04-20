package cas

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"

	"k8s.io/klog/v2"
)

// BundleManifest is a self-contained restore recipe for a published app bundle.
//
// Unlike a volume Manifest — which lives long and mutates as new snapshots land
// on the source volume — a BundleManifest is written exactly once at publish
// time and frozen. It describes which CAS blobs must be fetched, and in what
// order, to reconstruct the bundle's subvolume on a fresh node that has no
// prior state for the source volume.
//
// This exists because bundle publish delegates to the sync daemon's
// incremental-send path: the bundle's head blob is typically a tiny delta
// against the source volume's prior snapshot. Without a record of the ancestry,
// a receiving node has no way to reproduce the chain. The bundle manifest is
// that record, copied from the source volume's Manifest at publish time.
type BundleManifest struct {
	// Head is the final snapshot hash — matches the name suffix in the
	// template index ("bundle:<Head>") and the last Chain entry's Hash.
	Head string `json:"head"`

	// SourceVolume records the originating volume id, for diagnostics only.
	// Install does NOT need to load the source volume's manifest — the full
	// chain needed for receive lives in Chain below.
	SourceVolume string `json:"source_volume,omitempty"`

	// TemplateName, when non-empty, names a shared base template that the
	// earliest link in Chain diffs from. Install must materialise that
	// template before receiving Chain. Empty → Chain[0] is a full send.
	TemplateName string `json:"template_name,omitempty"`

	// Chain is the ordered list of layers, oldest → newest. Each Snapshot's
	// Parent equals the previous entry's Hash (or the template's base UUID
	// for Chain[0] when TemplateName is set, or "" for a full send).
	// Chain[len-1].Hash must equal Head.
	Chain []Snapshot `json:"chain"`
}

// BundleManifestKey is the object-storage key for a bundle manifest. Kept
// exported so callers outside the package can mint keys for list/delete
// operations without duplicating the format.
func BundleManifestKey(hash string) string {
	return fmt.Sprintf("manifests/bundle:%s.json", hash)
}

// AncestorsOf returns the chain of snapshots ending at head, ordered
// oldest → newest (so chain[len-1].Hash == head). Walks Snapshot.Parent
// pointers until a parent is empty or equals the manifest's Base.
//
// Returns an error if head is missing from the manifest's DAG, or if the
// chain cycles, or exceeds a sanity depth bound (guards against corrupt
// manifests).
func (m *Manifest) AncestorsOf(head string) ([]Snapshot, error) {
	if head == "" {
		return nil, fmt.Errorf("head hash is required")
	}
	const maxChainDepth = 10_000 // defence against corrupt DAGs

	reverse := make([]Snapshot, 0, 16)
	seen := make(map[string]struct{}, 16)
	current := head
	for i := 0; i < maxChainDepth; i++ {
		if _, dup := seen[current]; dup {
			return nil, fmt.Errorf("cycle detected at snapshot %s", ShortHash(current))
		}
		seen[current] = struct{}{}

		snap, ok := m.Snapshots[current]
		if !ok {
			return nil, fmt.Errorf("snapshot %s not found in manifest", ShortHash(current))
		}
		reverse = append(reverse, snap)

		// Stop when parent is empty (full send) or equals the template base.
		// Parent == "" → full send: Chain[0] has no parent at all.
		// Parent == Base → Chain[0] diffs from a named template. We stop here
		//   so the template is NOT itself part of the chain — it's materialised
		//   separately via EnsureTemplate before receive begins.
		if snap.Parent == "" || snap.Parent == m.Base {
			break
		}
		current = snap.Parent
	}
	if len(reverse) == maxChainDepth {
		return nil, fmt.Errorf("chain depth exceeded %d starting at %s", maxChainDepth, ShortHash(head))
	}

	// Reverse in place — callers want oldest-first.
	for i, j := 0, len(reverse)-1; i < j; i, j = i+1, j-1 {
		reverse[i], reverse[j] = reverse[j], reverse[i]
	}
	return reverse, nil
}

// PutBundleManifest writes a bundle manifest to object storage under
// manifests/bundle:<head>.json. Overwrites any existing manifest at the same
// key (publish is idempotent for identical content by construction).
func (s *Store) PutBundleManifest(ctx context.Context, bm BundleManifest) error {
	if bm.Head == "" {
		return fmt.Errorf("bundle manifest Head is required")
	}
	if len(bm.Chain) == 0 {
		return fmt.Errorf("bundle manifest Chain is empty")
	}
	if bm.Chain[len(bm.Chain)-1].Hash != bm.Head {
		return fmt.Errorf(
			"bundle manifest inconsistent: Head=%s but last chain entry is %s",
			ShortHash(bm.Head), ShortHash(bm.Chain[len(bm.Chain)-1].Hash),
		)
	}

	data, err := json.MarshalIndent(bm, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal bundle manifest %s: %w", ShortHash(bm.Head), err)
	}
	key := BundleManifestKey(bm.Head)
	if err := s.obj.Upload(ctx, key, bytes.NewReader(data), int64(len(data))); err != nil {
		return fmt.Errorf("upload bundle manifest %s: %w", ShortHash(bm.Head), err)
	}
	klog.V(3).Infof("Saved bundle manifest %s (chain_depth=%d, template=%q)",
		ShortHash(bm.Head), len(bm.Chain), bm.TemplateName)
	return nil
}

// GetBundleManifest reads a bundle manifest from object storage. Returns a
// wrapped error on missing-key so callers can distinguish "bundle predates
// manifest support" from transport failures.
func (s *Store) GetBundleManifest(ctx context.Context, hash string) (*BundleManifest, error) {
	if hash == "" {
		return nil, fmt.Errorf("bundle hash is required")
	}
	key := BundleManifestKey(hash)
	reader, err := s.obj.Download(ctx, key)
	if err != nil {
		return nil, fmt.Errorf("download bundle manifest %s: %w", ShortHash(hash), err)
	}
	defer reader.Close()

	var buf bytes.Buffer
	if _, err := buf.ReadFrom(reader); err != nil {
		return nil, fmt.Errorf("read bundle manifest %s: %w", ShortHash(hash), err)
	}
	var bm BundleManifest
	if err := json.Unmarshal(buf.Bytes(), &bm); err != nil {
		return nil, fmt.Errorf("decode bundle manifest %s: %w", ShortHash(hash), err)
	}
	if bm.Head == "" || len(bm.Chain) == 0 {
		return nil, fmt.Errorf("bundle manifest %s is malformed (missing head or chain)", ShortHash(hash))
	}
	return &bm, nil
}
