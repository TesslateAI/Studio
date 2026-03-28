package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/creack/pty"
	"github.com/gorilla/websocket"
)

// Channel IDs for the multiplexed WebSocket protocol.
// Mirrors the Kubernetes remotecommand SPDY channel convention.
const (
	chanStdin  byte = 0
	chanStdout byte = 1
	chanStderr byte = 2
	chanStatus byte = 3
	chanResize byte = 4
)

// runStatus is the JSON payload sent on the status channel when the process exits.
type runStatus struct {
	ExitCode int `json:"exit_code"`
}

// runResize is the JSON payload received on the resize channel.
type runResize struct {
	Width  int `json:"width"`
	Height int `json:"height"`
}

// handleRun handles GET /v1/run.
//
// Query parameters:
//   - cmd (required): shell command to execute
//   - dir (optional): working directory (default "/app")
//   - tty (optional): "true" (default) or "false"
//   - cols, rows (optional): initial terminal size (default 120x30)
//
// Upgrades to WebSocket and bridges process I/O using channel-multiplexed
// binary frames. One connection = one process lifecycle. Disconnect kills
// the process.
func (s *Server) handleRun(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()

	cmdStr := q.Get("cmd")
	if cmdStr == "" {
		writeError(w, http.StatusBadRequest, "cmd query parameter is required")
		return
	}

	dir := q.Get("dir")
	if dir == "" {
		dir = "/app"
	}

	useTTY := q.Get("tty") != "false"

	cols, rows := 120, 30
	if v, err := strconv.Atoi(q.Get("cols")); err == nil && v > 0 {
		cols = v
	}
	if v, err := strconv.Atoi(q.Get("rows")); err == nil && v > 0 {
		rows = v
	}

	conn, err := wsUpgrader.Upgrade(w, r, nil)
	if err != nil {
		slog.Error("run: websocket upgrade failed", "error", err)
		return
	}

	slog.Info("run: session started", "cmd", cmdStr, "dir", dir, "tty", useTTY)

	if useTTY {
		s.runWithTTY(conn, cmdStr, dir, cols, rows)
	} else {
		s.runWithPipes(conn, cmdStr, dir)
	}
}

// runWithTTY starts a process in a PTY and bridges it to the WebSocket.
// stdout+stderr are merged through the PTY on channel 1.
//
// Uses Setsid+Setctty (not Setpgid) so the shell becomes the session leader
// and the PTY becomes the controlling terminal. This enables job control
// (Ctrl+Z, bg, fg) and avoids the "can't access tty" warning. Setsid is safe
// here because the run endpoint owns the full lifecycle — on disconnect we
// SIGKILL the entire process group.
func (s *Server) runWithTTY(conn *websocket.Conn, command, dir string, cols, rows int) {
	cmd := exec.Command("/bin/sh", "-c", command)
	cmd.Dir = dir
	cmd.Env = os.Environ()
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true, Setctty: true, Ctty: 1}

	// Hold the tracked lock across start+register to prevent the zombie
	// reaper from collecting the exit status before TrackPID is called.
	s.manager.LockTracked()
	master, err := pty.StartWithAttrs(cmd, &pty.Winsize{
		Cols: uint16(cols),
		Rows: uint16(rows),
	}, cmd.SysProcAttr)
	if err != nil {
		s.manager.UnlockTracked()
		slog.Error("run: pty start failed", "error", err)
		writeStatusAndClose(conn, -1)
		return
	}
	pid := cmd.Process.Pid
	s.manager.TrackPIDLocked(pid)
	s.manager.UnlockTracked()
	defer s.manager.UntrackPID(pid)
	slog.Info("run: process started (tty)", "pid", pid)

	var wsMu sync.Mutex
	exitCh := make(chan struct{})
	var exitCode int

	// Output: PTY master -> channel 1 frames.
	outputDone := make(chan struct{})
	go func() {
		defer close(outputDone)
		buf := make([]byte, 32*1024)
		for {
			n, readErr := master.Read(buf)
			if n > 0 {
				frame := make([]byte, 1+n)
				frame[0] = chanStdout
				copy(frame[1:], buf[:n])
				wsMu.Lock()
				werr := conn.WriteMessage(websocket.BinaryMessage, frame)
				wsMu.Unlock()
				if werr != nil {
					return
				}
			}
			if readErr != nil {
				return
			}
		}
	}()

	// Exit watcher: reaps the process and records the exit code.
	go func() {
		exitCode = s.awaitExit(cmd)
		close(exitCh)
	}()

	// Input: WS -> PTY stdin (channel 0) + resize (channel 4).
	disconnectCh := make(chan struct{})
	go func() {
		defer close(disconnectCh)
		for {
			_, data, readErr := conn.ReadMessage()
			if readErr != nil {
				return
			}
			if len(data) < 1 {
				continue
			}
			switch data[0] {
			case chanStdin:
				if _, werr := master.Write(data[1:]); werr != nil {
					slog.Debug("run: pty stdin write error", "error", werr)
					return
				}
			case chanResize:
				var rm runResize
				if json.Unmarshal(data[1:], &rm) == nil && rm.Width > 0 && rm.Height > 0 {
					_ = pty.Setsize(master, &pty.Winsize{
						Cols: uint16(rm.Width),
						Rows: uint16(rm.Height),
					})
				}
			}
		}
	}()

	// Block until process exits or client disconnects.
	select {
	case <-exitCh:
		// Process exited. Close PTY to flush output goroutine, then send status.
		_ = master.Close()
		<-outputDone

		wsMu.Lock()
		writeRunStatus(conn, exitCode)
		wsMu.Unlock()
		// Wait for the client to read the status frame and disconnect.
		// The input reader goroutine owns ReadMessage — it closes
		// disconnectCh when the client sends its close or disconnects.
		select {
		case <-disconnectCh:
		case <-time.After(5 * time.Second):
		}
		// Suppress the close frame that conn.Close() would otherwise send.
		// If the server sends a close frame alongside the status frame,
		// the client's WebSocket library may process the close before
		// delivering the status to the application (internal reader race).
		conn.UnderlyingConn().Close()
		// Kill background jobs that outlived the shell (job control creates
		// separate process groups within the session).
		killSession(pid)

		slog.Info("run: session ended (process exit)", "pid", pid, "exit_code", exitCode)

	case <-disconnectCh:
		// Client gone. Kill entire session and clean up.
		slog.Info("run: client disconnected, killing session", "pid", pid)
		killSession(pid)
		_ = master.Close()
		<-exitCh
		<-outputDone
		conn.Close()
	}
}

