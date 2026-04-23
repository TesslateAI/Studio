# tsinit

OpenSail's in-container init system and process supervisor. Ships as a single static Go binary baked into the devserver and app-instance images.

## Why tsinit

Every user project pod needs:

1. A PID-1 capable of reaping zombies.
2. A way for the orchestrator to start, stop, restart, and stream logs for each declared process.
3. Optional PTY support so tools that draw TUIs work correctly.
4. Fast in-container IPC (Unix socket) for sidecars and the orchestrator exec path.

`tsinit` is that component.

## Usage

```bash
tsinit serve \
  --http :8787 \
  --unix /run/tsinit.sock \
  --process frontend='bun run dev' \
  --process backend='uvicorn app:app' \
  --log-lines 2000
```

## Structure

| Layer | Doc |
|-------|-----|
| CLI entrypoint (`main.go`) | [internal/main.md](internal/main.md) |
| API server (`internal/api/`) | [internal/api.md](internal/api.md) |
| Process manager (`internal/process/`) | [internal/process.md](internal/process.md) |
| Supervisor (`internal/supervisor/`) | [internal/supervisor.md](internal/supervisor.md) |
| Integration tests (`integration/`) | [internal/integration.md](internal/integration.md) |

## HTTP surface

| Method + path | Purpose |
|---------------|---------|
| `GET /healthz` | Aggregate health: manager uptime, per-process state. |
| `GET /processes` | List managed processes. |
| `POST /processes/{name}/start` | Start if not running. |
| `POST /processes/{name}/stop` | Graceful stop with deadline. |
| `POST /processes/{name}/restart` | Stop + start. |
| `POST /processes/{name}/signal` | Send an arbitrary signal. |
| `POST /processes/{name}/input` | Write to stdin. |
| `GET /processes/{name}/logs?tail=N` | Read ring-buffer tail. |
| `GET /ws/logs/{name}` | WebSocket live stream. |
| `POST /run` | One-shot subprocess; output streamed over WS response. |

## Listeners

| Listener | Address | Notes |
|----------|---------|-------|
| HTTP TCP | configurable (default `:8787`) | Used by the orchestrator from outside the container via port-forward or in-cluster service. |
| HTTP Unix | configurable (`/run/tsinit.sock`) | Fast in-container IPC for sidecars. |

Both share the same `http.Handler`.

## Build

`go build -ldflags "-X main.version=$(git describe)" -o tsinit ./` from the module root (`services/tsinit/`).
