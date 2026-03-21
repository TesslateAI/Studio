package btrfs

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"k8s.io/klog/v2"
)

// btrfsBin is the hardcoded path to the btrfs binary. All command execution
// in this package is restricted to this single binary.
const btrfsBin = "btrfs"

// SubvolumeInfo holds metadata about a btrfs subvolume.
type SubvolumeInfo struct {
	ID        int
	Name      string
	Path      string
	ReadOnly  bool
	CreatedAt time.Time
}

// Manager wraps btrfs CLI operations against a pool directory.
// All methods shell out to btrfs-progs via exec.CommandContext.
type Manager struct {
	poolPath string
	mu       sync.Mutex
}

// NewManager creates a Manager that operates on the given pool mount path.
func NewManager(poolPath string) *Manager {
	return &Manager{poolPath: poolPath}
}

// PoolPath returns the configured pool mount path.
func (m *Manager) PoolPath() string {
	return m.poolPath
}

// ---------------------------------------------------------------------------
// Subvolume operations
// ---------------------------------------------------------------------------

// CreateSubvolume creates a new btrfs subvolume at /pool/{name}.
func (m *Manager) CreateSubvolume(ctx context.Context, name string) error {
	target, err := m.safePath(name)
	if err != nil {
		return err
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	_, err = m.run(ctx, "subvolume", "create", target)
	if err != nil {
		return fmt.Errorf("create subvolume %q: %w", name, err)
	}
	klog.V(4).Infof("Created subvolume %s", target)
	return nil
}

// DeleteSubvolume deletes the btrfs subvolume at /pool/{name}.
func (m *Manager) DeleteSubvolume(ctx context.Context, name string) error {
	target, err := m.safePath(name)
	if err != nil {
		return err
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	_, err = m.run(ctx, "subvolume", "delete", target)
	if err != nil {
		return fmt.Errorf("delete subvolume %q: %w", name, err)
	}
	klog.V(4).Infof("Deleted subvolume %s", target)
	return nil
}

// RenameSubvolume renames a btrfs subvolume from /pool/{oldName} to
// /pool/{newName}. Uses os.Rename (preserves UUID and received_uuid) with
// SnapshotSubvolume + DeleteSubvolume fallback if os.Rename fails.
func (m *Manager) RenameSubvolume(ctx context.Context, oldName, newName string) error {
	oldFull, err := m.safePath(oldName)
	if err != nil {
		return err
	}
	newFull, nErr := m.safePath(newName)
	if nErr != nil {
		return nErr
	}

	// Ensure the parent directory of the target exists.
	if mkErr := os.MkdirAll(filepath.Dir(newFull), 0755); mkErr != nil {
		return fmt.Errorf("mkdir parent for %q: %w", newName, mkErr)
	}

	// Primary: os.Rename preserves UUID + received_uuid.
	if err := os.Rename(oldFull, newFull); err == nil {
		klog.V(4).Infof("Renamed subvolume %s -> %s (os.Rename)", oldName, newName)
		return nil
	} else {
		klog.Warningf("os.Rename %s -> %s failed (%v), falling back to snapshot+delete", oldName, newName, err)
	}

	// Fallback: snapshot + delete (works but loses received_uuid).
	if err := m.SnapshotSubvolume(ctx, oldName, newName, true); err != nil {
		return fmt.Errorf("fallback snapshot %s -> %s: %w", oldName, newName, err)
	}
	if err := m.DeleteSubvolume(ctx, oldName); err != nil {
		klog.Warningf("RenameSubvolume fallback: failed to delete %s after snapshot: %v", oldName, err)
	}
	klog.V(4).Infof("Renamed subvolume %s -> %s (snapshot+delete fallback)", oldName, newName)
	return nil
}

// SnapshotSubvolume creates a snapshot of /pool/{source} at /pool/{dest}.
// If readOnly is true the snapshot is created with the -r flag.
func (m *Manager) SnapshotSubvolume(ctx context.Context, source, dest string, readOnly bool) error {
	srcPath, err := m.safePath(source)
	if err != nil {
		return err
	}
	dstPath, err := m.safePath(dest)
	if err != nil {
		return err
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	args := []string{"subvolume", "snapshot"}
	if readOnly {
		args = append(args, "-r")
	}
	args = append(args, srcPath, dstPath)

	_, err = m.run(ctx, args...)
	if err != nil {
		return fmt.Errorf("snapshot %q -> %q: %w", source, dest, err)
	}
	klog.V(4).Infof("Snapshot %s -> %s (readOnly=%v)", srcPath, dstPath, readOnly)
	return nil
}

// SubvolumeExists returns true if the path exists and is a btrfs subvolume.
func (m *Manager) SubvolumeExists(ctx context.Context, name string) bool {
	target, err := m.safePath(name)
	if err != nil {
		return false
	}

	info, err := os.Stat(target)
	if err != nil || !info.IsDir() {
		return false
	}

	// Verify it is actually a subvolume, not just a directory.
	_, err = m.run(ctx, "subvolume", "show", target)
	return err == nil
}

// IsReadOnly returns true if the named subvolume has the read-only flag set.
func (m *Manager) IsReadOnly(ctx context.Context, name string) (bool, error) {
	target, err := m.safePath(name)
	if err != nil {
		return false, err
	}
	out, err := m.run(ctx, "property", "get", target, "ro")
	if err != nil {
		return false, fmt.Errorf("property get ro %q: %w", name, err)
	}
	return strings.Contains(out, "ro=true"), nil
}

// SetReadOnly sets or clears the read-only flag on a subvolume.
func (m *Manager) SetReadOnly(ctx context.Context, name string, readOnly bool) error {
	target, err := m.safePath(name)
	if err != nil {
		return err
	}
	val := "false"
	if readOnly {
		val = "true"
	}
	_, err = m.run(ctx, "property", "set", target, "ro", val)
	if err != nil {
		return fmt.Errorf("property set ro=%s %q: %w", val, name, err)
	}
	return nil
}

// EnsureReadOnly checks whether a subvolume is read-only and sets it if not.
func (m *Manager) EnsureReadOnly(ctx context.Context, name string) error {
	ro, err := m.IsReadOnly(ctx, name)
	if err != nil {
		return err
	}
	if ro {
		return nil
	}
	return m.SetReadOnly(ctx, name, true)
}

// ListSubvolumes lists subvolumes under the pool whose path contains the
// given prefix. It parses output from `btrfs subvolume list`.
func (m *Manager) ListSubvolumes(ctx context.Context, prefix string) ([]SubvolumeInfo, error) {
	output, err := m.run(ctx, "subvolume", "list", "--sort=ogen", m.poolPath)
	if err != nil {
		return nil, fmt.Errorf("list subvolumes: %w", err)
	}

	var results []SubvolumeInfo
	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		line := scanner.Text()
		info, ok := parseSubvolumeLine(line)
		if !ok {
			continue
		}
		if prefix == "" || strings.HasPrefix(info.Path, prefix) {
			results = append(results, info)
		}
	}

	// Enrich with read-only status and creation time where possible.
	for i := range results {
		fullPath := filepath.Join(m.poolPath, results[i].Path)
		showOut, showErr := m.run(ctx, "subvolume", "show", fullPath)
		if showErr == nil {
			if strings.Contains(showOut, "readonly") && strings.Contains(showOut, "true") {
				results[i].ReadOnly = true
			}
		}
		// Use directory mtime as creation proxy — btrfs preserves mtime of
		// the subvolume root directory from creation.
		if info, statErr := os.Stat(fullPath); statErr == nil {
			results[i].CreatedAt = info.ModTime()
		}
	}

	return results, nil
}

// ---------------------------------------------------------------------------
// Filesystem operations
// ---------------------------------------------------------------------------

// GetCapacity returns the total and available bytes on the pool filesystem.
// It parses the output of `btrfs filesystem usage -b`.
func (m *Manager) GetCapacity(ctx context.Context) (totalBytes, availableBytes int64, err error) {
	output, err := m.run(ctx, "filesystem", "usage", "-b", m.poolPath)
	if err != nil {
		return 0, 0, fmt.Errorf("filesystem usage: %w", err)
	}

	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, "Device size:") {
			totalBytes = extractBytes(line)
		} else if strings.HasPrefix(line, "Free (estimated):") {
			availableBytes = extractBytes(line)
		}
	}

	if totalBytes == 0 {
		return 0, 0, fmt.Errorf("failed to parse device size from btrfs filesystem usage")
	}
	return totalBytes, availableBytes, nil
}

