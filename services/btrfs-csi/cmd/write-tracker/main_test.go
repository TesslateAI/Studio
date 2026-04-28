// Tests for the inotify-driven write-tracker.
//
// The pure-logic helpers (splitPaths / shouldReport) are exercised in
// every environment. The end-to-end inotify path is gated by
// ``runtime.GOOS == "linux"`` because inotify(7) is Linux-only —
// running on darwin would produce a misleading "skipped: not linux"
// rather than crashing the macOS test runner.
package main

import (
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

// -----------------------------------------------------------------------
// splitPaths — pure helper, runs everywhere
// -----------------------------------------------------------------------

func TestSplitPathsFallback(t *testing.T) {
	got := splitPaths("", "/a:/b")
	if len(got) != 2 || got[0] != "/a" || got[1] != "/b" {
		t.Fatalf("expected fallback to split into [/a /b], got %#v", got)
	}
}

func TestSplitPathsTrimsBlanks(t *testing.T) {
	got := splitPaths("/a::/b: :/c", "")
	want := []string{"/a", "/b", "/c"}
	if len(got) != len(want) {
		t.Fatalf("expected %d entries, got %d (%#v)", len(want), len(got), got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("entry %d: want %q got %q", i, want[i], got[i])
		}
	}
}

func TestSplitPathsCleansSlashes(t *testing.T) {
	got := splitPaths("/a//b/", "")
	if got[0] != "/a/b" {
		t.Fatalf("expected /a/b after Clean, got %q", got[0])
	}
}

// -----------------------------------------------------------------------
// shouldReport — exclude-prefix logic
// -----------------------------------------------------------------------

func newTestTracker(t *testing.T, excludes []string) *tracker {
	t.Helper()
	return &tracker{
		fd:        -1,
		watchDirs: map[int32]string{},
		excludes:  excludes,
	}
}

func TestShouldReportRespectsExcludes(t *testing.T) {
	tr := newTestTracker(t, []string{"/tmp", "/automations"})
	cases := map[string]bool{
		"/var/log/syslog":         true,  // outside excludes — report
		"/etc/passwd":             true,  // outside excludes — report
		"/tmp/foo":                false, // under /tmp — drop
		"/tmp":                    false, // exact prefix — drop
		"/automations/123/x":      false, // under /automations — drop
		"/automations":            false, // exact prefix — drop
		"/var/tmp/x":              true,  // /var/tmp is NOT under /tmp — report
		"/automations-other/file": true,  // similar but distinct dir — report
	}
	for path, want := range cases {
		got := tr.shouldReport(path)
		if got != want {
			t.Errorf("shouldReport(%q) = %v, want %v", path, got, want)
		}
	}
}

func TestShouldReportEmptyExcludes(t *testing.T) {
	tr := newTestTracker(t, nil)
	if !tr.shouldReport("/anything") {
		t.Fatal("with empty excludes, every path should be reported")
	}
}

// -----------------------------------------------------------------------
// emit — verifies the JSON shape we promise to the orchestrator
// -----------------------------------------------------------------------

func TestEmitProducesExpectedJSONShape(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	defer r.Close()

	tr := &tracker{fd: -1, out: json.NewEncoder(w)}
	tr.emit("/var/log/foo")
	w.Close()

	data, err := io.ReadAll(r)
	if err != nil {
		t.Fatalf("read pipe: %v", err)
	}

	var got trackerEvent
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("unmarshal %q: %v", string(data), err)
	}
	if got.Event != "write_outside_tmp" {
		t.Errorf("Event=%q, want write_outside_tmp", got.Event)
	}
	if got.Path != "/var/log/foo" {
		t.Errorf("Path=%q, want /var/log/foo", got.Path)
	}
	if _, err := time.Parse(time.RFC3339Nano, got.TS); err != nil {
		t.Errorf("TS=%q is not RFC3339Nano: %v", got.TS, err)
	}
}

// -----------------------------------------------------------------------
// End-to-end inotify — Linux only
// -----------------------------------------------------------------------

// TestInotifyFiltersExcludedPaths drives a real inotify watcher
// against a temp dir and confirms that:
//   - a write under the watched (non-excluded) path is reported,
//   - a write under an excluded path is dropped.
//
// The test uses two siblings of the temp root: ``observed`` (watched)
// and ``ignored`` (declared excluded). Both are passed as roots so
// inotify watches both, but the exclude-prefix check should suppress
// events for ``ignored``.
func TestInotifyFiltersExcludedPaths(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skipf("inotify is Linux-only (running on %s)", runtime.GOOS)
	}

	tmp := t.TempDir()
	observed := filepath.Join(tmp, "observed")
	ignored := filepath.Join(tmp, "ignored")
	if err := os.MkdirAll(observed, 0o755); err != nil {
		t.Fatalf("mkdir observed: %v", err)
	}
	if err := os.MkdirAll(ignored, 0o755); err != nil {
		t.Fatalf("mkdir ignored: %v", err)
	}

	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	defer r.Close()

	tr, err := newTracker([]string{observed, ignored}, []string{ignored})
	if err != nil {
		t.Fatalf("newTracker: %v", err)
	}
	defer tr.close()
	tr.out = json.NewEncoder(w)
	for _, root := range []string{observed, ignored} {
		tr.addRecursive(root)
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- tr.run(ctx)
	}()

	// Generate one write under each root. Use simple file create —
	// IN_CREATE + IN_CLOSE_WRITE both fire and we only need one
	// matching event per path.
	if err := os.WriteFile(filepath.Join(observed, "hit.txt"), []byte("x"), 0o644); err != nil {
		t.Fatalf("write observed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(ignored, "miss.txt"), []byte("x"), 0o644); err != nil {
		t.Fatalf("write ignored: %v", err)
	}

	// Drain events for a short window then cancel.
	time.Sleep(200 * time.Millisecond)
	cancel()
	w.Close()
	<-done

	data, err := io.ReadAll(r)
	if err != nil {
		t.Fatalf("read pipe: %v", err)
	}

	var sawObserved, sawIgnored bool
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var evt trackerEvent
		if err := json.Unmarshal([]byte(line), &evt); err != nil {
			// Skip the startup breadcrumb — different schema.
			continue
		}
		if evt.Event != "write_outside_tmp" {
			continue
		}
		if strings.HasPrefix(evt.Path, observed) {
			sawObserved = true
		}
		if strings.HasPrefix(evt.Path, ignored) {
			sawIgnored = true
		}
	}

	if !sawObserved {
		t.Errorf("expected at least one write_outside_tmp event under %s; got none. raw=%q", observed, string(data))
	}
	if sawIgnored {
		t.Errorf("expected NO write_outside_tmp events under excluded %s; raw=%q", ignored, string(data))
	}
}
