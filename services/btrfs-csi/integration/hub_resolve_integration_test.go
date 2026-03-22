//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"net"
	"path/filepath"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/encoding"
	"google.golang.org/grpc/status"

	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/cas"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/nodeops"
	bsync "github.com/TesslateAI/tesslate-btrfs-csi/pkg/sync"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/template"
	"github.com/TesslateAI/tesslate-btrfs-csi/pkg/volumehub"
)

func init() {
	encoding.RegisterCodec(hubJSONCodec{})
}

// ---------------------------------------------------------------------------
// Hub gRPC client for integration tests (JSON codec, same as Python client)
// ---------------------------------------------------------------------------

type hubJSONCodec struct{}

func (hubJSONCodec) Marshal(v interface{}) ([]byte, error)     { return json.Marshal(v) }
func (hubJSONCodec) Unmarshal(data []byte, v interface{}) error { return json.Unmarshal(data, v) }
func (hubJSONCodec) Name() string                              { return "json" }

type hubClient struct{ conn *grpc.ClientConn }

type resolveReq struct{ VolumeID string `json:"volume_id"` }
type resolveResp struct {
	NodeName       string `json:"node_name"`
	FileopsAddress string `json:"fileops_address"`
	NodeopsAddress string `json:"nodeops_address"`
	State          string `json:"state"`
}
type ensureCachedReq struct{ VolumeID string `json:"volume_id"` }
type ensureCachedResp struct{ NodeName string `json:"node_name"` }

func (c *hubClient) resolveVolume(ctx context.Context, volID string) (*resolveResp, error) {
	var resp resolveResp
	err := c.conn.Invoke(ctx, "/volumehub.VolumeHub/ResolveVolume",
		&resolveReq{VolumeID: volID}, &resp, grpc.ForceCodec(hubJSONCodec{}))
	return &resp, err
}

func (c *hubClient) ensureCached(ctx context.Context, volID string) (*ensureCachedResp, error) {
	var resp ensureCachedResp
	err := c.conn.Invoke(ctx, "/volumehub.VolumeHub/EnsureCached",
		&ensureCachedReq{VolumeID: volID}, &resp, grpc.ForceCodec(hubJSONCodec{}))
	return &resp, err
}

