package process

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"sync"
	"syscall"
	"time"
)

// ProcessState represents the lifecycle state of a managed process.
type ProcessState string

const (
	StateStarting ProcessState = "starting"
	StateRunning  ProcessState = "running"
	StateExited   ProcessState = "exited"
	StateStopped  ProcessState = "stopped"
)

// RestartPolicy controls automatic restart behaviour after a process exits.
type RestartPolicy string

const (
	RestartNever     RestartPolicy = "never"
	RestartOnFailure RestartPolicy = "on-failure"
	RestartAlways    RestartPolicy = "always"
)

// ProcessConfig describes how to launch and manage a process.
type ProcessConfig struct {
	Name      string        `json:"name"`
	Cmd       string        `json:"cmd"`
	Dir       string        `json:"dir,omitempty"`
	Restart   RestartPolicy `json:"restart,omitempty"`
	TeeStdout bool          `json:"tee_stdout,omitempty"`
	Ephemeral bool          `json:"ephemeral,omitempty"`
	Env       []string      `json:"env,omitempty"`
	Cols      int           `json:"cols,omitempty"`
	Rows      int           `json:"rows,omitempty"`
}

// ProcessStatus is a point-in-time snapshot of process state, safe to serialise.
type ProcessStatus struct {
	Name      string        `json:"name"`
	State     ProcessState  `json:"state"`
	Pid       int           `json:"pid"`
	ExitCode  int           `json:"exit_code"`
	Restarts  int           `json:"restarts"`
	Cmd       string        `json:"cmd"`
	Dir       string        `json:"dir"`
	Restart   RestartPolicy `json:"restart_policy"`
	TeeStdout bool          `json:"tee_stdout"`
	Ephemeral bool          `json:"ephemeral"`
	StartedAt *time.Time    `json:"started_at,omitempty"`
	ExitedAt  *time.Time    `json:"exit_at,omitempty"`
	UptimeSec float64       `json:"uptime_sec"`
}

// Process manages a single supervised process with PTY, output capture, and
// optional restart logic.
type Process struct {
	config    ProcessConfig
	state     ProcessState
	pid       int
	exitCode  int
	restarts  int
	startedAt time.Time
	exitedAt  time.Time

	cmd       *exec.Cmd
	ptyMaster *os.File
	output    *RingBuffer
	stdout    io.Writer // container stdout for tee

	mu     sync.RWMutex
	exitCh chan struct{} // closed when process exits
	stopCh chan struct{} // signal to stop restart loop

	streamMu sync.RWMutex
	streams  map[string]chan []byte
}

const (
	defaultCols            = 120
	defaultRows            = 30
	DefaultOutputBufferLen = 10000
	streamChanSize         = 256
)

// NewProcess creates a Process from the given config. It does not start it;
// call Start() to launch. bufferLines sets the ring buffer capacity (0 = default).
//
// config.Dir semantics:
//   - non-empty path → exec.Cmd.Dir = that path
//   - empty string   → inherit cwd from tsinit's own process (which kubelet
//     seeds with the image's WORKDIR). This is REQUIRED for image-based
//     Tesslate Apps where the runtime contract is "image is self-contained;
//     the orchestrator must not override the image's WORKDIR" — passing
//     ``--dir /`` would silently break apps whose source lives at e.g.
//     /app/server.py because exec.Cmd would chdir to / first.
func NewProcess(config ProcessConfig, stdout io.Writer, bufferLines int) *Process {
	if config.Cols <= 0 {
		config.Cols = defaultCols
	}
	if config.Rows <= 0 {
		config.Rows = defaultRows
	}
	if config.Restart == "" {
		config.Restart = RestartNever
	}
	if bufferLines <= 0 {
		bufferLines = DefaultOutputBufferLen
	}

	return &Process{
		config:  config,
		state:   StateStopped,
		output:  NewRingBuffer(bufferLines),
		stdout:  stdout,
		exitCh:  make(chan struct{}),
		stopCh:  make(chan struct{}),
		streams: make(map[string]chan []byte),
	}
}

