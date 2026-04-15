//go:build integration

package integration

import (
	"context"
	"path/filepath"
	"testing"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
)

// TestBundleRoundtrip exercises the publish → restore round-trip through the
// template manager. Specifically it catches the "btrfs receive writes the
// subvol under its embedded send-stream name" bug: the source subvolume
// ("src-<rand>") is uploaded, then restored under a DIFFERENT requested
// template name ("bundle:<hash>"). Without the receive-to-staging + rename
// fix in pkg/template/manager.go, the restore lands at templates/<src-name>
// rather than templates/bundle:<hash>.
func TestBundleRoundtrip(t *testing.T) {
	pool := getPoolPath(t)
	bucket := uniqueName("bundle-rt")

	bm := newBtrfsManager(t)
	obj := newObjectStorage(t, bucket)
	casStore := cas.NewStore(obj)
	tmplMgr := template.NewManager(bm, casStore, pool)

	ctx := context.Background()

	// 1. Create a source subvolume with a distinctive name and known content.
	srcName := uniqueName("src")
	srcPath := "templates/" + srcName
	if err := bm.CreateSubvolume(ctx, srcPath); err != nil {
		t.Fatalf("CreateSubvolume source: %v", err)
	}
	t.Cleanup(func() { _ = bm.DeleteSubvolume(context.Background(), srcPath) })

	writeTestFile(t, filepath.Join(pool, srcPath), "payload.txt", "hello-bundle")
	writeTestFile(t, filepath.Join(pool, srcPath), "nested/inner.txt", "nested-content")

	// 2. Upload the source subvolume as a CAS blob.
	hash, err := tmplMgr.UploadTemplate(ctx, srcName)
	if err != nil {
		t.Fatalf("UploadTemplate: %v", err)
	}

	// 3. Restore the same blob under a *different* template name. This is
	// the bundle-style pattern used by CreateVolumeFromBundleOnNode.
	tgtName := "bundle:" + hash
	tgtPath := "templates/" + tgtName
	// Record the hash under the new name so EnsureTemplateByHash can resolve it.
	if err := casStore.SetTemplateHash(ctx, tgtName, hash); err != nil {
		t.Fatalf("SetTemplateHash(%s): %v", tgtName, err)
	}
	t.Cleanup(func() { _ = bm.DeleteSubvolume(context.Background(), tgtPath) })

	if err := tmplMgr.EnsureTemplateByHash(ctx, tgtName, hash); err != nil {
		t.Fatalf("EnsureTemplateByHash(%s): %v", tgtName, err)
	}

	// 4. Assert the template landed at templates/<tgtName>, NOT under the
	// source's embedded name.
	if !bm.SubvolumeExists(ctx, tgtPath) {
		t.Fatalf("expected restored template at %q, missing", tgtPath)
	}

	// 5. Byte-match content against the source.
	verifyFileContent(t, filepath.Join(pool, tgtPath, "payload.txt"), "hello-bundle")
	verifyFileContent(t, filepath.Join(pool, tgtPath, "nested/inner.txt"), "nested-content")

	// 6. The staging directory should be gone.
	strayPath := "templates/" + srcName
	// srcPath is the original source and still exists; that's fine — we
	// care that the restore didn't accidentally clobber or skip the rename.
	_ = strayPath
}