// startHubAndConnect starts a Hub gRPC server on a free port and returns a
// connected client. Both are cleaned up when the test ends.
func startHubAndConnect(t *testing.T, hub *volumehub.Server) *hubClient {
	t.Helper()

	lis, err := net.Listen("tcp", "localhost:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	addr := lis.Addr().String()
	lis.Close()

	go func() { _ = hub.Start(addr, nil) }()
	time.Sleep(100 * time.Millisecond)
	t.Cleanup(func() { hub.Stop() })

	conn, err := grpc.Dial(addr, grpc.WithTransportCredentials(localhostTestCredentials()))
	if err != nil {
		t.Fatalf("dial hub: %v", err)
	}
	t.Cleanup(func() { conn.Close() })

	return &hubClient{conn: conn}
}

// ---------------------------------------------------------------------------
// Test: ResolveVolume end-to-end — CAS restore after local delete
//
// 1. Create volume, sync to CAS, delete local subvolume
// 2. ResolveVolume → Hub restores from CAS → returns "cached"
// 3. Verify data intact
// ---------------------------------------------------------------------------

func TestHub_ResolveVolume_RestoreFromCAS(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	// CAS infra.
	bucket := uniqueName("resolve")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Template.
	tmplName := uniqueName("resolve-tmpl")
	tmplPath := "templates/" + tmplName
	if err := mgr.CreateSubvolume(ctx, tmplPath); err != nil {
		t.Fatalf("create template: %v", err)
	}
	t.Cleanup(func() { mgr.DeleteSubvolume(context.Background(), tmplPath) })
	writeTestFile(t, filepath.Join(pool, tmplPath), "base.txt", "base-content")

	tmplHash, err := tmplMgr.UploadTemplate(ctx, tmplName)
	if err != nil {
		t.Fatalf("UploadTemplate: %v", err)
	}

	// Volume from template.
	volID := uniqueName("resolve-vol")
	volPath := "volumes/" + volID
	if err := mgr.SnapshotSubvolume(ctx, tmplPath, volPath, false); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
	})

	// Write user data and sync to CAS.
	testData := "user-data-" + uniqueName("payload")
	writeTestFile(t, filepath.Join(pool, volPath), "user-file.txt", testData)

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	daemon.TrackVolume(volID, tmplName, tmplHash)
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Delete local subvolume (simulate node death / cache eviction).
	if err := mgr.DeleteSubvolume(ctx, volPath); err != nil {
		t.Fatalf("delete volume: %v", err)
	}

	// Start NodeOps server (Hub calls RestoreVolume on it).
	nodeOpsAddr := startNodeOpsServer(t, mgr, daemon, tmplMgr)
	nodeName := "test-node"

	// Hub: volume is registered but NOT cached.
	registry := volumehub.NewNodeRegistry()
	registry.RegisterNode(nodeName)
	registry.RegisterVolume(volID)

	hub := volumehub.NewServer(
		registry, casStore,
		func(n string) (*nodeops.Client, error) {
			return nodeops.NewClientWithDialOptions(nodeOpsAddr,
				grpc.WithTransportCredentials(localhostTestCredentials()))
		},
		func(n string) string { return nodeOpsAddr },
		func() []string { return []string{nodeName} },
	)

	client := startHubAndConnect(t, hub)

	// ResolveVolume — should restore from CAS. Small volume, likely completes
	// within the 15s internal timeout.
	resp, err := client.resolveVolume(ctx, volID)
	if err != nil {
		t.Fatalf("ResolveVolume: %v", err)
	}

	switch resp.State {
	case "cached":
		t.Log("ResolveVolume returned cached (fast restore)")
	case "restoring":
		t.Log("ResolveVolume returned restoring — polling")
		for i := 0; i < 30; i++ {
			time.Sleep(2 * time.Second)
			resp, err = client.resolveVolume(ctx, volID)
			if err != nil {
				t.Fatalf("poll: %v", err)
			}
			if resp.State == "cached" {
				break
			}
		}
		if resp.State != "cached" {
			t.Fatalf("still %s after 60s", resp.State)
		}
	default:
		t.Fatalf("unexpected state: %s", resp.State)
	}

	if resp.NodeName != nodeName {
		t.Errorf("NodeName = %q, want %q", resp.NodeName, nodeName)
	}
	if resp.FileopsAddress == "" {
		t.Error("FileopsAddress empty")
	}

	// Verify data is intact.
	verifyFileContent(t, filepath.Join(pool, volPath, "user-file.txt"), testData)
}

// ---------------------------------------------------------------------------
// Test: ResolveVolume fast path — volume already cached
// ---------------------------------------------------------------------------

func TestHub_ResolveVolume_CachedFastPath(t *testing.T) {
	_ = getPoolPath(t) // skip if no btrfs pool

	nodeName := "fast-node"
	nodeOpsAddr := "127.0.0.1:9741"

	registry := volumehub.NewNodeRegistry()
	registry.RegisterNode(nodeName)
	volID := uniqueName("fast-vol")
	registry.RegisterVolume(volID)
	registry.SetCached(volID, nodeName)

	hub := volumehub.NewServer(
		registry, nil,
		func(n string) (*nodeops.Client, error) {
			t.Fatal("nodeClient should not be called on fast path")
			return nil, nil
		},
		func(n string) string { return nodeOpsAddr },
		func() []string { return []string{nodeName} },
	)

	client := startHubAndConnect(t, hub)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := client.resolveVolume(ctx, volID)
	if err != nil {
		t.Fatalf("ResolveVolume: %v", err)
	}

	if resp.State != "cached" {
		t.Fatalf("state = %q, want cached", resp.State)
	}
	if resp.NodeName != nodeName {
		t.Errorf("NodeName = %q, want %q", resp.NodeName, nodeName)
	}
	if resp.FileopsAddress != "127.0.0.1:9742" {
		t.Errorf("FileopsAddress = %q, want 127.0.0.1:9742", resp.FileopsAddress)
	}
}

