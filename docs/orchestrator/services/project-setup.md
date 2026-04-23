# Project Setup Pipeline

**Directory**: `orchestrator/app/services/project_setup/`

Four-step pipeline that turns a marketplace base, git repo, template snapshot, or uploaded zip into a live project with containers persisted in the DB and files placed in the right runtime.

Replaces the older duplicated logic in `_setup_base_project`, `_setup_git_provider_project`, and `_setup_upload_project`.

## When to load

Load this doc when:
- Adding a new project source (e.g. new template snapshot type).
- Debugging container-creation from `.tesslate/config.json`.
- Fixing K8s DNS-1123 name collisions on project creation.
- Wiring a new file-placement target (local, Docker volume, K8s PVC).

## File map

| File | Purpose |
|------|---------|
| `__init__.py` | Public API: `run_setup_pipeline(...)` plus re-exports of step helpers. |
| `pipeline.py` | Orchestrates the four steps (source acquisition, file placement, container creation, config resolution). Single transaction boundary. |
| `source_acquisition.py` | Materializes project source from four origins: `template_snapshot` (btrfs reflink clone via Volume Hub, K8s only), `git_clone`, `base_copy`, `zip_upload`. |
| `file_placement.py` | Writes materialized files to the correct location per runtime: `local` host path, `docker` shared volume, `k8s` PVC via fileops. |
| `config_resolver.py` | Reads `.tesslate/config.json` from the project (via filesystem, container exec, or pre-parsed dict) into a `TesslateProjectConfig`. |
| `container_creation.py` | Translates a `TesslateProjectConfig` into persisted `Container` rows. Single source of truth for this mapping. |
| `naming.py` | DNS-1123 sanitization for K8s and Docker resource names. Used everywhere raw user names become deploy identifiers. |

## Pipeline outline

1. `source_acquisition.acquire(...)`: pick one of template-snapshot, git-clone, base-copy, zip-upload; return a temp dir or volume handle.
2. `file_placement.place(...)`: move/copy files into the runtime-appropriate location.
3. `config_resolver.resolve(...)`: parse `.tesslate/config.json` into `TesslateProjectConfig`.
4. `container_creation.create(...)`: create `Container` rows with startup commands, env, ports, directories.

## Callers

| Caller | Entry point |
|--------|-------------|
| `routers/projects.py` | `POST /api/projects`, `POST /api/projects/{id}/setup-config` |
| `services/marketplace_installer.py` | Desktop marketplace install path |
| `services/public/marketplace_install_service.py` | Cloud-mediated install from desktop |

## Related

- [config-json.md](./config-json.md): schema for `.tesslate/config.json`.
- [volume-manager.md](./volume-manager.md): template snapshot clones.
- [project-filesystem.md](./project-filesystem.md): `project_fs`, `project_patcher`, config sync.
