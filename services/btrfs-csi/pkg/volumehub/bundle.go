package volumehub

import (
	"context"
	"fmt"

	"k8s.io/klog/v2"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
)

// bundleTemplateName is the synthetic CAS template name under which a
// published bundle is registered. Bundles are content-addressed, so using
// the hash as part of the name guarantees uniqueness.
func bundleTemplateName(hash string) string {
	return fmt.Sprintf("bundle:%s", hash)
}

// PublishBundleForVolume creates an immutable CAS bundle of the named volume.
// The returned hash is the SHA256 digest of the zstd-compressed btrfs send
// stream (i.e., what cas.PutBlob returned). Bundles are content-addressed
// and deduplicated: publishing the same volume state twice yields the same
// hash.
//
// Internally this is a thin wrapper over CreateSnapshotForVolume that labels
// the snapshot explicitly as a bundle, and registers the resulting hash as
// a synthetic template named "bundle:<hash>" so restore can reuse the
// existing template download path.
//
// NOTE: CreateSnapshotForVolume also updates the per-volume "latest hash"
// pointer used by user timelines. This is intentional reuse of the existing
// snapshot primitive per the Wave 1 scope; a future wave may decouple the
// pointer update if publishing should never affect the timeline.
func (s *Server) PublishBundleForVolume(ctx context.Context, volumeID, appID, version string) (string, error) {
	if volumeID == "" {
		return "", fmt.Errorf("volume_id is required")
	}
	if appID == "" || version == "" {
		return "", fmt.Errorf("app_id and version are required")
	}
	label := fmt.Sprintf("bundle:%s:%s", appID, version)
	hash, err := s.CreateSnapshotForVolume(ctx, volumeID, label)
	if err != nil {
		return "", fmt.Errorf("publish bundle for %s: %w", volumeID, err)
	}
	// Record bundle hash in CAS template index so CreateVolumeFromBundle can
	// reuse the existing template download path. Non-fatal on error — the
	// caller can retry registration by republishing or via CreateVolumeFromBundle
	// (which re-sets the mapping idempotently).
	if err := s.cas.SetTemplateHash(ctx, bundleTemplateName(hash), hash); err != nil {
		klog.Warningf("PublishBundleForVolume: set template hash failed (non-fatal): %v", err)
	}
	klog.Infof("PublishBundleForVolume: volume=%s app=%s version=%s → %s",
		volumeID, appID, version, cas.ShortHash(hash))
	return hash, nil
}

// CreateVolumeFromBundleOnNode provisions a new volume on a target node by
// receiving the bundle blob identified by bundleHash from CAS. Returns
// (volumeID, nodeName) on success.
//
// Implementation: the bundle is registered as a synthetic template named
// "bundle:<hash>"; we then invoke CreateVolumeOnNode with that template name
// so node-side fetch-and-receive uses the existing path.
func (s *Server) CreateVolumeFromBundleOnNode(ctx context.Context, bundleHash, hintNode string) (string, string, error) {
	if bundleHash == "" {
		return "", "", fmt.Errorf("bundle_hash is required")
	}
	// Ensure the bundle is registered as a template (idempotent — re-publish
	// adds the same mapping).
	if err := s.cas.SetTemplateHash(ctx, bundleTemplateName(bundleHash), bundleHash); err != nil {
		return "", "", fmt.Errorf("register bundle template: %w", err)
	}

	volumeID, err := generateVolumeID()
	if err != nil {
		return "", "", fmt.Errorf("generate volume id: %w", err)
	}

	nodeName, err := s.CreateVolumeOnNode(ctx, volumeID, bundleTemplateName(bundleHash), hintNode)
	if err != nil {
		return "", "", fmt.Errorf("create volume from bundle: %w", err)
	}
	klog.Infof("CreateVolumeFromBundleOnNode: bundle=%s → volume=%s on %s",
		cas.ShortHash(bundleHash), volumeID, nodeName)
	return volumeID, nodeName, nil
}