// ---------------------------------------------------------------------------
// Test: EnsureCached client timeout — restore continues in background
// ---------------------------------------------------------------------------

func TestHub_EnsureCached_ClientTimeout_RestoreContinues(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	bucket := uniqueName("timeout")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	tmplName := uniqueName("timeout-tmpl")
	tmplPath := "templates/" + tmplName
	if err := mgr.CreateSubvolume(ctx, tmplPath); err != nil {
		t.Fatalf("create template: %v", err)
	}
	t.Cleanup(func() { mgr.DeleteSubvolume(context.Background(), tmplPath) })
	writeTestFile(t, filepath.Join(pool, tmplPath), "data.txt", "timeout-data")

	tmplHash, err := tmplMgr.UploadTemplate(ctx, tmplName)
	if err != nil {
		t.Fatalf("UploadTemplate: %v", err)
	}

	volID := uniqueName("timeout-vol")
	volPath := "volumes/" + volID
	if err := mgr.SnapshotSubvolume(ctx, tmplPath, volPath, false); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
	})
	writeTestFile(t, filepath.Join(pool, volPath), "user.txt", "user-content")

	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	daemon.TrackVolume(volID, tmplName, tmplHash)
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("SyncVolume: %v", err)
	}

	// Delete local.
	if err := mgr.DeleteSubvolume(ctx, volPath); err != nil {
		t.Fatalf("delete: %v", err)
	}

	nodeOpsAddr := startNodeOpsServer(t, mgr, daemon, tmplMgr)
	nodeName := "timeout-node"

	registry := volumehub.NewNodeRegistry()
	registry.RegisterNode(nodeName)
	registry.RegisterVolume(volID)

	hub := volumehub.NewServer(
		registry, casStore,
		func(n string) (*nodeops.Client, error) {
			return nodeops.NewClientWithDialOptions(nodeOpsAddr,
				grpc.WithTransportCredentials(localhostTestCredentials()))
		},
		func(n string) string { return nodeOpsAddr },
		func() []string { return []string{nodeName} },
	)

	client := startHubAndConnect(t, hub)

	// EnsureCached with very short timeout — should get DeadlineExceeded.
	shortCtx, shortCancel := context.WithTimeout(ctx, 200*time.Millisecond)
	defer shortCancel()

	_, ecErr := client.ensureCached(shortCtx, volID)
	if ecErr != nil {
		st, _ := status.FromError(ecErr)
		if st.Code() == codes.DeadlineExceeded {
			t.Log("EnsureCached correctly returned DeadlineExceeded")
		} else {
			t.Logf("EnsureCached returned: %v (may have been fast)", ecErr)
		}
	} else {
		t.Log("EnsureCached completed within 200ms (tiny volume)")
		// Still verify data — fast path.
		verifyFileContent(t, filepath.Join(pool, volPath, "user.txt"), "user-content")
		return
	}

	// Background restore should still complete. Poll via ResolveVolume.
	for i := 0; i < 30; i++ {
		time.Sleep(2 * time.Second)
		resp, err := client.resolveVolume(ctx, volID)
		if err != nil {
			t.Fatalf("ResolveVolume: %v", err)
		}
		if resp.State == "cached" {
			t.Log("Background restore completed")
			verifyFileContent(t, filepath.Join(pool, volPath, "user.txt"), "user-content")
			return
		}
	}
	t.Fatal("background restore did not complete within 60s")
}

