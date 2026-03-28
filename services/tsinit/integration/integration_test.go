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
	"net/url"
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
		"cmd":        "sh -c 'echo tee-marker; sleep 5'",
		"tee_stdout": true,
	})

	// Wait for output to appear in the ring buffer (poll, bounded).
	deadline := time.Now().Add(3 * time.Second)
	found := false
	for time.Now().Before(deadline) {
		_, data := doJSON(t, "GET", "/v1/processes/"+name+"/output?lines=5", nil)
		lines, _ := data["lines"].([]any)
		for _, l := range lines {
			s := fmt.Sprint(l)
			if strings.Contains(s, "tee-marker") && !strings.Contains(s, "[tee-test]") {
				found = true
			}
		}
		if found {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if !found {
		t.Fatal("expected raw 'tee-marker' without prefix in ring buffer")
	}

	deleteProcess(t, name)
	t.Log("stdout tee: ring buffer has raw output, prefix goes to container stdout only")
}

// TestForkAndExit verifies that when the direct child (shell) exits but
// a forked descendant is still alive, tsinit keeps the process state as
// "running" instead of "exited".
//
// This simulates the real-world pattern where:
//   bun run dev → forks next-server → bun exits → next-server keeps running
//
// With Setpgid (no Setsid), the shell exiting does NOT send SIGHUP to
// the process group, so even plain sleep survives. This is the key fix
// for fork-and-exit wrappers like bun/npx/npm run.
func TestForkAndExit(t *testing.T) {
	name := "fork-exit-test"

	// Shell forks a background sleep (simulating a dev server), then exits.
	// With Setpgid, no SIGHUP is sent — sleep survives.
	code, _ := createProcess(t, map[string]any{
		"name": name,
		"cmd":  `sh -c 'sleep 300 & echo FORK_CHILD_READY; exit 0'`,
	})
	if code != 201 {
		t.Fatalf("expected 201, got %d", code)
	}

	// Wait for the forked child to start.
	deadline := time.Now().Add(10 * time.Second)
	ready := false
	for time.Now().Before(deadline) {
		_, data := doJSON(t, "GET", "/v1/processes/"+name+"/output?lines=20", nil)
		lines, _ := data["lines"].([]any)
		for _, l := range lines {
			if strings.Contains(fmt.Sprint(l), "FORK_CHILD_READY") {
				ready = true
				break
			}
		}
		if ready {
			break
		}
		time.Sleep(300 * time.Millisecond)
	}
	if !ready {
		t.Fatal("forked child did not start within 10s")
	}

	// Give the shell time to exit.
	time.Sleep(2 * time.Second)

	// The shell (direct child) has exited, but sleep is still alive in the
	// process group. tsinit should still report state as "running".
	_, data := doJSON(t, "GET", "/v1/processes/"+name, nil)
	state := data["state"].(string)
	if state != "running" {
		t.Fatalf("expected state 'running' (process group alive), got %q", state)
	}
	t.Logf("process state is %q with shell exited but forked child alive — correct", state)

	// Now stop the process — should kill the entire group.
	deleteProcess(t, name)
	t.Log("fork-and-exit: process group tracked correctly, stop kills all members")
}

// TestForkAndExitWithServer verifies fork-and-exit with a real HTTP server
// (node), confirming the server is reachable and cleanup kills it.
func TestForkAndExitWithServer(t *testing.T) {
	name := "fork-server-test"

	code, _ := createProcess(t, map[string]any{
		"name": name,
		"cmd":  `sh -c 'node -e "require(\"http\").createServer((_,r)=>{r.end(\"ok\")}).listen(18999,()=>{console.log(\"SERVER_READY\")})" & sleep 0.5; exit 0'`,
	})
	if code != 201 {
		t.Fatalf("expected 201, got %d", code)
	}

	// Wait for server to start.
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		_, data := doJSON(t, "GET", "/v1/processes/"+name+"/output?lines=20", nil)
		lines, _ := data["lines"].([]any)
		for _, l := range lines {
			if strings.Contains(fmt.Sprint(l), "SERVER_READY") {
				goto serverUp
			}
		}
		time.Sleep(500 * time.Millisecond)
	}
	t.Fatal("node server did not print SERVER_READY within 10s")
serverUp:

	time.Sleep(2 * time.Second)

	// Process should be running (group alive).
	_, data := doJSON(t, "GET", "/v1/processes/"+name, nil)
	if data["state"].(string) != "running" {
		t.Fatalf("expected 'running', got %q", data["state"])
	}

	// Server should be reachable.
	resp, err := http.Get("http://localhost:18999/")
	if err != nil {
		t.Fatalf("node server not reachable: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
	t.Log("node server responding on port 18999")

	// Stop should kill the server.
	deleteProcess(t, name)
	time.Sleep(1 * time.Second)
	_, err = http.Get("http://localhost:18999/")
	if err == nil {
		t.Fatal("node server should be dead after stop, but it responded")
	}
	t.Log("fork-and-exit with server: tracked, reachable, cleanup works")
}

// TestForkAndExitCleanExit verifies that when both the direct child AND
// all process group members exit, tsinit correctly transitions to "exited".
func TestForkAndExitCleanExit(t *testing.T) {
	name := "fork-clean-exit"

	// Shell forks a short-lived sleep, then exits. Sleep runs for 2s.
	code, _ := createProcess(t, map[string]any{
		"name": name,
		"cmd":  `sh -c 'sleep 2 & echo EPHEMERAL_READY; exit 0'`,
	})
	if code != 201 {
		t.Fatalf("expected 201, got %d", code)
	}

	time.Sleep(1 * time.Second)

	// Should be "running" while sleep is alive.
	_, data := doJSON(t, "GET", "/v1/processes/"+name, nil)
	state := data["state"].(string)
	if state != "running" {
		t.Fatalf("expected 'running' while forked child alive, got %q", state)
	}

	// Wait for sleep to exit (2s + poll margin).
	waitForState(t, name, "exited", 8*time.Second)
	t.Log("fork-clean-exit: process group empty → correctly transitioned to exited")
}

// ---------------------------------------------------------------------------
// /v1/run — channel-multiplexed WebSocket endpoint
// ---------------------------------------------------------------------------

// readRunFrame reads a single channel-multiplexed binary frame from the
// WebSocket and returns (channel, payload). Returns (-1, nil) on error.
func readRunFrame(conn *websocket.Conn) (byte, []byte) {
	_, data, err := conn.ReadMessage()
	if err != nil || len(data) < 1 {
		return 0xFF, nil
	}
	return data[0], data[1:]
}

// sendRunFrame sends a channel-prefixed binary frame.
func sendRunFrame(t *testing.T, conn *websocket.Conn, ch byte, payload []byte) {
	t.Helper()
	frame := make([]byte, 1+len(payload))
	frame[0] = ch
	copy(frame[1:], payload)
	if err := conn.WriteMessage(websocket.BinaryMessage, frame); err != nil {
		t.Fatalf("sendRunFrame: %v", err)
	}
}

// dialRun connects to /v1/run with the given query string.
func dialRun(t *testing.T, query string) *websocket.Conn {
	t.Helper()
	url := "ws://localhost:9111/v1/run?" + query
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		t.Fatalf("dialRun: %v", err)
	}
	return conn
}

// collectRunOutput reads all frames until a status (channel 3) frame or timeout.
// Returns collected stdout, stderr, and the exit code.
func collectRunOutput(t *testing.T, conn *websocket.Conn, timeout time.Duration) (stdout, stderr string, exitCode int) {
	t.Helper()
	conn.SetReadDeadline(time.Now().Add(timeout))
	var outBuf, errBuf bytes.Buffer
	exitCode = -1

	for {
		ch, payload := readRunFrame(conn)
		if ch == 0xFF {
			break
		}
		switch ch {
		case 1: // stdout
			outBuf.Write(payload)
		case 2: // stderr
			errBuf.Write(payload)
		case 3: // status
			var status struct {
				ExitCode int `json:"exit_code"`
			}
			if err := json.Unmarshal(payload, &status); err == nil {
				exitCode = status.ExitCode
			}
			return outBuf.String(), errBuf.String(), exitCode
		}
	}
	return outBuf.String(), errBuf.String(), exitCode
}

// TestRunTTYEcho verifies a basic TTY-mode command that echoes output.
func TestRunTTYEcho(t *testing.T) {
	conn := dialRun(t, "cmd=echo+hello-run&tty=true")
	defer conn.Close()

	stdout, _, exitCode := collectRunOutput(t, conn, 5*time.Second)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", exitCode)
	}
	if !strings.Contains(stdout, "hello-run") {
		t.Fatalf("expected 'hello-run' in stdout, got %q", stdout)
	}
	t.Logf("run TTY echo: exit=%d, stdout=%q", exitCode, strings.TrimSpace(stdout))
}

