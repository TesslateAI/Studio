# Orchestrator Utilities (`app/utils/` and `app/types/`)

## `app/utils/`

| File | Purpose |
|------|---------|
| `__init__.py` | Re-exports `SearchReplaceEdit`, `apply_multiple_edits`, `apply_search_replace`, `extract_edits_by_file`, `extract_search_replace_blocks`, `is_full_file_format`, `is_search_replace_format` from `code_patching.py`. |
| `async_fileio.py` | Async file I/O wrappers so long-running operations don't block the event loop. `rmtree_async(path, progress_callback)` is the main helper. |
| `async_subprocess.py` | Async `subprocess` replacement. `SubprocessResult` dataclass mirrors `subprocess.CompletedProcess`. Use this instead of `subprocess.run()` anywhere in the API path. |
| `code_patching.py` | AI-driven editing utilities: Aider-style search/replace blocks, unified diff support, fuzzy matching with progressive fallback. Shared by agent edit tools and by any router that applies model-proposed patches. |
| `resource_naming.py` | Centralized name generators for filesystem paths, container/pod names, URLs, and DB queries. UUID-based to be non-enumerable, collision-free, distributed-safe, and URL-safe. |
| `slug_generator.py` | Human-readable slug generation following Vercel/Railway/Render patterns: `my-awesome-app-k3x8n2` for projects, `ernest-k3x8n2` for usernames. Non-enumerable via hash suffix. |

## `app/types/`

| File | Purpose |
|------|---------|
| `__init__.py` | Re-exports `GUID`. |
| `guid.py` | Dialect-agnostic UUID column type. `UUID` native on Postgres, `CHAR(36)` on SQLite and other backends. Python values are always `uuid.UUID` so application code is identical across deployments (cloud Postgres / desktop SQLite). |
| `CLAUDE.md` | Existing context for the type system. |

## Usage Guidelines

- Never call `subprocess.run` from the API path; use `async_subprocess`.
- Never call `os.remove` / `shutil.rmtree` synchronously inside request handlers; use `async_fileio.rmtree_async`.
- Always use `GUID` for primary keys on new models; SQLAlchemy's native `UUID` breaks desktop SQLite.
- Generate slugs with `slug_generator`, never hand-roll; the hash suffix is load-bearing for non-enumerability.
- `code_patching.apply_search_replace` is the shared engine behind `patch_file`, `multi_edit`, and `apply_patch`; do not duplicate the matcher elsewhere.

## Related

- `docs/orchestrator/agent/tools/file-ops.md`: how agent edit tools consume `code_patching`.
- `docs/orchestrator/models/README.md`: models using `GUID`.
