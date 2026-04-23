# internal/process

Process model + ring-buffered output + optional PTY support. Package `process`.

## Files

| File | Purpose |
|------|---------|
| `manager.go` | `ProcessManager` owns every `Process` by name. Exposes `Get`, `List`, `Start`, `Stop`, `Restart`, `Signal`, `Input`, `Logs`, `Health`. `HealthStatus` aggregates PID-1 uptime + per-process state. |
| `process.go` | `Process` FSM: `starting` -> `running` -> `exited`. Owns `*exec.Cmd`, stdout + stderr pumps into the ring buffer, exit-code capture, restart policy. |
| `pty.go` | `startWithPTY(cmd, cols, rows)` using `pty.StartWithAttrs`. Sets `Setpgid: true` (NOT `Setsid`) so the session leader's exit does not SIGHUP the whole process group. Returns the master file. |
| `output.go` | `RingBuffer`: thread-safe line-oriented circular buffer. Keeps at most `capacity` complete lines, accumulates partial lines in `partial`, drops the oldest line when full. |

## Lifecycle

1. `ProcessManager.Start(name)` looks up the declared command, builds `*exec.Cmd`, optionally wraps in PTY, sets `Setpgid`, starts pumps into the ring, transitions to `running`.
2. On child exit, pumps drain, exit code is captured, state transitions to `exited`. If restart policy says so, the manager reschedules.
3. `Stop(name, deadline)` sends SIGTERM to the process group, waits, escalates to SIGKILL after the deadline.

## Why `Setpgid` and not `Setsid`

Under `Setsid` the child becomes a session leader. When the session leader exits, the kernel sends SIGHUP to every process in the session. Fork-and-exit flows (bun launches next-server and exits; uvicorn --reload launches workers and exits) thus lose their children the moment the wrapper exits. `Setpgid: true` still gives us a process group for clean group-kill, without becoming a session leader, so the grandchildren survive.

## Ring buffer semantics

- `capacity` bounds memory: at most N lines stored.
- `partial` holds an unterminated line until its newline arrives.
- `Tail(n)` copies the last n lines under the mutex.
- Fan-out subscribers (WS) are serviced by the manager, not the buffer itself; the buffer only stores.

## Health

`HealthStatus` is serialised as JSON by `/healthz`. Clients poll it; Kubernetes uses it as the liveness and readiness probe target.
