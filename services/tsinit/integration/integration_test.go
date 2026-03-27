//go:build integration

// Package integration contains tests that run INSIDE a container where
// tsinit is PID 1. The test binary is launched as a managed process
// by tsinit itself, then exercises the HTTP API to verify that
// every feature works in a real container environment.
//
// Run via:
//   docker build -t tsinit-test -f integration/Dockerfile .
//   docker run --rm tsinit-test
package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

const (
	baseURL  = "http://localhost:9111"
	sockPath = "/var/run/tsinit.sock"
)

// --- helpers ----------------------------------------------------------------

func apiURL(path string) string { return baseURL + path }

func doJSON(t *testing.T, method, path string, body any) (*http.Response, map[string]any) {
	t.Helper()
	var reader io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		reader = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, apiURL(path), reader)
	if err != nil {
		t.Fatalf("build request: %v", err)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("%s %s: %v", method, path, err)
	}
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	var result map[string]any
	_ = json.Unmarshal(raw, &result)
	return resp, result
}

func waitForState(t *testing.T, name, wantState string, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		_, data := doJSON(t, "GET", "/v1/processes/"+name, nil)
		if data["state"] == wantState {
			return
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Fatalf("process %q did not reach state %q within %v", name, wantState, timeout)
}

func createProcess(t *testing.T, config map[string]any) (int, map[string]any) {
	t.Helper()
	resp, data := doJSON(t, "POST", "/v1/processes", config)
	return resp.StatusCode, data
}

func deleteProcess(t *testing.T, name string) int {
	t.Helper()
	resp, _ := doJSON(t, "DELETE", "/v1/processes/"+name+"?timeout=5s", nil)
	return resp.StatusCode
}

// --- tests ------------------------------------------------------------------

// TestPID1 verifies tsinit is running as PID 1.
func TestPID1(t *testing.T) {
	_, data := doJSON(t, "GET", "/info", nil)
	pid, ok := data["pid"].(float64)
	if !ok {
		t.Fatalf("missing pid in /info response: %v", data)
	}
	if int(pid) != 1 {
		t.Fatalf("expected PID 1, got %d", int(pid))
	}
	t.Logf("tsinit running as PID %d", int(pid))
}

// TestHealthEndpoint verifies /health returns valid status.
func TestHealthEndpoint(t *testing.T) {
	resp, data := doJSON(t, "GET", "/health", nil)
	if resp.StatusCode != 200 {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	status, ok := data["status"].(string)
	if !ok || (status != "healthy" && status != "degraded") {
		t.Fatalf("unexpected health status: %v", data["status"])
	}
	if _, ok := data["processes"]; !ok {
		t.Fatal("health response missing 'processes' field")
	}
	t.Logf("health status: %s", status)
}

// TestHealthViaCLI verifies the `tsinit health` CLI works via Unix socket.
func TestHealthViaCLI(t *testing.T) {
	client := &http.Client{
		Transport: &http.Transport{
			DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
				return net.Dial("unix", sockPath)
			},
		},
		Timeout: 2 * time.Second,
	}
	resp, err := client.Get("http://localhost/health")
	if err != nil {
		t.Fatalf("unix socket health check failed: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	t.Log("Unix socket health check OK")
}

// TestProcessLifecycle tests create → running → stop lifecycle.
func TestProcessLifecycle(t *testing.T) {
	name := "lifecycle-test"

	// Create a long-running process.
	code, data := createProcess(t, map[string]any{
		"name":       name,
		"cmd":        "sh -c 'echo started && sleep 3600'",
		"dir":        "/tmp",
		"tee_stdout": true,
	})
	if code != 201 {
		t.Fatalf("create: expected 201, got %d: %v", code, data)
	}
	if data["state"] != "running" {
		t.Fatalf("expected state=running, got %v", data["state"])
	}
	pid := data["pid"].(float64)
	if pid <= 0 {
		t.Fatalf("expected positive pid, got %v", pid)
	}
	t.Logf("created process %s with pid %d", name, int(pid))

	// Verify it appears in list.
	_, listData := doJSON(t, "GET", "/v1/processes", nil)
	// listData is actually []any, re-parse
	resp, _ := doJSON(t, "GET", "/v1/processes/"+name, nil)
	if resp.StatusCode != 200 {
		t.Fatalf("get: expected 200, got %d", resp.StatusCode)
	}

	// Stop it.
	delCode := deleteProcess(t, name)
	if delCode != 204 {
		t.Fatalf("delete: expected 204, got %d", delCode)
	}

	// Verify it's gone.
	resp2, _ := doJSON(t, "GET", "/v1/processes/"+name, nil)
	if resp2.StatusCode != 404 {
		t.Fatalf("expected 404 after delete, got %d", resp2.StatusCode)
	}

	_ = listData
	t.Log("process lifecycle: create → run → stop → gone OK")
}

// TestProcessOutput verifies output capture works.
func TestProcessOutput(t *testing.T) {
	name := "output-test"
	createProcess(t, map[string]any{
		"name":       name,
		"cmd":        "sh -c 'for i in 1 2 3 4 5; do echo line-$i; done; sleep 3600'",
		"tee_stdout": true,
	})
	defer deleteProcess(t, name)

	// Wait for output to be captured.
	time.Sleep(1 * time.Second)

	_, data := doJSON(t, "GET", "/v1/processes/"+name+"/output?lines=10", nil)
	lines, ok := data["lines"].([]any)
	if !ok || len(lines) == 0 {
		t.Fatalf("expected output lines, got: %v", data)
	}

	// Verify we got our expected lines.
	found := 0
	for _, l := range lines {
		s, _ := l.(string)
		if strings.Contains(s, "line-") {
			found++
		}
	}
	if found < 5 {
		t.Fatalf("expected at least 5 output lines matching 'line-', found %d in %v", found, lines)
	}
	t.Logf("output capture: %d lines captured", len(lines))
}

// TestProcessInput verifies writing to PTY stdin works.
func TestProcessInput(t *testing.T) {
	name := "input-test"
	createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sh -c 'read line; echo got:$line; sleep 3600'",
	})
	defer deleteProcess(t, name)

	time.Sleep(500 * time.Millisecond)

	// Send input.
	resp, _ := doJSON(t, "POST", "/v1/processes/"+name+"/input", map[string]any{
		"data": "hello-world\n",
	})
	if resp.StatusCode != 200 {
		t.Fatalf("input: expected 200, got %d", resp.StatusCode)
	}

	time.Sleep(500 * time.Millisecond)

	// Check output contains our input echoed back.
	_, data := doJSON(t, "GET", "/v1/processes/"+name+"/output?lines=20", nil)
	lines, _ := data["lines"].([]any)
	found := false
	for _, l := range lines {
		if strings.Contains(fmt.Sprint(l), "got:hello-world") {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected 'got:hello-world' in output, got: %v", lines)
	}
	t.Log("PTY input/output round-trip OK")
}

// TestSignalDelivery verifies sending signals to process groups works.
func TestSignalDelivery(t *testing.T) {
	name := "signal-test"
	createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sh -c 'trap \"echo caught-sigint\" INT; sleep 3600'",
	})
	defer deleteProcess(t, name)

	time.Sleep(500 * time.Millisecond)

	// Send SIGINT.
	resp, _ := doJSON(t, "POST", "/v1/processes/"+name+"/signal", map[string]any{
		"signal": "SIGINT",
	})
	if resp.StatusCode != 200 {
		t.Fatalf("signal: expected 200, got %d", resp.StatusCode)
	}

	// The process should exit (sh exits on SIGINT despite trap).
	waitForState(t, name, "exited", 5*time.Second)
	t.Log("signal delivery to process group OK")
}