// GetSubvolumeSize returns the number of bytes used by the subvolume at
// /pool/{name}. It attempts to read the qgroup data; if quotas are not
// enabled it falls back to a filesystem stat.
func (m *Manager) GetSubvolumeSize(ctx context.Context, name string) (usedBytes int64, err error) {
	target, err := m.safePath(name)
	if err != nil {
		return 0, err
	}

	// Try qgroup first (most accurate when quotas are enabled).
	showOut, showErr := m.run(ctx, "qgroup", "show", "--raw", "-f", target)
	if showErr == nil {
		scanner := bufio.NewScanner(strings.NewReader(showOut))
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			// Lines look like: 0/258       16384    16384
			fields := strings.Fields(line)
			if len(fields) >= 2 && strings.Contains(fields[0], "/") {
				val, parseErr := strconv.ParseInt(fields[1], 10, 64)
				if parseErr == nil && val > 0 {
					return val, nil
				}
			}
		}
	}

	// Fallback: use statfs to get a rough estimate.
	var stat syscallStatfs
	if statErr := statfs(target, &stat); statErr != nil {
		return 0, fmt.Errorf("statfs %q: %w", name, statErr)
	}
	used := int64(stat.Blocks-stat.Bfree) * int64(stat.Bsize)
	return used, nil
}