// Start launches the process in a new PTY with its own process group.
func (p *Process) Start() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.state == StateRunning || p.state == StateStarting {
		return fmt.Errorf("process %q is already running", p.config.Name)
	}

	p.state = StateStarting

	cmd := buildCmd(p.config.Cmd, p.config.Dir, p.config.Env)

	// Create a new process group (Setpgid) so we can kill the whole group
	// on Stop(). We intentionally do NOT use Setsid here: Setsid creates a
	// new session, making the child the session leader. When a session leader
	// exits, the kernel sends SIGHUP to all processes in the session — which
	// kills fork-and-exit children (e.g. bun run dev → next-server) before
	// tsinit can track them. Setpgid gives us group-kill without the
	// session-leader-death SIGHUP.
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Setpgid: true,
	}

	master, err := startWithPTY(cmd, uint16(p.config.Cols), uint16(p.config.Rows))
	if err != nil {
		p.state = StateExited
		return fmt.Errorf("start process %q: %w", p.config.Name, err)
	}

	p.cmd = cmd
	p.ptyMaster = master
	p.pid = cmd.Process.Pid
	p.exitCode = 0
	p.startedAt = time.Now()
	p.exitedAt = time.Time{}
	p.state = StateRunning
	p.exitCh = make(chan struct{})

	slog.Info("process started",
		"name", p.config.Name,
		"pid", p.pid,
		"cmd", p.config.Cmd,
		"dir", p.config.Dir,
	)

	go p.outputLoop()
	go p.waitLoop()

	return nil
}

// Stop sends SIGTERM to the process group, waits up to gracePeriod, then
// sends SIGKILL if the process has not exited.
func (p *Process) Stop(gracePeriod time.Duration) error {
	p.mu.Lock()

	if p.state != StateRunning && p.state != StateStarting {
		p.mu.Unlock()
		return nil
	}

	// Signal the restart loop to stop.
	select {
	case <-p.stopCh:
		// Already closed.
	default:
		close(p.stopCh)
	}

	pid := p.pid
	exitCh := p.exitCh
	p.mu.Unlock()

	slog.Info("stopping process", "name", p.config.Name, "pid", pid, "grace", gracePeriod)

	// SIGTERM the entire process group.
	if err := syscall.Kill(-pid, syscall.SIGTERM); err != nil {
		slog.Warn("sigterm failed", "name", p.config.Name, "pid", pid, "err", err)
	}

	select {
	case <-exitCh:
		// Process exited within grace period.
	case <-time.After(gracePeriod):
		slog.Warn("grace period expired, sending SIGKILL", "name", p.config.Name, "pid", pid)
		if err := syscall.Kill(-pid, syscall.SIGKILL); err != nil {
			slog.Warn("sigkill failed", "name", p.config.Name, "pid", pid, "err", err)
		}
		<-exitCh
	}

	p.mu.Lock()
	p.state = StateStopped
	p.mu.Unlock()

	slog.Info("process stopped", "name", p.config.Name, "pid", pid)
	return nil
}

// Status returns a point-in-time snapshot of the process state.
func (p *Process) Status() ProcessStatus {
	p.mu.RLock()
	defer p.mu.RUnlock()

	st := ProcessStatus{
		Name:      p.config.Name,
		State:     p.state,
		Pid:       p.pid,
		ExitCode:  p.exitCode,
		Restarts:  p.restarts,
		Cmd:       p.config.Cmd,
		Dir:       p.config.Dir,
		Restart:   p.config.Restart,
		TeeStdout: p.config.TeeStdout,
		Ephemeral: p.config.Ephemeral,
	}

	if !p.startedAt.IsZero() {
		t := p.startedAt
		st.StartedAt = &t
	}
	if !p.exitedAt.IsZero() {
		t := p.exitedAt
		st.ExitedAt = &t
	}

	if p.state == StateRunning && !p.startedAt.IsZero() {
		st.UptimeSec = time.Since(p.startedAt).Seconds()
	}

	return st
}

// WriteInput sends raw bytes to the process's PTY (i.e. its stdin).
func (p *Process) WriteInput(data []byte) (int, error) {
	p.mu.RLock()
	master := p.ptyMaster
	state := p.state
	p.mu.RUnlock()

	if state != StateRunning || master == nil {
		return 0, fmt.Errorf("process %q is not running", p.config.Name)
	}
	return master.Write(data)
}

// SendSignal sends a signal to the entire process group.
func (p *Process) SendSignal(sig syscall.Signal) error {
	p.mu.RLock()
	pid := p.pid
	state := p.state
	p.mu.RUnlock()

	if state != StateRunning {
		return fmt.Errorf("process %q is not running", p.config.Name)
	}
	return syscall.Kill(-pid, sig)
}

// Output returns the last n lines of captured output.
func (p *Process) Output(lines int) []string {
	return p.output.Lines(lines)
}