// runWithPipes starts a process with separate stdin/stdout/stderr pipes
// and bridges them to the WebSocket on channels 0/1/2.
func (s *Server) runWithPipes(conn *websocket.Conn, command, dir string) {
	cmd := exec.Command("/bin/sh", "-c", command)
	cmd.Dir = dir
	cmd.Env = os.Environ()
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	stdinPipe, err := cmd.StdinPipe()
	if err != nil {
		slog.Error("run: stdin pipe", "error", err)
		writeStatusAndClose(conn, -1)
		return
	}
	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		slog.Error("run: stdout pipe", "error", err)
		writeStatusAndClose(conn, -1)
		return
	}
	stderrPipe, err := cmd.StderrPipe()
	if err != nil {
		slog.Error("run: stderr pipe", "error", err)
		writeStatusAndClose(conn, -1)
		return
	}

	s.manager.LockTracked()
	if err := cmd.Start(); err != nil {
		s.manager.UnlockTracked()
		slog.Error("run: process start failed", "error", err)
		writeStatusAndClose(conn, -1)
		return
	}
	pid := cmd.Process.Pid
	s.manager.TrackPIDLocked(pid)
	s.manager.UnlockTracked()
	defer s.manager.UntrackPID(pid)
	slog.Info("run: process started (pipes)", "pid", pid)

	var wsMu sync.Mutex
	exitCh := make(chan struct{})
	var exitCode int

	// stdout -> channel 1
	stdoutDone := make(chan struct{})
	go func() {
		defer close(stdoutDone)
		pipeToChannel(conn, &wsMu, stdoutPipe, chanStdout)
	}()

	// stderr -> channel 2
	stderrDone := make(chan struct{})
	go func() {
		defer close(stderrDone)
		pipeToChannel(conn, &wsMu, stderrPipe, chanStderr)
	}()

	// Exit watcher.
	go func() {
		exitCode = s.awaitExit(cmd)
		close(exitCh)
	}()

	// WS channel 0 -> stdin
	disconnectCh := make(chan struct{})
	go func() {
		defer close(disconnectCh)
		defer stdinPipe.Close()
		for {
			_, data, readErr := conn.ReadMessage()
			if readErr != nil {
				return
			}
			if len(data) > 1 && data[0] == chanStdin {
				if _, werr := stdinPipe.Write(data[1:]); werr != nil {
					return
				}
			}
		}
	}()

	select {
	case <-exitCh:
		// Wait for output to drain.
		<-stdoutDone
		<-stderrDone

		wsMu.Lock()
		writeRunStatus(conn, exitCode)
		wsMu.Unlock()
		select {
		case <-disconnectCh:
		case <-time.After(5 * time.Second):
		}
		conn.UnderlyingConn().Close()

		slog.Info("run: session ended (process exit)", "pid", pid, "exit_code", exitCode)

	case <-disconnectCh:
		slog.Info("run: client disconnected, killing process", "pid", pid)
		_ = syscall.Kill(-pid, syscall.SIGKILL)
		waitGone(pid)
		<-exitCh
		<-stdoutDone
		<-stderrDone
		conn.Close()
	}

	_ = syscall.Kill(-pid, syscall.SIGKILL)
}

