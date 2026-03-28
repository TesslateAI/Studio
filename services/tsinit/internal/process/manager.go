package process

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"sync"
	"time"
)

// HealthStatus is the aggregate health of the process manager and all managed processes.
type HealthStatus struct {
	Status    string                   `json:"status"`
	Pid       int                      `json:"pid"`
	UptimeSec float64                  `json:"uptime_sec"`
	Version   string                   `json:"version"`
	Processes map[string]ProcessStatus `json:"processes"`
}

// ProcessManager is a thread-safe registry of all managed processes.
type ProcessManager struct {
	processes   map[string]*Process
	mu          sync.RWMutex
	stdout      io.Writer
	startedAt   time.Time
	version     string
	bufferLines int

	// trackedPIDs holds PIDs of short-lived processes (e.g. /v1/run)
	// that are NOT fully managed but whose exit status must be preserved
	// when the supervisor's Wait4(-1) zombie reaper collects them.
	trackedMu   sync.RWMutex
	trackedPIDs map[int]struct{}
	// stolenExits stores exit codes for tracked PIDs that were reaped
	// by Wait4(-1) before cmd.Wait() could collect them.
	stolenExits map[int]int
	// stolenReady is closed per-PID when SaveStolenExit writes the code,
	// allowing awaitExit to block on it instead of polling.
	stolenReady map[int]chan struct{}
}

// NewProcessManager creates a new process manager.
// bufferLines sets the per-process ring buffer size (0 = default).
func NewProcessManager(stdout io.Writer, version string, bufferLines int) *ProcessManager {
	return &ProcessManager{
		processes:   make(map[string]*Process),
		stdout:      stdout,
		startedAt:   time.Now(),
		version:     version,
		bufferLines: bufferLines,
		trackedPIDs: make(map[int]struct{}),
		stolenExits: make(map[int]int),
		stolenReady: make(map[int]chan struct{}),
	}
}

// Start validates the config, creates a new process, starts it, and registers it.
// It also starts a background goroutine that watches for process exit and handles
// ephemeral cleanup.
func (m *ProcessManager) Start(config ProcessConfig) (*ProcessStatus, error) {
	if config.Name == "" {
		return nil, fmt.Errorf("process name is required")
	}
	if config.Cmd == "" {
		return nil, fmt.Errorf("process command is required")
	}

	// Hold the lock across check → create → register to prevent TOCTOU
	// races where two concurrent Start("same-name") calls both pass the
	// existence check and leak a process.
	m.mu.Lock()
	if _, exists := m.processes[config.Name]; exists {
		m.mu.Unlock()
		return nil, fmt.Errorf("process %q already exists", config.Name)
	}

	proc := NewProcess(config, m.stdout, m.bufferLines)
	if err := proc.Start(); err != nil {
		m.mu.Unlock()
		return nil, fmt.Errorf("failed to start process %q: %w", config.Name, err)
	}

	m.processes[config.Name] = proc
	m.mu.Unlock()

	slog.Info("process started", "name", config.Name, "cmd", config.Cmd, "pid", proc.Status().Pid)

	// Background watcher for exit and ephemeral cleanup.
	go func() {
		<-proc.Wait()
		status := proc.Status()
		slog.Info("process exited",
			"name", config.Name,
			"exit_code", status.ExitCode,
			"ephemeral", config.Ephemeral,
		)
		if config.Ephemeral && status.State == StateExited {
			m.mu.Lock()
			delete(m.processes, config.Name)
			m.mu.Unlock()
			slog.Info("ephemeral process removed from registry", "name", config.Name)
		}
	}()

	s := proc.Status()
	return &s, nil
}

// Stop stops a process by name and removes it from the registry.
func (m *ProcessManager) Stop(name string, gracePeriod time.Duration) error {
	m.mu.Lock()
	proc, exists := m.processes[name]
	if !exists {
		m.mu.Unlock()
		return fmt.Errorf("process %q not found", name)
	}
	delete(m.processes, name)
	m.mu.Unlock()

	slog.Info("stopping process", "name", name, "grace_period", gracePeriod)
	return proc.Stop(gracePeriod)
}

// Restart stops a process and starts a new one with the same config.
func (m *ProcessManager) Restart(name string) (*ProcessStatus, error) {
	m.mu.Lock()
	proc, exists := m.processes[name]
	if !exists {
		m.mu.Unlock()
		return nil, fmt.Errorf("process %q not found", name)
	}
	// Capture config before stopping so we can re-use it.
	config := proc.config
	delete(m.processes, name)
	m.mu.Unlock()

	slog.Info("restarting process", "name", name)
	_ = proc.Stop(5 * time.Second)

	return m.Start(config)
}

// Get returns a process by name. Thread-safe.
func (m *ProcessManager) Get(name string) (*Process, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	p, ok := m.processes[name]
	return p, ok
}

// List returns the status of all managed processes.
func (m *ProcessManager) List() []ProcessStatus {
	m.mu.RLock()
	defer m.mu.RUnlock()

	statuses := make([]ProcessStatus, 0, len(m.processes))
	for _, p := range m.processes {
		statuses = append(statuses, p.Status())
	}
	return statuses
}