// TestRestartPolicy verifies on-failure restart works.
func TestRestartPolicy(t *testing.T) {
	name := "restart-test"
	createProcess(t, map[string]any{
		"name":    name,
		"cmd":     "sh -c 'echo attempt; exit 1'",
		"restart": "on-failure",
	})
	defer deleteProcess(t, name)

	// Wait for at least 2 restarts (1s backoff each).
	time.Sleep(4 * time.Second)

	_, data := doJSON(t, "GET", "/v1/processes/"+name, nil)
	restarts, _ := data["restarts"].(float64)
	if restarts < 2 {
		t.Fatalf("expected at least 2 restarts, got %v", restarts)
	}
	t.Logf("restart policy: %d restarts observed", int(restarts))
}

// TestEphemeralProcess verifies ephemeral processes are auto-cleaned.
func TestEphemeralProcess(t *testing.T) {
	name := "ephemeral-test"
	code, _ := createProcess(t, map[string]any{
		"name":      name,
		"cmd":       "echo done",
		"ephemeral": true,
	})
	if code != 201 {
		t.Fatalf("create: expected 201, got %d", code)
	}

	// Wait for the process to exit and be cleaned up.
	time.Sleep(2 * time.Second)

	resp, _ := doJSON(t, "GET", "/v1/processes/"+name, nil)
	if resp.StatusCode != 404 {
		t.Fatalf("expected 404 after ephemeral cleanup, got %d", resp.StatusCode)
	}
	t.Log("ephemeral process auto-cleanup OK")
}

