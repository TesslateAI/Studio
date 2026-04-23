# tsinit Agent Context

## Purpose

`services/tsinit/` is OpenSail's in-container init + process supervisor, written in Go. It runs as PID 1 inside every user project pod:

- Forwards signals to children.
- Reaps zombies via `SIGCHLD`.
- Starts and monitors the set of user processes declared via `--process name=cmd`.
- Exposes a REST API (HTTP + Unix socket) for start, stop, restart, status, log tail, and one-shot `run`.
- Exposes a WebSocket stream for live stdout / stderr per process.
- Optionally attaches a PTY per process so full terminal features (colour, readline) work.

Load this context for anything that touches how user containers start, stream logs, or accept restart / run commands from the orchestrator.

## Source tree

| Path | Purpose |
|------|---------|
| `main.go` | CLI entrypoint: `tsinit serve ...`. Parses `--process` flags, sets up logger, wires supervisor + API. |
| `internal/api/server.go` | HTTP server on TCP + Unix socket. Registers routes. |
| `internal/api/handlers.go` | REST handlers: health, processes list, start, stop, restart, logs, input, signal. |
| `internal/api/websocket.go` | WebSocket upgrader + per-process subscription logic. Atomic counter for unique subscriber IDs across reconnects. |
| `internal/api/run.go` | One-shot `/run` endpoint: fork a short-lived command, stream output back over WS. |
| `internal/process/manager.go` | `ProcessManager`: holds every managed `Process`, exposes health, dispatch. |
| `internal/process/process.go` | `Process` FSM: `starting`, `running`, `exited`, restart policy, log ring buffer wiring. |
| `internal/process/pty.go` | `startWithPTY`: uses `pty.StartWithAttrs` with `Setpgid` (not `Setsid`) so fork-and-exit children don't receive SIGHUP when the shell exits. |
| `internal/process/output.go` | Thread-safe line-oriented ring buffer. |
| `internal/supervisor/supervisor.go` | PID 1 supervisor: signal handling, zombie reaping, graceful shutdown. |
| `integration/integration_test.go` | End-to-end tests against a built binary. |
| `integration/Dockerfile` | Image that bakes `tsinit` into the test rootfs. |

## Related contexts

| Context | When to load |
|---------|--------------|
| `docs/orchestrator/orchestration/CLAUDE.md` | How the K8s orchestrator talks to tsinit for starting user processes. |
| `docs/services/btrfs-csi/CLAUDE.md` | Sibling Go service: storage stack. |
| `docs/apps/CLAUDE.md` | Tesslate Apps: apps run as tsinit-managed processes inside app-instance pods. |

## Key design choices

- PID 1 uses `Setpgid`, not `Setsid`. `pty.StartWithSize` (and by extension plain `Setsid`) creates a new session; when the session leader exits the kernel sends SIGHUP to every process in the session, killing fork-and-exit children (bun -> next-server). `Setpgid` gives group-kill without the SIGHUP.
- Both TCP and Unix socket listeners so in-pod clients (curl from sidecars, orchestrator exec) can skip the network stack.
- WebSocket upgrader accepts all origins: access control is enforced at the ingress layer.
- Line-based ring buffer, not byte ring. Keeps logs readable for humans and preserves line boundaries for WS subscribers that join mid-stream.

## When to load

Open this context before editing anything under `services/tsinit/` or any manifest that wires tsinit into a project pod.