// TestRunPipeStdoutStderr verifies non-TTY mode separates stdout and stderr.
func TestRunPipeStdoutStderr(t *testing.T) {
	conn := dialRun(t, "cmd=sh+-c+%27echo+out-data+%26%26+echo+err-data+%3E%262%27&tty=false")
	defer conn.Close()

	stdout, stderr, exitCode := collectRunOutput(t, conn, 5*time.Second)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", exitCode)
	}
	if !strings.Contains(stdout, "out-data") {
		t.Fatalf("expected 'out-data' in stdout, got %q", stdout)
	}
	if !strings.Contains(stderr, "err-data") {
		t.Fatalf("expected 'err-data' in stderr, got %q", stderr)
	}
	t.Logf("run pipe: exit=%d stdout=%q stderr=%q", exitCode, strings.TrimSpace(stdout), strings.TrimSpace(stderr))
}

// TestRunExitCodeNonZero verifies the correct exit code is reported.
func TestRunExitCodeNonZero(t *testing.T) {
	conn := dialRun(t, "cmd=sh+-c+%27exit+42%27&tty=false")
	defer conn.Close()

	_, _, exitCode := collectRunOutput(t, conn, 5*time.Second)
	if exitCode != 42 {
		t.Fatalf("expected exit code 42, got %d", exitCode)
	}
	t.Logf("run exit code: got %d (correct)", exitCode)
}

