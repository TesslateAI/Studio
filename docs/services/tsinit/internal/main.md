# tsinit main

Entrypoint: `services/tsinit/main.go`.

## Subcommand dispatch

`tsinit <subcommand>`:

| Subcommand | Purpose |
|------------|---------|
| `serve` | Long-running supervisor + API mode (the common case). |
| `version` | Print `version` (`-X main.version=<sha>` at build time). |
| anything else | Prints usage and exits with code 1. |

## `serve` flags

| Flag | Purpose |
|------|---------|
| `--http` | TCP listen address (e.g. `:8787`). |
| `--unix` | Unix socket path. |
| `--process name=command` | Repeatable. Declares a process to manage. |
| `--log-lines` | Per-process ring buffer capacity (default 2000). |
| `--grace` | Graceful shutdown window before the supervisor force-kills. |
| `--log-format` | `text` or `json` (slog handler). |

## Wiring

1. Build a `slog.Logger` with the selected handler.
2. Construct a `ProcessManager` with the declared processes.
3. Hand the manager to `supervisor.New` (PID 1 duties).
4. Hand the manager to `api.NewServer` and call `Start` on both the TCP and Unix listeners.
5. Block on the supervisor's `done` channel.

## processFlag

Custom `flag.Value` that lets `--process` appear multiple times. `Set` appends; `String` joins with `, ` for usage output.
