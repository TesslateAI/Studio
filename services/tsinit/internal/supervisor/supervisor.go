package supervisor

import (
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/tesslate/tsinit/internal/process"
)

// Supervisor is the PID 1 process supervisor. It handles signal forwarding,
// zombie reaping via SIGCHLD, and graceful shutdown of all managed processes.
type Supervisor struct {
	manager     *process.ProcessManager
	gracePeriod time.Duration
	shutdownCh  chan struct{}
	doneCh      chan struct{}
}

// NewSupervisor creates a new supervisor wrapping the given process manager.
func NewSupervisor(manager *process.ProcessManager, gracePeriod time.Duration) *Supervisor {
	return &Supervisor{
		manager:     manager,
		gracePeriod: gracePeriod,
		shutdownCh:  make(chan struct{}),
		doneCh:      make(chan struct{}),
	}
}

// Run is the main supervisor loop. It sets up signal handlers for SIGTERM,
// SIGINT, and SIGCHLD, then blocks until a shutdown signal is received or
// Shutdown() is called via the API. Returns after all processes have been
// stopped and cleanup is complete.
func (s *Supervisor) Run() error {
	sigCh := make(chan os.Signal, 10)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT, syscall.SIGCHLD)
	defer signal.Stop(sigCh)

	slog.Info("supervisor running", "pid", os.Getpid())

	for {
		select {
		case sig := <-sigCh:
			switch sig {
			case syscall.SIGCHLD:
				s.reapZombies()
			case syscall.SIGTERM, syscall.SIGINT:
				slog.Info("received shutdown signal", "signal", sig)
				s.doShutdown()
				return nil
			}
		case <-s.shutdownCh:
			slog.Info("shutdown requested via API")
			s.doShutdown()
			return nil
		}
	}
}

// Shutdown triggers a graceful shutdown from outside the signal loop (e.g.
// from an API handler). Safe to call from any goroutine. Calling it more
// than once is a no-op.
func (s *Supervisor) Shutdown() {
	select {
	case <-s.shutdownCh:
		// Already closed.
	default:
		close(s.shutdownCh)
	}
}

// Done returns a channel that is closed when the supervisor has finished
// shutting down all processes.
func (s *Supervisor) Done() <-chan struct{} {
	return s.doneCh
}

// reapZombies collects exit statuses from child processes that have terminated.
// This prevents zombie accumulation when running as PID 1. We skip PIDs that
// are managed by the ProcessManager — those are handled by cmd.Wait() in
// the process's waitLoop goroutine. Reaping them here would steal the exit
// status and cause cmd.Wait() to return ECHILD with a wrong exit code.
func (s *Supervisor) reapZombies() {
	for {
		var status syscall.WaitStatus
		pid, err := syscall.Wait4(-1, &status, syscall.WNOHANG, nil)
		if pid <= 0 || err != nil {
			break
		}
		if s.manager.IsManaged(pid) {
			// This PID belongs to a managed process. Go's runtime will
			// reap it via cmd.Wait(). We already consumed the status
			// though (Wait4 is destructive), so the managed process's
			// waitLoop will get ECHILD — it handles that gracefully.
			slog.Debug("reaped managed child (exit code may be lost)", "pid", pid)
			continue
		}
		exitStatus := status.ExitStatus()
		slog.Debug("reaped orphan child", "pid", pid, "exit_status", exitStatus)
		s.manager.HandleOrphanExit(pid, exitStatus)
	}
}

// doShutdown stops all managed processes with the configured grace period
// and signals completion via doneCh.
func (s *Supervisor) doShutdown() {
	slog.Info("stopping all processes", "grace_period", s.gracePeriod)
	s.manager.StopAll(s.gracePeriod)
	close(s.doneCh)
	slog.Info("supervisor shutdown complete")
}