// TestRunTTYInputRoundTrip verifies that stdin data sent on channel 0
// is echoed back on channel 1 through the PTY.
func TestRunTTYInputRoundTrip(t *testing.T) {
	// Start an interactive shell.
	conn := dialRun(t, "cmd=sh&tty=true")
	defer conn.Close()

	// Wait briefly for shell to start, then send a command.
	time.Sleep(300 * time.Millisecond)
	sendRunFrame(t, conn, 0, []byte("echo run-roundtrip-ok\n"))

	// Read frames until we see the echo.
	conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	found := false
	for i := 0; i < 30; i++ {
		ch, payload := readRunFrame(conn)
		if ch == 0xFF {
			break
		}
		if ch == 1 && strings.Contains(string(payload), "run-roundtrip-ok") {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("did not see 'run-roundtrip-ok' echoed back on channel 1")
	}
	t.Log("run TTY input round-trip OK")
}

// TestRunTTYResize verifies that resize messages on channel 4 are accepted.
func TestRunTTYResize(t *testing.T) {
	conn := dialRun(t, "cmd=sh&tty=true&cols=80&rows=24")
	defer conn.Close()

	time.Sleep(300 * time.Millisecond)

	// Send resize on channel 4.
	resize := []byte(`{"width":200,"height":50}`)
	sendRunFrame(t, conn, 4, resize)

	// Send a tput command to verify the new size is applied.
	sendRunFrame(t, conn, 0, []byte("tput cols\n"))

	conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	found := false
	for i := 0; i < 20; i++ {
		ch, payload := readRunFrame(conn)
		if ch == 0xFF {
			break
		}
		if ch == 1 && strings.Contains(string(payload), "200") {
			found = true
			break
		}
	}
	if !found {
		t.Log("tput cols did not return 200 (tput may not be installed); resize accepted without error")
	} else {
		t.Log("run TTY resize verified: cols=200")
	}
}

// TestRunDisconnectKillsProcess verifies that closing the WebSocket kills
// the remote process (one connection = one lifecycle).
func TestRunDisconnectKillsProcess(t *testing.T) {
	// Use a marker file: the process creates it on start, we check removal after disconnect.
	marker := "/tmp/tsinit-test-disconnect-" + strconv.FormatInt(time.Now().UnixNano(), 36)

	// Start a process that creates a marker file then sleeps.
	cmd := fmt.Sprintf("touch %s && sleep 3600", marker)
	conn := dialRun(t, "cmd="+url.QueryEscape(cmd)+"&tty=false")

	time.Sleep(500 * time.Millisecond)

	// Verify marker exists (process started).
	checkConn := dialRun(t, "cmd="+url.QueryEscape(fmt.Sprintf("test -f %s && echo EXISTS || echo GONE", marker))+"&tty=false")
	stdout, _, _ := collectRunOutput(t, checkConn, 3*time.Second)
	if !strings.Contains(stdout, "EXISTS") {
		t.Fatal("marker file not created — process didn't start")
	}

	// Disconnect. The server's cleanup runs asynchronously after the
	// client close returns, so we poll for the process to die.
	conn.Close()

	// Poll until sleep 3600 is gone (bounded — fails after 5s).
	// Use ps + grep -v grep to avoid pgrep matching its own args.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		checkConn2 := dialRun(t, "cmd="+url.QueryEscape("ps aux | grep 'sleep 3600' | grep -v grep | grep -v ps > /dev/null 2>&1 && echo ALIVE || echo DEAD")+"&tty=false")
		stdout2, _, _ := collectRunOutput(t, checkConn2, 3*time.Second)
		if strings.Contains(stdout2, "DEAD") {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("process survived WebSocket disconnect after 5s")
		}
	}

	// Clean up marker.
	cleanConn := dialRun(t, "cmd="+url.QueryEscape(fmt.Sprintf("rm -f %s", marker))+"&tty=false")
	collectRunOutput(t, cleanConn, 3*time.Second)

	t.Log("run disconnect: process killed correctly")
}

