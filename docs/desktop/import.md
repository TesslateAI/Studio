# Desktop project import

Adopting an existing on-disk directory as a Tesslate project without copying
files or running template scaffolding.

## Endpoint

`POST /api/desktop/import` — `/orchestrator/app/routers/desktop/projects.py` →
`desktop_import_project()`.

Request body (`DesktopImportBody`):

```json
{
  "name": "my-app",
  "path": "/home/me/code/my-app",
  "runtime": "local"
}
```

| Field     | Type                                          | Notes                               |
| --------- | --------------------------------------------- | ----------------------------------- |
| `name`    | `str` (1–200)                                 | Project display name.               |
| `path`    | `str` (≥1)                                    | Absolute or `~`-prefixed host path. |
| `runtime` | `"local" \| "docker" \| "k8s" \| null`        | 400 if any other string.            |

The handler builds a `ProjectCreate` (`/orchestrator/app/schemas.py`) with
`import_path=body.path` and `source_type="base"` and delegates to
`create_project_from_payload()` in `/orchestrator/app/routers/projects.py` so
validation / quota / slug handling stays on one code path.

Response:

```json
{"project": { ... ProjectSchema ... }}
```

## Schema contract

`ProjectCreate` in `/orchestrator/app/schemas.py`:

- `import_path: str | None` — when set, scaffolding is skipped and the project
  root "adopts" the directory.
- `runtime: Literal["local", "docker", "k8s"] | None` — per-project override;
  `None` resolves to the deployment-wide default (`local` under desktop mode).
- The `base_id` validator is explicitly bypassed when `import_path` is set
  (no template required for imports).

## Canonical-path dedup

In `create_project_from_payload()` at
`/orchestrator/app/routers/projects.py:530+`:

1. `os.path.expanduser(import_path)` — resolve `~`.
2. `os.path.isdir(expanded)` — 400 if the path is not a directory.
3. `canonical_source = os.path.realpath(expanded)` — collapse symlinks.
4. Query `Project` by `(owner_id, source_path == canonical_source)`; any match
   → **409 Conflict** (`"A project already exists for this path: …"`).

The canonical path is persisted on `Project.source_path`; `sync_client._project_root()`
prefers this over the orchestration-managed root so imported projects sync from
their original location.

## Materialization

After the row is inserted, `_materialize_imported_root(source_path, project_root)`
(same file, line 469) makes the managed project root point at the source:

| Platform | Strategy                                                                     |
| -------- | ---------------------------------------------------------------------------- |
| POSIX    | `os.symlink(source_path, project_root)` — managed root is a symlink.         |
| Windows  | `mkdir project_root` + write `.tesslate-source` marker file with the path.  |

Windows avoids `os.symlink` because symlink creation normally requires
elevation. The `.tesslate-source` marker is the discovery fallback.

If `project_root` already exists (`os.path.lexists`) the call is a no-op so a
repeat import against the same canonical path converges.

On materialization failure the error is logged but the project row is kept
(`environment_status` just won't flip to `active`); the import endpoint still
returns 2xx with the project. The caller can retry lifecycle operations.

## Status-code map

| Status | Condition                                         |
| ------ | ------------------------------------------------- |
| 200    | Import succeeded — body is `{project: {...}}`.    |
| 400    | `path` is not a directory, or `runtime` invalid.  |
| 409    | Another project already adopts the same `realpath`.|
| 422    | Pydantic validation error (name length, etc.).    |
| 500    | DB write / slug-collision exhaustion.             |

## Related

- `/docs/desktop/runtimes.md` — per-project runtime dispatch.
- `/docs/desktop/sync.md` — push/pull treats `source_path` as project root.
- `/docs/desktop/unified-workspace.md` — `Directory` rows co-exist with imported projects.