// ---------------------------------------------------------------------------
// Send / Receive (for S3 persistence)
// ---------------------------------------------------------------------------

// Send starts a `btrfs send` process for the given snapshot path and returns
// a ReadCloser connected to its stdout. If parentPath is non-empty an
// incremental send is performed using -p. The caller is responsible for
// reading the stream and closing it.
func (m *Manager) Send(ctx context.Context, snapshotPath string, parentPath string) (io.ReadCloser, error) {
	snapFull, err := m.safePath(snapshotPath)
	if err != nil {
		return nil, err
	}

	args := []string{"send"}
	if parentPath != "" {
		parentFull, pErr := m.safePath(parentPath)
		if pErr != nil {
			return nil, pErr
		}
		args = append(args, "-p", parentFull)
	}
	args = append(args, snapFull)

	cmd := exec.CommandContext(ctx, btrfsBin, args...) // #nosec G204 -- args are validated by safePath
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("stdout pipe for btrfs send: %w", err)
	}

	cmd.Stderr = &logWriter{prefix: "btrfs send"}

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start btrfs send: %w", err)
	}

	// Wrap stdout so that closing it also waits for the process to exit.
	return &cmdReadCloser{ReadCloser: stdout, cmd: cmd}, nil
}

// Receive pipes the contents of reader into `btrfs receive` at /pool/{destDir}.
func (m *Manager) Receive(ctx context.Context, destDir string, reader io.Reader) error {
	destFull, err := m.safePath(destDir)
	if err != nil {
		return err
	}

	// Ensure the destination directory exists.
	if mkErr := os.MkdirAll(destFull, 0755); mkErr != nil {
		return fmt.Errorf("mkdir %q: %w", destFull, mkErr)
	}

	cmd := exec.CommandContext(ctx, btrfsBin, "receive", destFull) // #nosec G204 -- destFull validated by safePath
	cmd.Stdin = reader
	cmd.Stderr = &logWriter{prefix: "btrfs receive"}

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("btrfs receive into %q: %w", destDir, err)
	}
	klog.V(4).Infof("btrfs receive completed in %s", destFull)
	return nil
}

// ---------------------------------------------------------------------------
// Pool initialization
// ---------------------------------------------------------------------------

// EnsurePoolStructure creates the top-level pool subdirectories (templates/,
// volumes/, snapshots/) as btrfs subvolumes if they do not already exist.
func (m *Manager) EnsurePoolStructure(ctx context.Context) error {
	for _, dir := range []string{"templates", "volumes", "snapshots", "layers"} {
		if m.SubvolumeExists(ctx, dir) {
			continue
		}
		// If the path exists as a plain directory, skip subvolume creation.
		full := filepath.Join(m.poolPath, dir)
		if info, statErr := os.Stat(full); statErr == nil && info.IsDir() {
			klog.V(2).Infof("Pool directory %s exists as plain dir, skipping subvolume create", dir)
			continue
		}
		if err := m.CreateSubvolume(ctx, dir); err != nil {
			return fmt.Errorf("ensure pool structure %q: %w", dir, err)
		}
	}
	klog.V(2).Info("Pool structure verified")
	return nil
}