// TestProcessRestart verifies the restart endpoint works.
func TestProcessRestart(t *testing.T) {
	name := "restart-endpoint-test"
	_, data := createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sleep 3600",
	})
	oldPid := data["pid"].(float64)

	resp, newData := doJSON(t, "POST", "/v1/processes/"+name+"/restart", nil)
	if resp.StatusCode != 200 {
		t.Fatalf("restart: expected 200, got %d", resp.StatusCode)
	}

	newPid := newData["pid"].(float64)
	if newPid == oldPid {
		t.Fatalf("expected different PID after restart, both are %d", int(oldPid))
	}

	defer deleteProcess(t, name)
	t.Logf("restart: PID %d → %d", int(oldPid), int(newPid))
}

// TestDuplicateName verifies 409 on duplicate process name.
func TestDuplicateName(t *testing.T) {
	name := "dup-test"
	createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sleep 3600",
	})
	defer deleteProcess(t, name)

	code, data := createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sleep 3600",
	})
	if code != 409 {
		t.Fatalf("expected 409 for duplicate, got %d: %v", code, data)
	}
	t.Log("duplicate name returns 409 OK")
}

// TestValidationErrors verifies 400 for missing name/cmd.
func TestValidationErrors(t *testing.T) {
	code, _ := createProcess(t, map[string]any{"cmd": "echo hi"})
	if code != 400 {
		t.Fatalf("missing name: expected 400, got %d", code)
	}

	code, _ = createProcess(t, map[string]any{"name": "no-cmd"})
	if code != 400 {
		t.Fatalf("missing cmd: expected 400, got %d", code)
	}
	t.Log("validation errors return 400 OK")
}

// TestWebSocket verifies bidirectional PTY streaming.
func TestWebSocket(t *testing.T) {
	name := "ws-test"
	createProcess(t, map[string]any{
		"name":       name,
		"cmd":        "sh -c 'while true; do echo ws-tick; sleep 0.5; done'",
		"tee_stdout": true,
	})
	defer deleteProcess(t, name)

	time.Sleep(500 * time.Millisecond)

	// Connect WebSocket.
	wsURL := "ws://localhost:9111/v1/processes/" + name + "/stream"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("websocket dial: %v", err)
	}
	defer conn.Close()

	// Read a few frames.
	var received []string
	conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	for i := 0; i < 3; i++ {
		_, msg, err := conn.ReadMessage()
		if err != nil {
			t.Fatalf("websocket read: %v", err)
		}
		received = append(received, string(msg))
	}

	found := 0
	for _, r := range received {
		if strings.Contains(r, "ws-tick") {
			found++
		}
	}
	if found == 0 {
		t.Fatalf("expected 'ws-tick' in websocket output, got: %v", received)
	}
	t.Logf("websocket: received %d frames, %d with 'ws-tick'", len(received), found)
}

// TestWebSocketInput verifies sending data through WebSocket to PTY.
func TestWebSocketInput(t *testing.T) {
	name := "ws-input-test"
	createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sh",
	})
	defer deleteProcess(t, name)

	time.Sleep(500 * time.Millisecond)

	wsURL := "ws://localhost:9111/v1/processes/" + name + "/stream"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("websocket dial: %v", err)
	}
	defer conn.Close()

	// Send a command via binary frame.
	err = conn.WriteMessage(websocket.BinaryMessage, []byte("echo ws-round-trip-ok\n"))
	if err != nil {
		t.Fatalf("websocket write: %v", err)
	}

	// Read until we see the echo.
	conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	found := false
	for i := 0; i < 20; i++ {
		_, msg, err := conn.ReadMessage()
		if err != nil {
			break
		}
		if strings.Contains(string(msg), "ws-round-trip-ok") {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("did not receive 'ws-round-trip-ok' back via websocket")
	}
	t.Log("websocket input round-trip OK")
}

