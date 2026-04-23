# tsinit integration tests

Path: `services/tsinit/integration/`.

## Files

| File | Purpose |
|------|---------|
| `integration_test.go` | End-to-end: builds the tsinit binary, launches it inside a container, exercises start / stop / restart / logs / WS / run. Verifies PID 1 behaviours: zombie reaping, signal forwarding, graceful shutdown with deadline, PTY vs non-PTY children. |
| `Dockerfile` | Test rootfs. Installs Go build output at `/usr/local/bin/tsinit` and a few test fixtures (sleep, echo-loop, fork-and-exit harness). |

## How it runs

`go test ./integration/...` inside the repo-level CI image. The test harness skips if docker is unavailable.
