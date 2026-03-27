package api

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"os"
	"time"

	"github.com/tesslate/tsinit/internal/process"
)

// Server serves the tsinit REST API on both a TCP port and a Unix
// domain socket. The Unix socket enables fast in-container communication
// without network overhead.
type Server struct {
	manager      *process.ProcessManager
	mux          *http.ServeMux
	tcpAddr      string
	sockPath     string
	tcpServer    *http.Server
	sockServer   *http.Server
	shutdownFunc func()
}

// NewServer creates a new API server wired to the given process manager.
// tcpAddr is the TCP listen address (e.g. ":8100"). sockPath is the Unix
// socket path (e.g. "/run/tesslate/init.sock"). shutdownFunc is called
// when the POST /shutdown endpoint is hit.
func NewServer(manager *process.ProcessManager, tcpAddr, sockPath string) *Server {
	s := &Server{
		manager:  manager,
		mux:      http.NewServeMux(),
		tcpAddr:  tcpAddr,
		sockPath: sockPath,
	}
	s.registerRoutes()
	return s
}

// SetShutdownFunc sets the function to call when the /shutdown endpoint is
// invoked. This is typically the supervisor's Shutdown method.
func (s *Server) SetShutdownFunc(fn func()) {
	s.shutdownFunc = fn
}

// registerRoutes configures all HTTP routes using Go 1.22+ method-pattern routing.
func (s *Server) registerRoutes() {
	// Process lifecycle
	s.mux.HandleFunc("POST /v1/processes", s.handleCreateProcess)
	s.mux.HandleFunc("GET /v1/processes", s.handleListProcesses)
	s.mux.HandleFunc("GET /v1/processes/{name}", s.handleGetProcess)
	s.mux.HandleFunc("DELETE /v1/processes/{name}", s.handleDeleteProcess)
	s.mux.HandleFunc("POST /v1/processes/{name}/restart", s.handleRestartProcess)

	// Process interaction
	s.mux.HandleFunc("POST /v1/processes/{name}/input", s.handleProcessInput)
	s.mux.HandleFunc("POST /v1/processes/{name}/signal", s.handleProcessSignal)
	s.mux.HandleFunc("GET /v1/processes/{name}/output", s.handleProcessOutput)

	// WebSocket streaming
	s.mux.HandleFunc("GET /v1/processes/{name}/stream", s.handleProcessStream)

	// System
	s.mux.HandleFunc("GET /health", s.handleHealth)
	s.mux.HandleFunc("GET /info", s.handleInfo)
	s.mux.HandleFunc("POST /shutdown", s.handleShutdown)
}

// Start begins listening on both the TCP and Unix socket addresses.
// Both listeners run in background goroutines; this method returns
// immediately after both are bound.
func (s *Server) Start() error {
	// Remove stale socket file if it exists from a previous run.
	if s.sockPath != "" {
		if err := os.Remove(s.sockPath); err != nil && !os.IsNotExist(err) {
			slog.Warn("failed to remove stale socket", "path", s.sockPath, "error", err)
		}
	}

	s.tcpServer = &http.Server{
		Addr:              s.tcpAddr,
		Handler:           s.mux,
		ReadHeaderTimeout: 10 * time.Second,
	}

	// Start TCP listener.
	tcpLn, err := net.Listen("tcp", s.tcpAddr)
	if err != nil {
		return err
	}
	slog.Info("API server listening", "transport", "tcp", "addr", s.tcpAddr)
	go func() {
		if err := s.tcpServer.Serve(tcpLn); err != nil && !errors.Is(err, http.ErrServerClosed) {
			slog.Error("TCP server error", "error", err)
		}
	}()

	// Start Unix socket listener if a path was provided.
	if s.sockPath != "" {
		s.sockServer = &http.Server{
			Handler:           s.mux,
			ReadHeaderTimeout: 10 * time.Second,
		}
		sockLn, err := net.Listen("unix", s.sockPath)
		if err != nil {
			return err
		}
		// Make the socket world-readable/writable so any user in the container
		// can talk to the init process.
		if err := os.Chmod(s.sockPath, 0666); err != nil {
			slog.Warn("failed to chmod socket", "path", s.sockPath, "error", err)
		}
		slog.Info("API server listening", "transport", "unix", "path", s.sockPath)
		go func() {
			if err := s.sockServer.Serve(sockLn); err != nil && !errors.Is(err, http.ErrServerClosed) {
				slog.Error("Unix socket server error", "error", err)
			}
		}()
	}

	return nil
}

// Shutdown gracefully shuts down both the TCP and Unix socket servers.
func (s *Server) Shutdown(ctx context.Context) error {
	var errs []error

	if s.tcpServer != nil {
		if err := s.tcpServer.Shutdown(ctx); err != nil {
			errs = append(errs, err)
		}
	}
	if s.sockServer != nil {
		if err := s.sockServer.Shutdown(ctx); err != nil {
			errs = append(errs, err)
		}
	}

	// Clean up socket file.
	if s.sockPath != "" {
		os.Remove(s.sockPath)
	}

	return errors.Join(errs...)
}