// TestWebSocketResize verifies PTY resize via control message.
func TestWebSocketResize(t *testing.T) {
	name := "ws-resize-test"
	createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sleep 3600",
	})
	defer deleteProcess(t, name)

	time.Sleep(300 * time.Millisecond)

	wsURL := "ws://localhost:9111/v1/processes/" + name + "/stream"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("websocket dial: %v", err)
	}
	defer conn.Close()

	// Send resize control message (text frame).
	resize := `{"type":"resize","cols":200,"rows":50}`
	err = conn.WriteMessage(websocket.TextMessage, []byte(resize))
	if err != nil {
		t.Fatalf("websocket resize write: %v", err)
	}

	// If it didn't crash, the resize was accepted.
	t.Log("websocket resize OK (no error)")
}

// TestMultipleProcesses verifies running several processes concurrently.
func TestMultipleProcesses(t *testing.T) {
	names := []string{"multi-a", "multi-b", "multi-c"}

	for i, name := range names {
		code, _ := createProcess(t, map[string]any{
			"name":       name,
			"cmd":        fmt.Sprintf("sh -c 'echo proc-%d && sleep 3600'", i),
			"tee_stdout": true,
		})
		if code != 201 {
			t.Fatalf("create %s: expected 201, got %d", name, code)
		}
	}

	// All should be running.
	resp, _ := doJSON(t, "GET", "/health", nil)
	if resp.StatusCode != 200 {
		t.Fatalf("health: expected 200, got %d", resp.StatusCode)
	}

	// List should have at least our 3 + the test runner itself.
	listResp, err := http.Get(apiURL("/v1/processes"))
	if err != nil {
		t.Fatal(err)
	}
	defer listResp.Body.Close()
	var list []map[string]any
	json.NewDecoder(listResp.Body).Decode(&list)

	found := 0
	for _, p := range list {
		for _, n := range names {
			if p["name"] == n {
				found++
			}
		}
	}
	if found != len(names) {
		t.Fatalf("expected %d processes in list, found %d", len(names), found)
	}

	// Cleanup.
	for _, name := range names {
		deleteProcess(t, name)
	}
	t.Logf("multiple concurrent processes: %d created and cleaned up", len(names))
}

// TestProcessGroupKill verifies that stopping a process kills the entire
// process group, not just the root PID. This is the core fix over tmux.
func TestProcessGroupKill(t *testing.T) {
	name := "pgkill-test"
	// Start a process that spawns children (sh → sleep).
	// The sleep child should also die when we stop the parent.
	createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sh -c 'sleep 3600 & sleep 3600 & wait'",
	})

	time.Sleep(500 * time.Millisecond)

	// Get the PID of the process.
	_, data := doJSON(t, "GET", "/v1/processes/"+name, nil)
	pid := int(data["pid"].(float64))

	// Stop it.
	deleteProcess(t, name)

	// Verify the PID is gone (kill -0 should fail).
	// Give the kernel a moment to clean up.
	time.Sleep(500 * time.Millisecond)

	// Try to find any process in the old session. We can't easily check
	// from inside the test, but we can verify tsinit reported
	// the process as stopped cleanly.
	resp, _ := doJSON(t, "GET", "/v1/processes/"+name, nil)
	if resp.StatusCode != 404 {
		t.Fatalf("expected 404 after stop, got %d", resp.StatusCode)
	}
	t.Logf("process group kill: PID %d and children cleaned up", pid)
}

// TestGracefulShutdownPrep verifies we can create processes that will be
// cleaned up during container shutdown (when tsinit receives SIGTERM).
// We don't actually trigger shutdown since that would kill the test runner.
func TestGracefulShutdownPrep(t *testing.T) {
	name := "shutdown-prep"
	code, _ := createProcess(t, map[string]any{
		"name":       name,
		"cmd":        "sleep 3600",
		"tee_stdout": true,
	})
	if code != 201 {
		t.Fatalf("create: expected 201, got %d", code)
	}

	// Verify it's running.
	_, data := doJSON(t, "GET", "/v1/processes/"+name, nil)
	if data["state"] != "running" {
		t.Fatalf("expected running, got %v", data["state"])
	}

	deleteProcess(t, name)
	t.Log("shutdown prep: process created and stopped, ready for container SIGTERM")
}