// ---------------------------------------------------------------------------
// Test: Cross-node CAS restore with auto-promoted synthetic template
//
// Simulates the real failure: volume is auto-promoted, synced with
// incremental layers, then the subvolume + layers + template are all
// deleted (simulating fresh node). RestoreVolume must download the
// parent template from CAS before applying the incremental layer.
// ---------------------------------------------------------------------------

func TestHub_RestoreVolume_CrossNodeWithSyntheticTemplate(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	bucket := uniqueName("crossnode")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create a volume (no template — will be auto-promoted).
	volID := uniqueName("cross-vol")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("create volume: %v", err)
	}
	t.Cleanup(func() {
		mgr.DeleteSubvolume(context.Background(), volPath)
		subs, _ := mgr.ListSubvolumes(context.Background(), "layers/"+volID)
		for _, sub := range subs {
			mgr.DeleteSubvolume(context.Background(), sub.Path)
		}
		mgr.DeleteSubvolume(context.Background(), "templates/_vol_"+volID)
	})

	// Write data.
	testData := "cross-node-data-" + uniqueName("payload")
	writeTestFile(t, filepath.Join(pool, volPath), "user.txt", testData)

	// Sync — this triggers auto-promote (creates synthetic template + full first layer).
	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	daemon.TrackVolume(volID, "", "")
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("First SyncVolume: %v", err)
	}

	// Write more data and sync again (incremental layer from synthetic template).
	writeTestFile(t, filepath.Join(pool, volPath), "extra.txt", "extra-content")
	if err := daemon.SyncVolume(ctx, volID); err != nil {
		t.Fatalf("Second SyncVolume: %v", err)
	}

	// Verify manifest has base set (from auto-promote backfill).
	manifest, err := casStore.GetManifest(ctx, volID)
	if err != nil {
		t.Fatalf("GetManifest: %v", err)
	}
	if manifest.Base == "" {
		t.Fatal("manifest.Base is empty after auto-promote — backfill didn't work")
	}
	t.Logf("Manifest: base=%s, template=%s, layers=%d",
		cas.ShortHash(manifest.Base), manifest.TemplateName, len(manifest.Layers))

	// Delete EVERYTHING local — simulate a completely fresh node.
	if err := mgr.DeleteSubvolume(ctx, volPath); err != nil {
		t.Fatalf("delete volume: %v", err)
	}
	layerSubs, _ := mgr.ListSubvolumes(ctx, "layers/"+volID)
	for _, sub := range layerSubs {
		_ = mgr.DeleteSubvolume(ctx, sub.Path)
	}
	syntheticTmpl := "templates/_vol_" + volID
	if mgr.SubvolumeExists(ctx, syntheticTmpl) {
		_ = mgr.DeleteSubvolume(ctx, syntheticTmpl)
	}

	// Verify nothing is left locally.
	if mgr.SubvolumeExists(ctx, volPath) {
		t.Fatal("volume still exists")
	}
	if mgr.SubvolumeExists(ctx, syntheticTmpl) {
		t.Fatal("synthetic template still exists")
	}

	// Start a new daemon (fresh, no tracking state).
	daemon2 := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	nodeOpsAddr := startNodeOpsServer(t, mgr, daemon2, tmplMgr)
	nodeName := "fresh-node"

	registry := volumehub.NewNodeRegistry()
	registry.RegisterNode(nodeName)
	registry.RegisterVolume(volID)

	hub := volumehub.NewServer(
		registry, casStore,
		func(n string) (*nodeops.Client, error) {
			return nodeops.NewClientWithDialOptions(nodeOpsAddr,
				grpc.WithTransportCredentials(localhostTestCredentials()))
		},
		func(n string) string { return nodeOpsAddr },
		func() []string { return []string{nodeName} },
	)

	client := startHubAndConnect(t, hub)

	// ResolveVolume — should download template from CAS, then restore.
	resp, err := client.resolveVolume(ctx, volID)
	if err != nil {
		t.Fatalf("ResolveVolume: %v", err)
	}

	if resp.State == "restoring" {
		for i := 0; i < 30; i++ {
			time.Sleep(2 * time.Second)
			resp, err = client.resolveVolume(ctx, volID)
			if err != nil {
				t.Fatalf("poll: %v", err)
			}
			if resp.State == "cached" {
				break
			}
		}
	}

	if resp.State != "cached" {
		t.Fatalf("expected cached, got %s", resp.State)
	}

	// Verify ALL data survived the cross-"node" restore.
	verifyFileContent(t, filepath.Join(pool, volPath, "user.txt"), testData)
	verifyFileContent(t, filepath.Join(pool, volPath, "extra.txt"), "extra-content")
	t.Log("Cross-node restore with synthetic template succeeded")
}

