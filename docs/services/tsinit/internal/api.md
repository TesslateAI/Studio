# internal/api

HTTP + WebSocket surface for tsinit. Package `api`.

## Files

| File | Purpose |
|------|---------|
| `server.go` | `Server` struct; binds the same `http.Mux` on both a TCP listener and a Unix socket listener. Handles graceful shutdown. |
| `handlers.go` | REST handlers: health, process list, start, stop, restart, signal, input, log tail. |
| `websocket.go` | `wsUpgrader` (accepts all origins), per-process WS subscriptions, `wsCounter` atomic for unique subscriber IDs across reconnects. |
| `run.go` | `/run` one-shot: fork a short command, pipe its combined output through a WebSocket response. |

## Dual-listener model

`NewServer(manager, logger)` returns a struct with both `Start(ctx)` (TCP) and `StartUnix(ctx, path)` (Unix). Both mount the same handler so clients can pick the path of least resistance:

- Sidecars: Unix socket, zero network overhead.
- Orchestrator: TCP via port-forward or in-cluster service.

## WebSocket subscription

On `GET /ws/logs/{name}`:

1. Upgrade with `wsUpgrader`.
2. Allocate a subscriber ID via `wsCounter.Add(1)`.
3. Register a fan-out consumer on the process's output ring.
4. Replay the last N lines (tail), then stream new lines.
5. Clean up the subscription on disconnect or process exit.

Access control runs at the ingress layer, so `CheckOrigin` is permissive.

## `/run`

Accepts `{command, args[], env, cwd, tty}`. If `tty=true`, launches via PTY (see `pty.go`). Output is streamed over the caller's WebSocket response. Used by the orchestrator for ad-hoc commands that don't warrant a managed process.