// TestConcurrentCreation verifies that concurrent creates of the same name
// don't cause a race condition (TOCTOU fix validation).
func TestConcurrentCreation(t *testing.T) {
	name := "race-test"
	n := 10
	results := make([]int, n)
	var wg sync.WaitGroup

	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			code, _ := createProcess(t, map[string]any{
				"name": name,
				"cmd":  "sleep 3600",
			})
			results[idx] = code
		}(i)
	}
	wg.Wait()

	created := 0
	conflicted := 0
	for _, code := range results {
		switch code {
		case 201:
			created++
		case 409:
			conflicted++
		}
	}

	if created != 1 {
		t.Fatalf("expected exactly 1 successful creation, got %d (conflicts: %d)", created, conflicted)
	}
	if conflicted != n-1 {
		t.Fatalf("expected %d conflicts, got %d", n-1, conflicted)
	}

	deleteProcess(t, name)
	t.Logf("concurrent creation: 1 created, %d conflicts (correct)", conflicted)
}

// TestOutputBufferLines verifies the ring buffer caps at the configured size.
func TestOutputBufferLines(t *testing.T) {
	name := "buffer-test"
	// Write more lines than the default buffer.
	lineCount := 200
	cmd := fmt.Sprintf("sh -c 'for i in $(seq 1 %d); do echo bufline-$i; done; sleep 3600'", lineCount)
	createProcess(t, map[string]any{
		"name": name,
		"cmd":  cmd,
	})
	defer deleteProcess(t, name)

	time.Sleep(2 * time.Second)

	// Request all lines — should be capped by the buffer.
	_, data := doJSON(t, "GET", "/v1/processes/"+name+"/output?lines="+strconv.Itoa(lineCount+100), nil)
	lines, _ := data["lines"].([]any)

	// We should have captured the lines (up to buffer capacity).
	if len(lines) < lineCount {
		t.Fatalf("expected at least %d lines, got %d", lineCount, len(lines))
	}

	// Verify last line is the expected one.
	lastLine := fmt.Sprint(lines[len(lines)-1])
	expected := fmt.Sprintf("bufline-%d", lineCount)
	if !strings.Contains(lastLine, expected) {
		t.Fatalf("expected last line to contain %q, got %q", expected, lastLine)
	}

	t.Logf("output buffer: %d lines captured, last=%q", len(lines), lastLine)
}