// ---------------------------------------------------------------------------
// Test: RebuildRegistry does NOT mark cached when subvolume is missing
//
// If sync daemon tracks a volume but the subvolume was deleted,
// RebuildRegistry should NOT claim it's cached.
// ---------------------------------------------------------------------------

func TestHub_RebuildRegistry_MissingSubvolume(t *testing.T) {
	pool := getPoolPath(t)
	mgr := newBtrfsManager(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	if err := mgr.EnsurePoolStructure(ctx); err != nil {
		t.Fatalf("EnsurePoolStructure: %v", err)
	}

	bucket := uniqueName("rebuild")
	store := newObjectStorage(t, bucket)
	casStore := cas.NewStore(store)
	tmplMgr := template.NewManager(mgr, casStore, pool)

	// Create volume.
	volID := uniqueName("rebuild-vol")
	volPath := "volumes/" + volID
	if err := mgr.CreateSubvolume(ctx, volPath); err != nil {
		t.Fatalf("create volume: %v", err)
	}
	writeTestFile(t, filepath.Join(pool, volPath), "data.txt", "some-data")

	// Start sync daemon and track the volume (so GetSyncState returns it).
	daemon := bsync.NewDaemon(mgr, casStore, tmplMgr, 1*time.Hour)
	daemon.TrackVolume(volID, "", "")

	// Verify tracking.
	states := daemon.GetTrackedState()
	found := false
	for _, st := range states {
		if st.VolumeID == volID {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("volume not tracked by sync daemon")
	}

	// Delete the subvolume — sync daemon still tracks it.
	if err := mgr.DeleteSubvolume(ctx, volPath); err != nil {
		t.Fatalf("delete volume: %v", err)
	}

	// Start NodeOps + Hub, let RebuildRegistry run.
	nodeOpsAddr := startNodeOpsServer(t, mgr, daemon, tmplMgr)
	nodeName := "rebuild-node"

	registry := volumehub.NewNodeRegistry()
	registry.RegisterNode(nodeName)

	hub := volumehub.NewServer(
		registry, casStore,
		func(n string) (*nodeops.Client, error) {
			return nodeops.NewClientWithDialOptions(nodeOpsAddr,
				grpc.WithTransportCredentials(localhostTestCredentials()))
		},
		func(n string) string { return nodeOpsAddr },
		func() []string { return []string{nodeName} },
	)

	// Trigger RebuildRegistry explicitly.
	if err := hub.RebuildRegistry(ctx); err != nil {
		t.Fatalf("RebuildRegistry: %v", err)
	}

	// Volume should be registered (sync daemon knows about it) but NOT cached
	// (subvolume doesn't exist on disk).
	cachedNodes := registry.GetCachedNodes(volID)
	if len(cachedNodes) > 0 {
		t.Fatalf("expected 0 cached nodes (subvolume deleted), got %v", cachedNodes)
	}

	// Owner should still be set (for metadata/sync purposes).
	owner := registry.GetOwner(volID)
	if owner != nodeName {
		t.Errorf("owner = %q, want %q", owner, nodeName)
	}

	t.Log("RebuildRegistry correctly did not mark deleted volume as cached")

	// Cleanup.
	hub.Stop()
}
