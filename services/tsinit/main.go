package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/tesslate/tsinit/internal/api"
	"github.com/tesslate/tsinit/internal/process"
	"github.com/tesslate/tsinit/internal/supervisor"
)

var version = "dev" // set via -ldflags at build time

// processFlag is a repeatable string flag for --process name=command.
type processFlag []string

func (f *processFlag) String() string { return strings.Join(*f, ", ") }
func (f *processFlag) Set(value string) error {
	*f = append(*f, value)
	return nil
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(1)
	}

	switch os.Args[1] {
	case "serve":
		cmdServe()
	case "health":
		cmdHealth()
	case "version":
		cmdVersion()
	default:
		usage()
		os.Exit(1)
	}
}

func cmdServe() {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)

	var processes processFlag
	fs.Var(&processes, "process", "Process to start (name=command, repeatable)")
	dir := fs.String("dir", "", "Default working directory")
	gracePeriod := fs.Duration("grace-period", 10*time.Second, "Shutdown grace period")
	restartPolicy := fs.String("restart-policy", "never", "Default restart policy")
	bufferLines := fs.Int("output-buffer", 10000, "Ring buffer lines per process")
	tcpAddr := fs.String("tcp-addr", ":9111", "TCP listen address")
	sockPath := fs.String("sock-path", "/var/run/tsinit.sock", "Unix socket path")

	_ = fs.Parse(os.Args[2:])

	// Configure structured logging.
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	})))

	slog.Info("tsinit starting",
		"version", version,
		"pid", os.Getpid(),
		"tcp_addr", *tcpAddr,
		"sock_path", *sockPath,
	)

	// Create process manager.
	manager := process.NewProcessManager(os.Stdout, version, *bufferLines)

	// Create supervisor.
	sup := supervisor.NewSupervisor(manager, *gracePeriod)

	// Create API server.
	srv := api.NewServer(manager, *tcpAddr, *sockPath)
	srv.SetShutdownFunc(sup.Shutdown)

	// Start API server in the background.
	go func() {
		if err := srv.Start(); err != nil {
			slog.Error("API server failed", "error", err)
			sup.Shutdown()
		}
	}()

	// Start initial processes from --process flags.
	for _, p := range processes {
		parts := strings.SplitN(p, "=", 2)
		if len(parts) != 2 {
			slog.Error("invalid --process format, expected name=command", "value", p)
			os.Exit(1)
		}
		name, cmd := parts[0], parts[1]

		config := process.ProcessConfig{
			Name:      name,
			Cmd:       cmd,
			Dir:       *dir,
			Restart:   process.RestartPolicy(*restartPolicy),
			TeeStdout: true, // boot processes always tee to stdout
		}

		status, err := manager.Start(config)
		if err != nil {
			slog.Error("failed to start process", "name", name, "error", err)
			os.Exit(1)
		}
		slog.Info("started process", "name", name, "pid", status.Pid)
	}

	// Run supervisor (blocks until shutdown signal).
	if err := sup.Run(); err != nil {
		slog.Error("supervisor error", "error", err)
		os.Exit(1)
	}

	// Gracefully shut down the API server.
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	srv.Shutdown(ctx)

	slog.Info("tsinit exited")
}

func cmdHealth() {
	sockPath := "/var/run/tsinit.sock"
	if len(os.Args) > 2 {
		sockPath = os.Args[2]
	}

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
		fmt.Fprintf(os.Stderr, "unhealthy: %v\n", err)
		os.Exit(1)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	var health struct {
		Status string `json:"status"`
	}
	_ = json.Unmarshal(body, &health)

	if health.Status == "unhealthy" {
		fmt.Fprintf(os.Stderr, "%s\n", body)
		os.Exit(1)
	}

	// For K8s probes: healthy and degraded both pass (exit 0).
	// Degraded means the supervisor is alive but some processes are down --
	// the agent can fix that without a pod restart.
	fmt.Printf("%s\n", body)
	os.Exit(0)
}

func cmdVersion() {
	fmt.Printf("tsinit %s\n", version)
}

func usage() {
	fmt.Fprintf(os.Stderr, `tsinit — container process supervisor

Usage:
  tsinit serve [flags]    Run as PID 1 supervisor
  tsinit health [socket]  Check health (for K8s probes)
  tsinit version          Print version

Flags for serve:
  --process name=command   Process to start (repeatable)
  --dir path               Default working directory
  --grace-period duration  Shutdown grace period (default: 10s)
  --restart-policy policy  Default restart policy: never|on-failure|always
  --output-buffer lines    Ring buffer lines per process (default: 10000)
  --tcp-addr addr          TCP listen address (default: :9111)
  --sock-path path         Unix socket path (default: /var/run/tsinit.sock)
`)
}