// pipeToChannel reads from r and sends channel-prefixed binary frames.
func pipeToChannel(conn *websocket.Conn, mu *sync.Mutex, r io.Reader, ch byte) {
	buf := make([]byte, 32*1024)
	for {
		n, err := r.Read(buf)
		if n > 0 {
			frame := make([]byte, 1+n)
			frame[0] = ch
			copy(frame[1:], buf[:n])
			mu.Lock()
			werr := conn.WriteMessage(websocket.BinaryMessage, frame)
			mu.Unlock()
			if werr != nil {
				return
			}
		}
		if err != nil {
			return
		}
	}
}

// killSession sends SIGKILL to every process whose session ID matches sid,
// then waits for all of them to exit. This is synchronous — when it returns,
// every session member is dead and reaped. No sleep or polling delay needed
// by the caller.
func killSession(sid int) {
	pids := findSessionPIDs(sid)
	if len(pids) == 0 {
		return
	}

	for _, pid := range pids {
		_ = syscall.Kill(pid, syscall.SIGKILL)
	}

	// Wait for all killed processes to disappear from /proc.
	// SIGKILL is unblockable — the kernel guarantees termination.
	// We just need to wait for tsinit (PID 1) to reap the zombies,
	// which the supervisor's SIGCHLD handler does automatically.
	for _, pid := range pids {
		waitGone(pid)
	}

	slog.Debug("killSession: all processes reaped", "sid", sid, "count", len(pids))
}

// findSessionPIDs returns all PIDs whose session ID matches sid.
func findSessionPIDs(sid int) []int {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return nil
	}
	var pids []int
	for _, e := range entries {
		pid, err := strconv.Atoi(e.Name())
		if err != nil || pid <= 1 {
			continue
		}
		data, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
		if err != nil {
			continue
		}
		// /proc/[pid]/stat: "pid (comm) state ppid pgrp session ..."
		// comm can contain spaces/parens, so find the last ')' first.
		idx := bytes.LastIndexByte(data, ')')
		if idx < 0 || idx+2 >= len(data) {
			continue
		}
		fields := strings.Fields(string(data[idx+2:]))
		// fields: [0]=state [1]=ppid [2]=pgrp [3]=session
		if len(fields) >= 4 {
			if procSID, err := strconv.Atoi(fields[3]); err == nil && procSID == sid {
				pids = append(pids, pid)
			}
		}
	}
	return pids
}

// waitGone blocks until /proc/[pid] no longer exists, meaning the process
// has been fully reaped. SIGKILL is unblockable so this completes as soon
// as the supervisor's SIGCHLD handler reaps the zombie (typically <1ms).
func waitGone(pid int) {
	// Wait4 blocks until the child is reaped or returns ECHILD if already
	// reaped by the supervisor's reapZombies. Either way, the process is dead.
	var ws syscall.WaitStatus
	_, _ = syscall.Wait4(pid, &ws, 0, nil)
}

// awaitExit waits for cmd to finish and returns the exit code.
// If the zombie reaper (Wait4(-1)) collected the exit status before
// cmd.Wait(), we retrieve it from the manager's stolen exit map.
func (s *Server) awaitExit(cmd *exec.Cmd) int {
	err := cmd.Wait()
	if err == nil {
		return 0
	}
	if exitErr, ok := err.(*exec.ExitError); ok {
		return exitErr.ExitCode()
	}
	// cmd.Wait got ECHILD — the zombie reaper collected the status via
	// Wait4(-1). Block on the per-PID channel until the reaper saves it.
	pid := cmd.Process.Pid
	if code, ok := s.manager.WaitStolenExit(pid); ok {
		return code
	}
	return -1
}

// writeRunStatus sends a channel 3 frame containing the exit code as JSON.
func writeRunStatus(conn *websocket.Conn, exitCode int) {
	payload, _ := json.Marshal(runStatus{ExitCode: exitCode})
	frame := make([]byte, 1+len(payload))
	frame[0] = chanStatus
	copy(frame[1:], payload)
	_ = conn.WriteMessage(websocket.BinaryMessage, frame)
}

// writeStatusAndClose sends a status frame and closes the connection.
// Used when the process fails to start (no active reader goroutine).
func writeStatusAndClose(conn *websocket.Conn, exitCode int) {
	writeRunStatus(conn, exitCode)
	drainAndClose(conn)
}

// drainAndClose waits for the client to initiate the WebSocket close
// handshake (up to 5s), then closes the connection. This ensures the
// client has time to read the status frame before the connection drops.
// Sending a server-initiated close frame back-to-back with a data frame
// causes a race in some WebSocket libraries where the close is processed
// before the data frame is delivered to the application.
func drainAndClose(conn *websocket.Conn) {
	conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	for {
		if _, _, err := conn.ReadMessage(); err != nil {
			break
		}
	}
	conn.Close()
}