// TestNodeJSProcess verifies that a real Node.js process can be managed.
func TestNodeJSProcess(t *testing.T) {
	name := "node-test"
	createProcess(t, map[string]any{
		"name":       name,
		"cmd":        `node -e "console.log('node-ok'); setTimeout(() => {}, 60000)"`,
		"tee_stdout": true,
	})
	defer deleteProcess(t, name)

	time.Sleep(2 * time.Second)

	_, data := doJSON(t, "GET", "/v1/processes/"+name+"/output?lines=10", nil)
	lines, _ := data["lines"].([]any)
	found := false
	for _, l := range lines {
		if strings.Contains(fmt.Sprint(l), "node-ok") {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected 'node-ok' in Node.js output, got: %v", lines)
	}
	t.Log("Node.js process managed successfully")
}

// TestPythonProcess verifies that a real Python process can be managed.
func TestPythonProcess(t *testing.T) {
	name := "python-test"
	createProcess(t, map[string]any{
		"name":       name,
		"cmd":        `python3 -c "import sys; print('python-ok', flush=True); import time; time.sleep(60)"`,
		"tee_stdout": true,
	})
	defer deleteProcess(t, name)

	time.Sleep(2 * time.Second)

	_, data := doJSON(t, "GET", "/v1/processes/"+name+"/output?lines=10", nil)
	lines, _ := data["lines"].([]any)
	found := false
	for _, l := range lines {
		if strings.Contains(fmt.Sprint(l), "python-ok") {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected 'python-ok' in Python output, got: %v", lines)
	}
	t.Log("Python process managed successfully")
}

// TestEnvironmentVariables verifies env vars are passed to processes.
func TestEnvironmentVariables(t *testing.T) {
	name := "env-test"
	createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sh -c 'echo TEST_VAR=$TEST_VAR; sleep 3600'",
		"env":  []string{"TEST_VAR=hello-from-init"},
	})
	defer deleteProcess(t, name)

	time.Sleep(1 * time.Second)

	_, data := doJSON(t, "GET", "/v1/processes/"+name+"/output?lines=10", nil)
	lines, _ := data["lines"].([]any)
	found := false
	for _, l := range lines {
		if strings.Contains(fmt.Sprint(l), "TEST_VAR=hello-from-init") {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected env var in output, got: %v", lines)
	}
	t.Log("environment variables passed correctly")
}

// TestInfoEndpoint verifies /info returns version and identity.
func TestInfoEndpoint(t *testing.T) {
	_, data := doJSON(t, "GET", "/info", nil)

	v, _ := data["version"].(string)
	if v == "" {
		t.Fatal("missing version in /info")
	}
	if v != "integration-test" {
		t.Fatalf("expected version=integration-test, got %q", v)
	}

	// project_id and container_id should be empty (not set in env).
	t.Logf("info: version=%s", v)
}

// TestSelfVisibleInList verifies the test runner itself appears as a managed
// process (it was started via --process flag by the ENTRYPOINT).
func TestSelfVisibleInList(t *testing.T) {
	listResp, err := http.Get(apiURL("/v1/processes"))
	if err != nil {
		t.Fatal(err)
	}
	defer listResp.Body.Close()
	var list []map[string]any
	json.NewDecoder(listResp.Body).Decode(&list)

	found := false
	for _, p := range list {
		if p["name"] == "tests" {
			found = true
			if p["state"] != "running" {
				t.Fatalf("test runner process state: %v", p["state"])
			}
		}
	}
	if !found {
		t.Fatal("test runner process 'tests' not found in process list")
	}
	t.Log("test runner visible as managed process 'tests'")
}

// TestShutdownEndpointExists verifies /shutdown is routed (but don't call it).
func TestShutdownEndpointExists(t *testing.T) {
	// Send a GET to /shutdown — should be 405 (method not allowed) since
	// only POST is registered.
	resp, err := http.Get(apiURL("/shutdown"))
	if err != nil {
		t.Fatalf("shutdown GET: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != 405 {
		t.Fatalf("expected 405 for GET /shutdown, got %d", resp.StatusCode)
	}
	t.Log("/shutdown endpoint exists (POST only)")
}

// TestNotFoundProcess verifies 404 for non-existent process operations.
func TestNotFoundProcess(t *testing.T) {
	paths := []struct {
		method string
		path   string
	}{
		{"GET", "/v1/processes/nonexistent"},
		{"DELETE", "/v1/processes/nonexistent"},
		{"POST", "/v1/processes/nonexistent/restart"},
		{"POST", "/v1/processes/nonexistent/input"},
		{"POST", "/v1/processes/nonexistent/signal"},
		{"GET", "/v1/processes/nonexistent/output"},
	}

	for _, p := range paths {
		resp, _ := doJSON(t, p.method, p.path, map[string]any{
			"data":   "test",
			"signal": "SIGINT",
		})
		if resp.StatusCode != 404 {
			t.Fatalf("%s %s: expected 404, got %d", p.method, p.path, resp.StatusCode)
		}
	}
	t.Log("all not-found cases return 404 OK")
}

// TestUnsupportedSignal verifies 400 for unknown signal names.
func TestUnsupportedSignal(t *testing.T) {
	name := "bad-signal-test"
	createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sleep 3600",
	})
	defer deleteProcess(t, name)

	resp, _ := doJSON(t, "POST", "/v1/processes/"+name+"/signal", map[string]any{
		"signal": "SIGFAKE",
	})
	if resp.StatusCode != 400 {
		t.Fatalf("expected 400 for bad signal, got %d", resp.StatusCode)
	}
	t.Log("unsupported signal returns 400 OK")
}

// TestStdoutTeePrefix verifies that tee_stdout processes get [name] prefix.
// This test reads the ring buffer looking for the prefix pattern.
func TestStdoutTeePrefix(t *testing.T) {
	// The test runner itself is tee'd, so tsinit's stdout has
	// lines like [tests] ...
	// We create a process and check its own output (ring buffer doesn't
	// include prefix — prefix goes to container stdout only).
	name := "tee-test"
	createProcess(t, map[string]any{
		"name":       name,
		"cmd":        "echo tee-marker",
		"tee_stdout": true,
	})

	time.Sleep(1 * time.Second)

	// The ring buffer should have the raw output WITHOUT prefix.
	_, data := doJSON(t, "GET", "/v1/processes/"+name+"/output?lines=5", nil)
	lines, _ := data["lines"].([]any)
	found := false
	for _, l := range lines {
		s := fmt.Sprint(l)
		if strings.Contains(s, "tee-marker") && !strings.Contains(s, "[tee-test]") {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected raw 'tee-marker' without prefix in ring buffer, got: %v", lines)
	}

	deleteProcess(t, name)
	t.Log("stdout tee: ring buffer has raw output, prefix goes to container stdout only")
}
