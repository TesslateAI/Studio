# services/

Business-logic services used by routers, agents, and workers.

## runtime_probe.py

`RuntimeProbe` performs bounded, non-blocking availability checks for execution
runtimes (local / docker / remote k8s). Each probe returns a `ProbeResult`
dataclass and never raises — failures are surfaced as `ok=False` with a
human-readable `reason`.

- Docker probe shells `docker info --format json` with a 3s timeout and caches
  the result for 30 seconds via a monotonic clock.
- The k8s remote probe is currently a stub returning
  `"Cloud pairing required"`; it will integrate with the pairing state once
  that lands.
- Access via the process-wide singleton `get_runtime_probe()`.

Used by `app/routers/desktop.py` to power the tray/runtime-probe endpoints.