// Subscribe registers a channel that receives real-time output chunks.
// The caller must eventually call Unsubscribe to avoid leaks.
func (p *Process) Subscribe(id string) chan []byte {
	ch := make(chan []byte, streamChanSize)
	p.streamMu.Lock()
	p.streams[id] = ch
	p.streamMu.Unlock()
	return ch
}

// Unsubscribe removes a subscriber and closes its channel.
func (p *Process) Unsubscribe(id string) {
	p.streamMu.Lock()
	ch, ok := p.streams[id]
	if ok {
		delete(p.streams, id)
		close(ch)
	}
	p.streamMu.Unlock()
}

// Wait returns a channel that is closed when the process exits.
func (p *Process) Wait() <-chan struct{} {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.exitCh
}

// Resize changes the PTY window size.
func (p *Process) Resize(cols, rows int) error {
	p.mu.RLock()
	master := p.ptyMaster
	state := p.state
	p.mu.RUnlock()

	if state != StateRunning || master == nil {
		return fmt.Errorf("process %q is not running", p.config.Name)
	}
	return resizePTY(master, uint16(cols), uint16(rows))
}

// ---------- internal goroutines ----------

// outputLoop reads from the PTY master and distributes output to the ring
// buffer, optional tee, and any subscribers.
func (p *Process) outputLoop() {
	buf := make([]byte, 32*1024)
	name := p.config.Name

	for {
		n, err := p.ptyMaster.Read(buf)
		if n > 0 {
			chunk := make([]byte, n)
			copy(chunk, buf[:n])

			// Store in ring buffer.
			p.output.Write(chunk)

			// Optionally tee to container stdout with a per-line prefix.
			if p.config.TeeStdout && p.stdout != nil {
				p.teeOutput(name, chunk)
			}

			// Fan out to subscribers (non-blocking).
			p.streamMu.RLock()
			for _, ch := range p.streams {
				select {
				case ch <- chunk:
				default:
					// Slow subscriber — drop to avoid blocking.
				}
			}
			p.streamMu.RUnlock()
		}
		if err != nil {
			// PTY closed — process has exited or will exit momentarily.
			return
		}
	}
}

// teeOutput writes data to stdout, prepending "[name] " to each line.
func (p *Process) teeOutput(name string, data []byte) {
	prefix := []byte("[" + name + "] ")
	start := 0
	for i, b := range data {
		if b == '\n' {
			line := make([]byte, 0, len(prefix)+i-start+1)
			line = append(line, prefix...)
			line = append(line, data[start:i+1]...)
			_, _ = p.stdout.Write(line)
			start = i + 1
		}
	}
	// Trailing partial line (no newline).
	if start < len(data) {
		line := make([]byte, 0, len(prefix)+len(data)-start)
		line = append(line, prefix...)
		line = append(line, data[start:]...)
		_, _ = p.stdout.Write(line)
	}
}

// pgroupAlive checks whether any process in the process group is still running.
// Uses kill(2) with signal 0 which checks existence without sending a signal.
func pgroupAlive(pgid int) bool {
	return syscall.Kill(-pgid, 0) == nil
}