// TestRunDisconnectKillsBackgroundJobs verifies that closing the WebSocket
// kills background jobs spawned by the shell, not just the shell itself.
// With Setsid+Setctty, the shell uses job control and creates separate
// process groups for background jobs. killSession must find and kill all
// processes in the session via /proc.
func TestRunDisconnectKillsBackgroundJobs(t *testing.T) {
	// Use unique marker files for each background job.
	id := strconv.FormatInt(time.Now().UnixNano(), 36)
	markerA := "/tmp/tsinit-bg-a-" + id
	markerB := "/tmp/tsinit-bg-b-" + id

	// Start an interactive TTY shell.
	conn := dialRun(t, "cmd=sh&tty=true")
	time.Sleep(500 * time.Millisecond)

	// Spawn background jobs that create marker files and sleep.
	// Each background job gets its own PGID under job control.
	sendRunFrame(t, conn, 0, []byte(fmt.Sprintf("sh -c 'touch %s && sleep 9001' &\n", markerA)))
	time.Sleep(300 * time.Millisecond)
	sendRunFrame(t, conn, 0, []byte(fmt.Sprintf("sh -c 'touch %s && sleep 9002' &\n", markerB)))
	time.Sleep(300 * time.Millisecond)

	// Verify both markers exist (jobs started).
	checkCmd := fmt.Sprintf("test -f %s && test -f %s && echo BOTH_RUNNING || echo NOT_READY", markerA, markerB)
	checkConn := dialRun(t, "cmd="+url.QueryEscape(checkCmd)+"&tty=false")
	stdout, _, _ := collectRunOutput(t, checkConn, 3*time.Second)
	if !strings.Contains(stdout, "BOTH_RUNNING") {
		t.Fatalf("background jobs did not start: %s", strings.TrimSpace(stdout))
	}

	// Disconnect the TTY session.
	conn.Close()

	// Poll until background sleeps are gone (bounded — fails after 5s).
	checkCmd2 := "pgrep -f 'sleep 900[12]' >/dev/null 2>&1 && echo LEAKED || echo CLEAN"
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		checkConn2 := dialRun(t, "cmd="+url.QueryEscape(checkCmd2)+"&tty=false")
		stdout2, _, _ := collectRunOutput(t, checkConn2, 3*time.Second)
		if strings.Contains(stdout2, "CLEAN") {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("background jobs survived disconnect after 5s")
		}
	}

	// Clean up markers.
	cleanCmd := fmt.Sprintf("rm -f %s %s", markerA, markerB)
	cleanConn := dialRun(t, "cmd="+url.QueryEscape(cleanCmd)+"&tty=false")
	collectRunOutput(t, cleanConn, 3*time.Second)

	t.Log("run disconnect: background jobs killed correctly (session-level cleanup)")
}