// EnableQuotas enables btrfs quotas on the pool filesystem.
func (m *Manager) EnableQuotas(ctx context.Context) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	_, err := m.run(ctx, "quota", "enable", m.poolPath)
	if err != nil {
		return fmt.Errorf("enable quotas: %w", err)
	}
	klog.V(2).Info("btrfs quotas enabled")
	return nil
}

// ---------------------------------------------------------------------------
// Quota group operations
// ---------------------------------------------------------------------------

// getSubvolumeID retrieves the btrfs subvolume ID for the given relative name
// by parsing the output of `btrfs subvolume show`.
func (m *Manager) getSubvolumeID(ctx context.Context, name string) (int, error) {
	target, err := m.safePath(name)
	if err != nil {
		return 0, err
	}
	output, err := m.run(ctx, "subvolume", "show", target)
	if err != nil {
		return 0, fmt.Errorf("subvolume show %q: %w", name, err)
	}
	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if after, ok := strings.CutPrefix(line, "Subvolume ID:"); ok {
			field := strings.TrimSpace(after)
			id, parseErr := strconv.Atoi(field)
			if parseErr != nil {
				return 0, fmt.Errorf("parse subvolume ID %q: %w", field, parseErr)
			}
			return id, nil
		}
	}
	return 0, fmt.Errorf("subvolume ID not found in show output for %q", name)
}

// SetQgroupLimit sets a storage quota on a subvolume via btrfs qgroup.
// If bytes <= 0, the limit is removed ("none").
func (m *Manager) SetQgroupLimit(ctx context.Context, name string, bytes int64) error {
	id, err := m.getSubvolumeID(ctx, name)
	if err != nil {
		return fmt.Errorf("get subvolume ID for quota: %w", err)
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	var limitArg string
	if bytes <= 0 {
		limitArg = "none"
	} else {
		limitArg = strconv.FormatInt(bytes, 10)
	}

	qgroup := fmt.Sprintf("0/%d", id)
	_, err = m.run(ctx, "qgroup", "limit", limitArg, qgroup, m.poolPath)
	if err != nil {
		return fmt.Errorf("set qgroup limit on %q: %w", name, err)
	}
	klog.V(4).Infof("Set qgroup limit %s on %s (qgroup=%s)", limitArg, name, qgroup)
	return nil
}

// GetQgroupUsage returns the exclusive byte usage and limit for a subvolume's qgroup.
// Exclusive bytes exclude shared CoW blocks from templates.
// Returns limit=0 if no limit is set ("none").
func (m *Manager) GetQgroupUsage(ctx context.Context, name string) (exclusive int64, limit int64, err error) {
	id, err := m.getSubvolumeID(ctx, name)
	if err != nil {
		return 0, 0, fmt.Errorf("get subvolume ID for usage: %w", err)
	}

	target, err := m.safePath(name)
	if err != nil {
		return 0, 0, err
	}

	output, err := m.run(ctx, "qgroup", "show", "--raw", "-re", target)
	if err != nil {
		return 0, 0, fmt.Errorf("qgroup show %q: %w", name, err)
	}

	qgroupPrefix := fmt.Sprintf("0/%d", id)
	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		fields := strings.Fields(line)
		if len(fields) >= 3 && fields[0] == qgroupPrefix {
			// With --raw -re the format is:
			//   0/{id}  <rfer>  <excl>  <max_rfer>  <max_excl>
			// "none" appears as literal "none" for unlimited.
			excl, parseErr := strconv.ParseInt(fields[2], 10, 64)
			if parseErr != nil {
				return 0, 0, fmt.Errorf("parse exclusive bytes %q: %w", fields[2], parseErr)
			}
			// Parse max_rfer (field 3) as the limit.
			if len(fields) >= 4 {
				lim, limErr := strconv.ParseInt(fields[3], 10, 64)
				if limErr == nil {
					limit = lim
				}
				// If "none", limErr != nil and limit stays 0.
			}
			return excl, limit, nil
		}
	}
	return 0, 0, fmt.Errorf("qgroup %s not found in show output for %q", qgroupPrefix, name)
}

