// write-tracker is a tiny in-pod sidecar (Tier 1 ephemeral compute) that
// emits a JSON line to stderr for every filesystem write that happens
// outside an allow-listed prefix set (typically /tmp and /automations).
//
// It is intentionally dependency-light — only golang.org/x/sys/unix —
// so the resulting scratch image stays tiny (~5 MiB compressed) and
// has no kubelet-visible attack surface beyond the inotify(7) syscalls.
//
// Configuration is via env vars (mirrors the rest of the OpenSail
// ephemeral-pod plumbing):
//
//	OPENSAIL_TRACKER_ROOTS    Colon-separated absolute paths to watch.
//	                          Defaults to "/etc:/var:/opt:/usr". We
//	                          deliberately skip /proc and /sys (kernel
//	                          pseudo-fs that confuse inotify) and skip
//	                          / (which would force the watcher to crawl
//	                          every mount). The defaults capture the
//	                          dirs that signal "this tool wrote outside
//	                          /tmp" without recursing into the
//	                          workspace mount.
//	OPENSAIL_TRACKER_EXCLUDES Colon-separated path prefixes that should
//	                          NOT be reported. Defaults to "/tmp:/automations".
//	                          Any event whose path starts with one of
//	                          these is silently dropped.
//
// Output format (one JSON object per line, written to stderr so it
// shows up cleanly in kubectl logs --container=write-tracker):
//
//	{"event":"write_outside_tmp","path":"/var/log/foo","ts":"2026-04-26T12:34:56Z"}
//
// Lifecycle: runs until SIGTERM/SIGINT. The Tier-1 pod's
// restartPolicy=Never plus the agent container's terminal exit means
// kubelet sends the sidecar SIGTERM via the standard pod lifecycle,
// at which point we close the inotify FD and exit cleanly.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/unix"
)

const (
	// Watch every "this directory was mutated" class event. We bundle
	// CREATE/MODIFY/MOVED_TO/ATTRIB/DELETE so the tracker reports the
	// full surface of "filesystem state changed". CLOSE_WRITE alone
	// misses pure rename + chmod events that are still meaningful
	// signals of "tool mutated something outside /tmp".
	defaultWatchMask uint32 = unix.IN_CREATE |
		unix.IN_MODIFY |
		unix.IN_MOVED_TO |
		unix.IN_MOVED_FROM |
		unix.IN_DELETE |
		unix.IN_ATTRIB |
		unix.IN_CLOSE_WRITE

	// Per-watch buffer — must be large enough to hold at least one
	// inotify_event + max NAME_MAX (255). 4 KiB is the practical floor
	// per inotify(7).
	readBufferBytes = 64 * 1024

	defaultRoots    = "/etc:/var:/opt:/usr"
	defaultExcludes = "/tmp:/automations"
)

// trackerEvent is the JSON shape emitted on stderr for each write
// event the runtime decides to surface. Keeping the schema tiny &
// stable lets the orchestrator parse with json.Unmarshal without
// version negotiation.
type trackerEvent struct {
	Event string `json:"event"`
	Path  string `json:"path"`
	TS    string `json:"ts"`
}

// tracker holds the inotify fd + the watch-descriptor → directory map
// (inotify_event payloads carry the basename, not the full path; we
// reconstruct via the wd lookup).
type tracker struct {
	fd        int
	roots     []string
	excludes  []string
	watchDirs map[int32]string // wd → absolute directory path
	out       *json.Encoder
}

func newTracker(roots, excludes []string) (*tracker, error) {
	fd, err := unix.InotifyInit1(unix.IN_CLOEXEC)
	if err != nil {
		return nil, fmt.Errorf("inotify_init1: %w", err)
	}
	return &tracker{
		fd:        fd,
		roots:     roots,
		excludes:  excludes,
		watchDirs: make(map[int32]string),
		out:       json.NewEncoder(os.Stderr),
	}, nil
}

func (t *tracker) close() {
	if t.fd >= 0 {
		_ = unix.Close(t.fd)
		t.fd = -1
	}
}

// addWatch registers a single directory with inotify. Errors are
// non-fatal — a missing dir (common — /opt isn't always present) is
// logged once and skipped. Re-watching is harmless; inotify returns
// the same wd for the same path.
func (t *tracker) addWatch(dir string) {
	wd, err := unix.InotifyAddWatch(t.fd, dir, defaultWatchMask)
	if err != nil {
		// EACCES on /etc/ssl/private and similar is expected in
		// hardened images. ENOENT means the dir doesn't exist —
		// silently skip both. Anything else gets stderr breadcrumb.
		if err != unix.EACCES && err != unix.ENOENT {
			fmt.Fprintf(os.Stderr,
				`{"event":"write_tracker_warning","path":%q,"error":%q}`+"\n",
				dir, err.Error())
		}
		return
	}
	t.watchDirs[int32(wd)] = dir
}

