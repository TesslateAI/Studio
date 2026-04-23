# Project Filesystem Services

Helpers for locating, patching, and synchronizing project files outside the orchestrator exec path. Used by routers, background tasks, and CLI tools that need direct filesystem access.

## When to load

Load this doc when:
- A background task needs to read or write project files without going through the orchestrator.
- Debugging `.tesslate/config.json` drift between DB and filesystem.
- Wiring a new import-from-GitHub patch (e.g. framework config fix).
- Working on node-export interpolation (`${HOST}`, `${PORT}`, etc.).

## File map

| File | Purpose |
|------|---------|
| `project_fs.py` | Unified project-path resolver. Given a project, returns the correct filesystem path per runtime (local host path, Docker shared-volume subpath, K8s volume mount). Single source of truth for direct I/O. |
| `project_patcher.py` | Detects and patches imported GitHub projects to work on OpenSail. Fixes missing configs, framework-incompatible settings, wrong ports, etc. |
| `config_sync.py` | Bidirectional sync between `.tesslate/config.json` and DB. `build_config_from_db()` reads canvas state into config; `apply_config_to_db()` imports config changes back into Container/connection rows. |
| `export_resolver.py` | Resolves `${}` interpolation in node exports. Each node's exports reference only the node's own properties (`${HOST}`, `${PORT}`, `${URL}`, etc.). |
| `base_config_parser.py` | Parser for `.tesslate/config.json`. See [runtime-support.md](./runtime-support.md) for the primary entry. Listed here because it is the read-side of the filesystem contract. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| `routers/projects.py` (`setup-config`) | `config_sync`, `base_config_parser` |
| `routers/git.py` (import) | `project_patcher`, `project_fs` |
| Background agents and CLI tools | `project_fs` |
| `services/orchestration/*` | `export_resolver` when building connection env vars |

## Related

- [project-setup.md](./project-setup.md): pipeline that initially populates project files.
- [config-json.md](./config-json.md): the config-file schema.
- [runtime-support.md](./runtime-support.md): `base_config_parser` detail.