// waitLoop waits for the process to exit, records the exit code, and
// optionally triggers a restart.
//
// The tracked child is typically a shell (sh -c "...") that may fork a
// long-running workload (e.g. bun run dev → next-server). When the shell
// exits, we check whether the process group still has living members.
// If it does, the process is still "running" — we poll until the group
// is empty before declaring it exited. This handles fork-and-exit
// patterns (bun, npx, npm run) that spawn a child and then exit.
func (p *Process) waitLoop() {
	err := p.cmd.Wait()

	exitCode := 0
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			exitCode = exitErr.ExitCode()
		} else {
			// This can happen if the zombie reaper (Wait4(-1)) collected
			// the exit status before cmd.Wait() did. In that case we lose
			// the real exit code but the process is still dead.
			slog.Debug("cmd.Wait returned non-ExitError", "name", p.config.Name, "err", err)
			exitCode = -1
		}
	}

	p.mu.RLock()
	pid := p.pid
	name := p.config.Name
	state := p.state
	p.mu.RUnlock()

	// The direct child exited, but the process group (pgid == pid due to
	// Setsid) may still have living members (fork-and-exit pattern).
	// Poll until the group is empty before declaring the process dead.
	if state != StateStopped && pgroupAlive(pid) {
		slog.Info("direct child exited but process group still alive, tracking group",
			"name", name,
			"pid", pid,
			"child_exit_code", exitCode,
		)

		const pollInterval = 2 * time.Second
		ticker := time.NewTicker(pollInterval)
		defer ticker.Stop()

		for range ticker.C {
			// Check if Stop() was called while we're polling.
			p.mu.RLock()
			stopped := p.state == StateStopped
			p.mu.RUnlock()
			if stopped {
				return
			}

			if !pgroupAlive(pid) {
				slog.Info("process group empty, declaring exited",
					"name", name,
					"pid", pid,
				)
				break
			}
		}
	}

	p.mu.Lock()
	now := time.Now()
	p.exitedAt = now
	p.exitCode = exitCode

	// Close the PTY master if still open.
	if p.ptyMaster != nil {
		_ = p.ptyMaster.Close()
		p.ptyMaster = nil
	}

	// Only transition to exited if not already marked stopped (by Stop()).
	if p.state != StateStopped {
		p.state = StateExited
	}

	// Close exitCh to unblock waiters.
	select {
	case <-p.exitCh:
	default:
		close(p.exitCh)
	}

	policy := p.config.Restart
	state = p.state
	p.mu.Unlock()

	slog.Info("process exited",
		"name", name,
		"exit_code", exitCode,
		"ephemeral", p.config.Ephemeral,
	)

	// Decide whether to restart.
	shouldRestart := false
	switch policy {
	case RestartAlways:
		shouldRestart = state != StateStopped
	case RestartOnFailure:
		shouldRestart = state != StateStopped && exitCode != 0
	case RestartNever:
		// no-op
	}

	// Before restarting, kill any orphaned process group members
	// to avoid resource conflicts (e.g. EADDRINUSE).
	if shouldRestart {
		_ = syscall.Kill(-pid, syscall.SIGKILL)
		go p.restartLoop()
	}
}

// restartLoop implements exponential-backoff restarts: 1s, 2s, 4s, 8s, 16s,
// capped at 30s.
func (p *Process) restartLoop() {
	const (
		initialBackoff = 1 * time.Second
		maxBackoff     = 30 * time.Second
	)
	backoff := initialBackoff

	for {
		// Check if stop was requested.
		select {
		case <-p.stopCh:
			slog.Info("restart loop cancelled", "name", p.config.Name)
			return
		default:
		}

		slog.Info("restarting process",
			"name", p.config.Name,
			"backoff", backoff,
		)

		// Sleep with cancellation.
		timer := time.NewTimer(backoff)
		select {
		case <-p.stopCh:
			timer.Stop()
			slog.Info("restart loop cancelled during backoff", "name", p.config.Name)
			return
		case <-timer.C:
		}

		// Re-check stop under lock after the sleep. If Stop() closed
		// stopCh while the timer was running, we must not proceed.
		p.mu.Lock()
		select {
		case <-p.stopCh:
			p.mu.Unlock()
			slog.Info("restart loop cancelled after backoff", "name", p.config.Name)
			return
		default:
		}
		p.restarts++
		// Allocate fresh channels for the new lifecycle.
		p.stopCh = make(chan struct{})
		p.mu.Unlock()

		if err := p.Start(); err != nil {
			slog.Error("restart failed",
				"name", p.config.Name,
				"err", err,
			)
			// Double the backoff for next attempt.
			backoff *= 2
			if backoff > maxBackoff {
				backoff = maxBackoff
			}
			continue
		}

		// Successfully restarted.
		slog.Info("process restarted successfully", "name", p.config.Name)
		return
	}
}

// buildCmd constructs the exec.Cmd for a supervised process.
//
// Security note: the command string is intentionally passed to /bin/sh -c
// because process supervisor configs require shell features (pipes, redirects,
// env expansion). The command comes from ProcessConfig which is set by the
// container orchestrator — not from untrusted user HTTP input. The trust
// boundary is at the API layer that constructs ProcessConfig, not here.
func buildCmd(command, dir string, extraEnv []string) *exec.Cmd {
	args := []string{"-c", command}
	cmd := exec.Command("/bin/sh", args...)
	cmd.Dir = dir
	cmd.Env = buildEnv(extraEnv)
	return cmd
}

// buildEnv returns the environment for the child process. It inherits the
// current environment and appends any extra entries from config.
func buildEnv(extra []string) []string {
	env := os.Environ()
	if len(extra) > 0 {
		env = append(env, extra...)
	}
	return env
}