// addRecursive walks ``root`` and registers a watch on every directory.
// inotify(7) is per-directory, not recursive — explicit walk is the
// only correct way to cover a tree.
func (t *tracker) addRecursive(root string) {
	_ = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			// Skip unreadable subtrees (perm denied, vanished
			// during walk). This is the read-only mount case
			// for /etc/shadow etc.
			return nil
		}
		if !d.IsDir() {
			return nil
		}
		t.addWatch(path)
		return nil
	})
}

// shouldReport returns false when the path falls under one of the
// excluded prefixes. Prefix match is intentional: /tmp/foo and
// /automations/123/bar both filter out, but /var/tmp/x stays in
// (it's not under "/tmp" — leading slash is part of the prefix).
func (t *tracker) shouldReport(path string) bool {
	for _, prefix := range t.excludes {
		if path == prefix || strings.HasPrefix(path, prefix+string(os.PathSeparator)) {
			return false
		}
	}
	return true
}

// emit writes one JSON event line. Errors writing are intentionally
// swallowed — losing a stderr line because the descriptor is wedged
// is preferable to crashing the sidecar (which would leave the
// agent container alive but unmonitored).
func (t *tracker) emit(path string) {
	evt := trackerEvent{
		Event: "write_outside_tmp",
		Path:  path,
		TS:    time.Now().UTC().Format(time.RFC3339Nano),
	}
	_ = t.out.Encode(&evt)
}

// run pumps inotify events until ctx is cancelled.
func (t *tracker) run(ctx context.Context) error {
	buf := make([]byte, readBufferBytes)

	// Use a goroutine to translate ctx cancellation into a closed fd
	// so the blocking Read returns immediately.
	go func() {
		<-ctx.Done()
		t.close()
	}()

	for {
		n, err := unix.Read(t.fd, buf)
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			if err == unix.EINTR {
				continue
			}
			return fmt.Errorf("inotify read: %w", err)
		}
		if n <= 0 {
			if ctx.Err() != nil {
				return nil
			}
			continue
		}

		// Decode the event stream. Multiple events may be packed
		// into one read; we walk the buffer using the variable-
		// length name field per event.
		offset := 0
		for offset < n {
			if offset+int(unsafe.Sizeof(unix.InotifyEvent{})) > n {
				break
			}
			raw := (*unix.InotifyEvent)(unsafe.Pointer(&buf[offset]))
			nameLen := int(raw.Len)
			nameBytes := buf[offset+int(unsafe.Sizeof(unix.InotifyEvent{})) : offset+int(unsafe.Sizeof(unix.InotifyEvent{}))+nameLen]
			name := strings.TrimRight(string(nameBytes), "\x00")

			dir, ok := t.watchDirs[raw.Wd]
			if ok {
				fullPath := dir
				if name != "" {
					fullPath = filepath.Join(dir, name)
				}
				if t.shouldReport(fullPath) {
					t.emit(fullPath)
				}

				// If this event created a new directory under a
				// watched root, recurse so we keep observing
				// children. CREATE+ISDIR is the canonical pattern.
				if raw.Mask&unix.IN_CREATE != 0 && raw.Mask&unix.IN_ISDIR != 0 {
					t.addWatch(fullPath)
				}
			}

			offset += int(unsafe.Sizeof(unix.InotifyEvent{})) + nameLen
		}
	}
}

func splitPaths(value, fallback string) []string {
	if value == "" {
		value = fallback
	}
	parts := strings.Split(value, ":")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		out = append(out, filepath.Clean(p))
	}
	return out
}

func main() {
	roots := splitPaths(os.Getenv("OPENSAIL_TRACKER_ROOTS"), defaultRoots)
	excludes := splitPaths(os.Getenv("OPENSAIL_TRACKER_EXCLUDES"), defaultExcludes)

	t, err := newTracker(roots, excludes)
	if err != nil {
		fmt.Fprintf(os.Stderr,
			`{"event":"write_tracker_fatal","error":%q}`+"\n", err.Error())
		os.Exit(1)
	}

	// Best-effort startup breadcrumb so operators can correlate the
	// sidecar starting with a run id (the orchestrator stamps the env
	// vars on the agent container; the tracker doesn't read them but
	// having a startup line in the log helps debugging).
	_ = t.out.Encode(&trackerEvent{
		Event: "write_tracker_started",
		Path:  strings.Join(roots, ":"),
		TS:    time.Now().UTC().Format(time.RFC3339Nano),
	})

	for _, root := range roots {
		t.addRecursive(root)
	}

	ctx, cancel := signal.NotifyContext(context.Background(),
		syscall.SIGTERM, syscall.SIGINT)
	defer cancel()

	if err := t.run(ctx); err != nil {
		fmt.Fprintf(os.Stderr,
			`{"event":"write_tracker_fatal","error":%q}`+"\n", err.Error())
		os.Exit(1)
	}
}