// Health returns the aggregate health status of the manager and all processes.
// "healthy" if all non-ephemeral processes are running, "degraded" if any are
// exited or stopped.
func (m *ProcessManager) Health() HealthStatus {
	m.mu.RLock()
	defer m.mu.RUnlock()

	procs := make(map[string]ProcessStatus, len(m.processes))
	status := "healthy"

	for name, p := range m.processes {
		ps := p.Status()
		procs[name] = ps

		// Only consider non-ephemeral processes for health.
		if !ps.Ephemeral {
			switch ps.State {
			case StateExited, StateStopped:
				status = "degraded"
			}
		}
	}

	return HealthStatus{
		Status:    status,
		Pid:       os.Getpid(),
		UptimeSec: time.Since(m.startedAt).Seconds(),
		Version:   m.version,
		Processes: procs,
	}
}

// StopAll stops all managed processes in parallel with the given grace period.
func (m *ProcessManager) StopAll(gracePeriod time.Duration) {
	m.mu.Lock()
	// Snapshot the current set and clear the map.
	procs := make(map[string]*Process, len(m.processes))
	for name, p := range m.processes {
		procs[name] = p
	}
	m.processes = make(map[string]*Process)
	m.mu.Unlock()

	if len(procs) == 0 {
		return
	}

	slog.Info("stopping all processes", "count", len(procs), "grace_period", gracePeriod)

	var wg sync.WaitGroup
	for name, p := range procs {
		wg.Add(1)
		go func(n string, proc *Process) {
			defer wg.Done()
			if err := proc.Stop(gracePeriod); err != nil {
				slog.Warn("error stopping process during shutdown", "name", n, "error", err)
			}
		}(name, p)
	}
	wg.Wait()

	slog.Info("all processes stopped")
}

// LockTracked acquires the tracked PID write lock. Used to atomically
// start a process and register its PID before the reaper can run.
func (m *ProcessManager) LockTracked()   { m.trackedMu.Lock() }
func (m *ProcessManager) UnlockTracked() { m.trackedMu.Unlock() }

// TrackPIDLocked registers a PID while the caller already holds LockTracked.
func (m *ProcessManager) TrackPIDLocked(pid int) {
	m.trackedPIDs[pid] = struct{}{}
	m.stolenReady[pid] = make(chan struct{})
}

// TrackPID registers a PID so the zombie reaper won't steal its exit status.
// Call UntrackPID when the process has been waited on.
func (m *ProcessManager) TrackPID(pid int) {
	m.trackedMu.Lock()
	m.trackedPIDs[pid] = struct{}{}
	m.trackedMu.Unlock()
}

// UntrackPID removes a PID from the tracked set and cleans up any stolen exit.
func (m *ProcessManager) UntrackPID(pid int) {
	m.trackedMu.Lock()
	delete(m.trackedPIDs, pid)
	delete(m.stolenExits, pid)
	delete(m.stolenReady, pid)
	m.trackedMu.Unlock()
}

// SaveStolenExit records an exit code for a tracked PID whose status was
// consumed by the zombie reaper's Wait4(-1). Closes the per-PID ready
// channel so WaitStolenExit unblocks immediately.
func (m *ProcessManager) SaveStolenExit(pid int, exitCode int) {
	m.trackedMu.Lock()
	m.stolenExits[pid] = exitCode
	if ch, ok := m.stolenReady[pid]; ok {
		close(ch)
	}
	m.trackedMu.Unlock()
}

// StolenExit returns the exit code saved by the zombie reaper for a tracked
// PID, and whether one was found.
func (m *ProcessManager) StolenExit(pid int) (int, bool) {
	m.trackedMu.RLock()
	code, ok := m.stolenExits[pid]
	m.trackedMu.RUnlock()
	return code, ok
}

// WaitStolenExit blocks until the reaper saves a stolen exit code for pid,
// then returns it. Returns (-1, false) if the channel doesn't exist (pid
// was not tracked).
func (m *ProcessManager) WaitStolenExit(pid int) (int, bool) {
	m.trackedMu.RLock()
	ch, ok := m.stolenReady[pid]
	m.trackedMu.RUnlock()
	if !ok {
		return -1, false
	}
	<-ch // blocks until SaveStolenExit closes it
	return m.StolenExit(pid)
}

// IsTracked returns true if the PID was registered via TrackPID (/v1/run).
func (m *ProcessManager) IsTracked(pid int) bool {
	m.trackedMu.RLock()
	_, tracked := m.trackedPIDs[pid]
	m.trackedMu.RUnlock()
	return tracked
}

// IsManaged returns true if the given PID belongs to a supervisor-managed
// process (started via ProcessManager.Start). Does NOT check tracked PIDs.
func (m *ProcessManager) IsManaged(pid int) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, p := range m.processes {
		if p.Status().Pid == pid {
			return true
		}
	}
	return false
}

// HandleOrphanExit is called by the supervisor when an unknown child process
// exits (zombie reaping for processes not managed by this manager).
func (m *ProcessManager) HandleOrphanExit(pid int, status int) {
	slog.Debug("reaped orphan child process", "pid", pid, "exit_status", status)
}
