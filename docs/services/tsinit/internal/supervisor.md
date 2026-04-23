# internal/supervisor

PID 1 duties. Package `supervisor`.

## File

`supervisor.go`: `Supervisor` struct with `manager`, `gracePeriod`, `shutdownCh`, `doneCh`.

## What PID 1 must do

1. Reap zombies. Any orphaned child re-parented to PID 1 is reaped via `wait4` on `SIGCHLD`. Without this the container slowly accumulates defunct processes.
2. Forward signals. `SIGTERM` and `SIGINT` from kubelet or docker stop need to trigger an ordered shutdown.
3. Graceful shutdown. On shutdown, the supervisor stops every managed process with a deadline (`--grace`), then force-kills stragglers and exits.

## Flow

```
goroutine 1: signal loop
  SIGCHLD -> for { wait4(-1, WNOHANG) }     // reap zombies
  SIGTERM / SIGINT -> close(shutdownCh)

main goroutine:
  <-shutdownCh
  manager.StopAll(gracePeriod)
  close(doneCh)
```

## Why not `tini`

tsinit needs to know the lifecycle of individual managed processes (for health, logs, restart), so it's tightly coupled to the process manager. Swapping in `tini` would lose that integration.
