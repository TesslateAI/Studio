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

// IsManaged returns true if the given PID belongs to a currently managed process.
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
