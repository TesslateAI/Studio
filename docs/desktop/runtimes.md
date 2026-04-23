# Desktop runtimes

Per-project dispatch between `local`, `docker`, and `k8s` (remote/cloud) backends,
plus the tray-facing availability probes that gate the UI's runtime picker.

## Runtime dispatch

`Project.runtime` (`"local" | "docker" | "k8s" | None`) is the source of truth.
Resolution lives in `OrchestratorFactory.resolve_for_project(project)` at
`/orchestrator/app/services/orchestration/factory.py`:

| `Project.runtime` | Orchestrator                            |
| ----------------- | --------------------------------------- |
| `"local"`         | `LocalOrchestrator` (subprocess + FS)   |
| `"docker"`        | `DockerOrchestrator`                    |
| `"k8s"`           | `KubernetesOrchestrator` (remote K8s: pending pairing wiring) |
| `None`            | Deployment-wide default; `desktop` → `local` |

Under `DEPLOYMENT_MODE=desktop` any row without an explicit runtime resolves
to `LocalOrchestrator`.

## `$OPENSAIL_HOME` layout

Resolver: `/orchestrator/app/services/desktop_paths.py` (`resolve_opensail_home`,
`ensure_opensail_home`). Precedence: explicit setting → `$OPENSAIL_HOME`
env var → OS default (`~/Library/Application Support/OpenSail` on macOS,
`%APPDATA%/OpenSail` on Windows, `$XDG_DATA_HOME/tesslate-studio` on
Linux).

```
$OPENSAIL_HOME/
├── projects/{slug}-{uuid}/      # local-runtime project roots
├── cache/
│   ├── cloud_token.json         # paired bearer (token_store)
│   ├── marketplace.json         # stale-while-revalidate catalog cache
│   └── ports.json               # local-runtime port assignments
├── logs/
├── agents/{slug}/manifest.json  # installed marketplace agents
├── skills/{slug}/manifest.json
├── bases/{slug}/manifest.json
└── themes/{slug}/manifest.json
```

`_get_project_root(project)` at `/orchestrator/app/services/orchestration/local.py`
returns `$OPENSAIL_HOME/projects/{slug}-{id}` under desktop mode, else
falls back to `$PROJECT_ROOT` then `os.getcwd()`.

## Port allocator (local runtime)

`PortAllocator` at `/orchestrator/app/services/orchestration/local_ports.py`
reserves host TCP ports per `(project_id, container_name)` from
`settings.local_port_range_start`–`_range_end` (default `42000`–`42999`).

- Persists to `$OPENSAIL_HOME/cache/ports.json` (atomic `tmp + os.replace`).
- Stores owning `pid`; `reclaim_dead(pid_check=_pid_alive)` frees ports whose
  owner is gone.
- `allocate()` is idempotent for existing pairs.
- `RuntimeError` when the range is exhausted.

Process-wide singleton via `get_default_allocator()`.

## Runtime probe

`RuntimeProbe` at `/orchestrator/app/services/runtime_probe.py` — non-blocking
availability checks. Every probe returns
`ProbeResult(ok: bool, reason: str | None)` and **never raises**; unexpected
errors surface as `ok=False` with a `reason`.

| Probe                   | Behavior                                                       |
| ----------------------- | -------------------------------------------------------------- |
| `local_available()`     | Always `ok=True` — the orchestrator process itself.            |
| `docker_available()`    | Shells `docker info --format json`, 3s timeout, 30s cache.     |
| `k8s_remote_available()`| Currently stubbed: `ok=False, reason="Cloud pairing required"`.|

Docker cache uses `time.monotonic()` and an `asyncio.Lock` to dedupe dogpile.
Server-side errors (`ServerErrors` in the JSON payload) count as unreachable.
Access via `get_runtime_probe()` singleton.

## Tray endpoints

Router: `/orchestrator/app/routers/desktop/tray.py`. Auth: `current_active_user`.

| Method | Path                        | Response shape |
| ------ | --------------------------- | -------------- |
| `GET`  | `/api/desktop/runtime-probe`| `{local: ProbeResult, docker: ProbeResult, k8s: ProbeResult}` |
| `GET`  | `/api/desktop/tray-state`   | `{runtimes: {local, docker, k8s}, running_projects: [], running_agents: []}` |

`ProbeResult` serializes as `{"ok": bool, "reason": str | null}`. `_safe_probe()`
wraps each probe coroutine so the endpoint is guaranteed a well-formed payload
even when a probe implementation raises — the desktop shell must never see a
5xx here.

## Related

- `/docs/desktop/cloud.md` — pairing state that the k8s-remote probe will consume.
- `/docs/orchestrator/orchestration/CLAUDE.md` — cross-backend orchestrator contract.
