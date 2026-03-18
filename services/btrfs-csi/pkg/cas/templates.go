package cas

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"

	"k8s.io/klog/v2"
)

const templateIndexKey = "index/templates.json"

// templateIndex maps template name → blob hash.
type templateIndex map[string]string

// GetTemplateHash returns the CAS blob hash for the named template.
func (s *Store) GetTemplateHash(ctx context.Context, name string) (string, error) {
	idx, err := s.loadTemplateIndex(ctx)
	if err != nil {
		return "", err
	}
	hash, ok := idx[name]
	if !ok {
		return "", fmt.Errorf("template %q not found in index", name)
	}
	return hash, nil
}

// SetTemplateHash updates the CAS blob hash for a named template.
func (s *Store) SetTemplateHash(ctx context.Context, name, hash string) error {
	idx, err := s.loadTemplateIndex(ctx)
	if err != nil {
		// If index doesn't exist yet, start fresh.
		idx = make(templateIndex)
	}
	idx[name] = hash
	return s.saveTemplateIndex(ctx, idx)
}

// ListTemplateHashes returns all template name→hash entries.
func (s *Store) ListTemplateHashes(ctx context.Context) (map[string]string, error) {
	idx, err := s.loadTemplateIndex(ctx)
	if err != nil {
		return nil, err
	}
	// Return a copy to prevent external mutation.
	result := make(map[string]string, len(idx))
	for k, v := range idx {
		result[k] = v
	}
	return result, nil
}

func (s *Store) loadTemplateIndex(ctx context.Context) (templateIndex, error) {
	exists, err := s.obj.Exists(ctx, templateIndexKey)
	if err != nil {
		return nil, fmt.Errorf("check template index: %w", err)
	}
	if !exists {
		return make(templateIndex), nil
	}

	reader, err := s.obj.Download(ctx, templateIndexKey)
	if err != nil {
		return nil, fmt.Errorf("download template index: %w", err)
	}
	defer reader.Close()

	var idx templateIndex
	if err := json.NewDecoder(reader).Decode(&idx); err != nil {
		return nil, fmt.Errorf("decode template index: %w", err)
	}
	return idx, nil
}

func (s *Store) saveTemplateIndex(ctx context.Context, idx templateIndex) error {
	data, err := json.MarshalIndent(idx, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal template index: %w", err)
	}

	if err := s.obj.Upload(ctx, templateIndexKey, bytes.NewReader(data), int64(len(data))); err != nil {
		return fmt.Errorf("upload template index: %w", err)
	}

	klog.V(3).Infof("Saved template index (%d entries)", len(idx))
	return nil
}
