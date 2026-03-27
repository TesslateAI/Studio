package api

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/tesslate/tsinit/internal/process"
)

// --- Request / Response types ------------------------------------------------

type inputRequest struct {
	Data string `json:"data"`
}

type signalRequest struct {
	Signal string `json:"signal"`
}

type outputResponse struct {
	Lines []string `json:"lines"`
}

type infoResponse struct {
	Version     string `json:"version"`
	Pid         int    `json:"pid"`
	ProjectID   string `json:"project_id"`
	ContainerID string `json:"container_id"`
}

type errorResponse struct {
	Error string `json:"error"`
}

// --- Helpers -----------------------------------------------------------------

// writeJSON serializes v as JSON and writes it with the given HTTP status code.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		slog.Error("failed to write JSON response", "error", err)
	}
}

// writeError writes a JSON error response.
func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, errorResponse{Error: msg})
}

// parseDuration parses a Go duration string (e.g. "10s", "5m"). Returns
// defaultVal if s is empty or unparseable.
func parseDuration(s string, defaultVal time.Duration) time.Duration {
	if s == "" {
		return defaultVal
	}
	d, err := time.ParseDuration(s)
	if err != nil {
		return defaultVal
	}
	return d
}

// signalMap maps human-readable signal names to their syscall equivalents.
var signalMap = map[string]syscall.Signal{
	"SIGINT":  syscall.SIGINT,
	"SIGTERM": syscall.SIGTERM,
	"SIGKILL": syscall.SIGKILL,
	"SIGHUP":  syscall.SIGHUP,
	"SIGUSR1": syscall.SIGUSR1,
	"SIGUSR2": syscall.SIGUSR2,
}

// --- Handlers ----------------------------------------------------------------

// handleCreateProcess handles POST /v1/processes.
// Expects a ProcessConfig JSON body. Returns 201 with the new ProcessStatus.
func (s *Server) handleCreateProcess(w http.ResponseWriter, r *http.Request) {
	var config process.ProcessConfig
	if err := json.NewDecoder(r.Body).Decode(&config); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
		return
	}

	status, err := s.manager.Start(config)
	if err != nil {
		switch {
		case strings.Contains(err.Error(), "already exists"):
			writeError(w, http.StatusConflict, err.Error())
		case strings.Contains(err.Error(), "is required"):
			writeError(w, http.StatusBadRequest, err.Error())
		default:
			writeError(w, http.StatusInternalServerError, err.Error())
		}
		return
	}

	writeJSON(w, http.StatusCreated, status)
}

// handleListProcesses handles GET /v1/processes.
// Returns 200 with an array of ProcessStatus.
func (s *Server) handleListProcesses(w http.ResponseWriter, r *http.Request) {
	statuses := s.manager.List()
	writeJSON(w, http.StatusOK, statuses)
}

// handleGetProcess handles GET /v1/processes/{name}.
// Returns 200 with ProcessStatus or 404 if not found.
func (s *Server) handleGetProcess(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	proc, ok := s.manager.Get(name)
	if !ok {
		writeError(w, http.StatusNotFound, "process not found: "+name)
		return
	}
	status := proc.Status()
	writeJSON(w, http.StatusOK, status)
}

// handleDeleteProcess handles DELETE /v1/processes/{name}.
// Optional query param: ?timeout=10s (default 10s). Returns 204 on success.
func (s *Server) handleDeleteProcess(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	timeout := parseDuration(r.URL.Query().Get("timeout"), 10*time.Second)

	if err := s.manager.Stop(name, timeout); err != nil {
		if strings.Contains(err.Error(), "not found") {
			writeError(w, http.StatusNotFound, err.Error())
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

// handleRestartProcess handles POST /v1/processes/{name}/restart.
// Returns 200 with the new ProcessStatus.
func (s *Server) handleRestartProcess(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")

	status, err := s.manager.Restart(name)
	if err != nil {
		if strings.Contains(err.Error(), "not found") {
			writeError(w, http.StatusNotFound, err.Error())
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, status)
}

// handleProcessInput handles POST /v1/processes/{name}/input.
// Body: {"data": "some text\n"}. The data is written to the process PTY stdin.
func (s *Server) handleProcessInput(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	proc, ok := s.manager.Get(name)
	if !ok {
		writeError(w, http.StatusNotFound, "process not found: "+name)
		return
	}

	var req inputRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
		return
	}

	// Replace literal \n escape sequences with actual newlines so callers
	// can send "ls\n" as a convenience.
	data := strings.ReplaceAll(req.Data, `\n`, "\n")

	if _, err := proc.WriteInput([]byte(data)); err != nil {
		writeError(w, http.StatusInternalServerError, "write failed: "+err.Error())
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// handleProcessSignal handles POST /v1/processes/{name}/signal.
// Body: {"signal": "SIGINT"}. Supported: SIGINT, SIGTERM, SIGKILL, SIGHUP,
// SIGUSR1, SIGUSR2.
func (s *Server) handleProcessSignal(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	proc, ok := s.manager.Get(name)
	if !ok {
		writeError(w, http.StatusNotFound, "process not found: "+name)
		return
	}

	var req signalRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
		return
	}

	sig, ok := signalMap[strings.ToUpper(req.Signal)]
	if !ok {
		writeError(w, http.StatusBadRequest, "unsupported signal: "+req.Signal)
		return
	}

	if err := proc.SendSignal(sig); err != nil {
		writeError(w, http.StatusInternalServerError, "signal failed: "+err.Error())
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// handleProcessOutput handles GET /v1/processes/{name}/output.
// Optional query param: ?lines=100 (default 100). Returns recent output lines.
func (s *Server) handleProcessOutput(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	proc, ok := s.manager.Get(name)
	if !ok {
		writeError(w, http.StatusNotFound, "process not found: "+name)
		return
	}

	lines := 100
	if v := r.URL.Query().Get("lines"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			lines = n
		}
	}

	output := proc.Output(lines)
	writeJSON(w, http.StatusOK, outputResponse{Lines: output})
}

// handleHealth handles GET /health.
// Returns aggregate health status. Used by K8s liveness/readiness probes.
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	health := s.manager.Health()
	writeJSON(w, http.StatusOK, health)
}

// handleInfo handles GET /info.
// Returns environment identity information for the init process.
func (s *Server) handleInfo(w http.ResponseWriter, r *http.Request) {
	info := infoResponse{
		Version:     s.manager.Health().Version,
		Pid:         os.Getpid(),
		ProjectID:   os.Getenv("TESSLATE_PROJECT_ID"),
		ContainerID: os.Getenv("TESSLATE_CONTAINER_ID"),
	}
	writeJSON(w, http.StatusOK, info)
}

// handleShutdown handles POST /shutdown.
// Triggers graceful supervisor shutdown.
func (s *Server) handleShutdown(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "shutting down"})

	if s.shutdownFunc != nil {
		// Run in a goroutine so the response is flushed before shutdown begins.
		go s.shutdownFunc()
	}
}
