package process

import (
	"os"
	"os/exec"

	"github.com/creack/pty"
)

// startWithPTY starts a command with a PTY of the given size.
// Returns the master end of the PTY.
//
// Uses pty.StartWithAttrs (not StartWithSize) so we control SysProcAttr
// directly. StartWithSize forces Setsid+Setctty which creates a new session
// — when the session leader (shell) exits, the kernel sends SIGHUP to all
// processes in the session, killing fork-and-exit children (bun → next-server).
// By using Setpgid instead, we get a process group for group-kill without
// the session-leader-death SIGHUP.
func startWithPTY(cmd *exec.Cmd, cols, rows uint16) (*os.File, error) {
	size := &pty.Winsize{
		Rows: rows,
		Cols: cols,
	}
	// cmd.SysProcAttr is set by the caller (Start) with Setpgid: true.
	// We pass it through to StartWithAttrs which won't override it.
	return pty.StartWithAttrs(cmd, size, cmd.SysProcAttr)
}

// resizePTY resizes the PTY window.
func resizePTY(master *os.File, cols, rows uint16) error {
	return pty.Setsize(master, &pty.Winsize{
		Rows: rows,
		Cols: cols,
	})
}
