package process

import (
	"os"
	"os/exec"

	"github.com/creack/pty"
)

// startWithPTY starts a command with a PTY of the given size.
// Returns the master end of the PTY.
func startWithPTY(cmd *exec.Cmd, cols, rows uint16) (*os.File, error) {
	size := &pty.Winsize{
		Rows: rows,
		Cols: cols,
	}
	return pty.StartWithSize(cmd, size)
}

// resizePTY resizes the PTY window.
func resizePTY(master *os.File, cols, rows uint16) error {
	return pty.Setsize(master, &pty.Winsize{
		Rows: rows,
		Cols: cols,
	})
}