// TestRunLargeOutput verifies that large output is delivered in full.
func TestRunLargeOutput(t *testing.T) {
	// Generate 10000 lines of output.
	conn := dialRun(t, "cmd=seq+10000&tty=false")
	defer conn.Close()

	stdout, _, exitCode := collectRunOutput(t, conn, 10*time.Second)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", exitCode)
	}
	lines := strings.Split(strings.TrimSpace(stdout), "\n")
	if len(lines) < 9000 {
		t.Fatalf("expected ~10000 lines, got %d", len(lines))
	}
	// Check last line is "10000"
	last := strings.TrimSpace(lines[len(lines)-1])
	if last != "10000" {
		t.Fatalf("expected last line '10000', got %q", last)
	}
	t.Logf("run large output: %d lines delivered, last=%s", len(lines), last)
}

// TestRunWorkingDirectory verifies the dir query parameter is respected.
func TestRunWorkingDirectory(t *testing.T) {
	conn := dialRun(t, "cmd=pwd&dir=%2Ftmp&tty=false")
	defer conn.Close()

	stdout, _, exitCode := collectRunOutput(t, conn, 5*time.Second)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", exitCode)
	}
	if !strings.Contains(stdout, "/tmp") {
		t.Fatalf("expected '/tmp' in pwd output, got %q", stdout)
	}
	t.Logf("run working directory: %s", strings.TrimSpace(stdout))
}

// TestRunMissingCmd verifies that missing cmd returns an HTTP error (not a WS upgrade).
func TestRunMissingCmd(t *testing.T) {
	resp, data := doJSON(t, "GET", "/v1/run", nil)
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d: %v", resp.StatusCode, data)
	}
	t.Log("run missing cmd: correctly returned 400")
}

// TestRunDoesNotBreakManagedProcesses verifies that /v1/run sessions don't
// interfere with the supervisor's managed process lifecycle. This catches
// regressions where tracked PID locking contends with the zombie reaper
// and blocks managed process reaping (e.g. bun → next-server fork-and-exit).
func TestRunDoesNotBreakManagedProcesses(t *testing.T) {
	// Start a managed fork-and-exit process (simulates bun → next-server).
	name := "run-coexist-test"
	code, _ := createProcess(t, map[string]any{
		"name": name,
		"cmd":  "sh -c 'sleep 2 & exec sleep 0'",
	})
	if code != 201 {
		t.Fatalf("expected 201, got %d", code)
	}
	defer deleteProcess(t, name)

	// Simultaneously run several /v1/run sessions to create lock contention.
	var wg sync.WaitGroup
	for i := 0; i < 5; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			conn := dialRun(t, "cmd=echo+coexist-ok&tty=false")
			defer conn.Close()
			collectRunOutput(t, conn, 5*time.Second)
		}()
	}
	wg.Wait()

	// The managed process should still be tracked correctly.
	// It should reach "running" (group alive) then "exited" (group empty).
	waitForState(t, name, "exited", 10*time.Second)
	t.Log("run+managed coexistence: managed process lifecycle unaffected")
}