// ---------------------------------------------------------------------------
// Ownership operations
// ---------------------------------------------------------------------------

// SafePath validates and returns the clean absolute path for a subvolume name.
// Exposed for use by nodeops handlers that need to perform post-creation operations.
func (m *Manager) SafePath(name string) (string, error) {
	return m.safePath(name)
}

// SetOwnership recursively chowns a subvolume to the given uid:gid.
func (m *Manager) SetOwnership(ctx context.Context, name string, uid, gid int) error {
	target, err := m.safePath(name)
	if err != nil {
		return err
	}
	return filepath.WalkDir(target, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return os.Chown(path, uid, gid)
	})
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// run executes a btrfs sub-command and returns its stdout output. The binary
// is always the hardcoded btrfsBin constant; only btrfs sub-command arguments
// are accepted. If the command fails stderr is logged at the error level.
func (m *Manager) run(ctx context.Context, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, btrfsBin, args...) // #nosec G204 -- binary is a hardcoded constant
	var stdout strings.Builder
	var stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	klog.V(5).Infof("exec: %s %s", btrfsBin, strings.Join(args, " "))
	if err := cmd.Run(); err != nil {
		if stderr.Len() > 0 {
			klog.Errorf("cmd %s stderr: %s", btrfsBin, strings.TrimSpace(stderr.String()))
		}
		return stdout.String(), fmt.Errorf("%s %s: %w", btrfsBin, strings.Join(args, " "), err)
	}
	return stdout.String(), nil
}

// safePath validates that the given name, when joined with poolPath, does not
// escape outside the pool directory. Returns the clean absolute path.
func (m *Manager) safePath(name string) (string, error) {
	full := filepath.Join(m.poolPath, name)
	clean := filepath.Clean(full)

	poolClean := filepath.Clean(m.poolPath)
	if !strings.HasPrefix(clean, poolClean+string(filepath.Separator)) && clean != poolClean {
		return "", fmt.Errorf("path traversal detected: %q resolves outside pool %q", name, m.poolPath)
	}
	return clean, nil
}

// parseSubvolumeLine parses a single line from `btrfs subvolume list` output.
// Example line: "ID 258 gen 42 top level 5 path volumes/my-vol"
func parseSubvolumeLine(line string) (SubvolumeInfo, bool) {
	fields := strings.Fields(line)
	if len(fields) < 9 {
		return SubvolumeInfo{}, false
	}

	// Expected format: ID <id> gen <gen> top level <toplevel> path <path>
	if fields[0] != "ID" {
		return SubvolumeInfo{}, false
	}

	id, err := strconv.Atoi(fields[1])
	if err != nil {
		return SubvolumeInfo{}, false
	}

	// The path is everything after "path ".
	_, subPath, found := strings.Cut(line, " path ")
	if !found {
		return SubvolumeInfo{}, false
	}
	subPath = strings.TrimSpace(subPath)

	return SubvolumeInfo{
		ID:   id,
		Name: filepath.Base(subPath),
		Path: subPath,
	}, true
}

// extractBytes pulls a numeric byte value from a btrfs output line.
// It looks for the last token that is a pure integer.
func extractBytes(line string) int64 {
	fields := strings.Fields(line)
	for i := len(fields) - 1; i >= 0; i-- {
		// Strip parenthesized annotations like "(min: ...)"
		cleaned := strings.Trim(fields[i], "()")
		val, err := strconv.ParseInt(cleaned, 10, 64)
		if err == nil {
			return val
		}
	}
	return 0
}

// cmdReadCloser wraps a stdout pipe so that Close also waits for the
// underlying process to exit.
type cmdReadCloser struct {
	io.ReadCloser
	cmd *exec.Cmd
}

func (c *cmdReadCloser) Close() error {
	_ = c.ReadCloser.Close()
	return c.cmd.Wait()
}

// logWriter is an io.Writer that forwards written data to klog as warnings.
type logWriter struct {
	prefix string
}

func (w *logWriter) Write(p []byte) (int, error) {
	msg := strings.TrimSpace(string(p))
	if msg != "" {
		klog.Warningf("[%s] %s", w.prefix, msg)
	}
	return len(p), nil
}
