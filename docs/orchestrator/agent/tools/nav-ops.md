# Navigation Tools (`nav_ops/`)

Tree and content navigation tools backed by the orchestrator's `list_tree` and `execute_command` interfaces. All three are read-only and carry no scope requirement.

## Tools

| Tool | File | Purpose |
|------|------|---------|
| `glob` | `nav_ops/glob_tool.py` | Pattern match against the project tree. Uses `list_tree` with `.gitignore` applied, filters with `fnmatch` / `PurePath.match`, sorts by mtime or name. |
| `grep` | `nav_ops/grep_tool.py` | Content search via `ripgrep`. Output modes: `files_with_matches` (default), `count`, `content` (line numbers + optional context). |
| `list_dir` | `nav_ops/list_dir_tool.py` | Bounded-depth directory tree with pagination. Long names are truncated with `truncated_name` flagged. |

## Registration

`register_nav_ops_tools(registry)` wires all three. Re-exported helpers: `glob_tool`, `grep_tool`, `list_dir_tool`.

## Operational Notes

- Respect `.gitignore`: `list_tree` strips ignored paths before the tool sees candidates.
- `grep` requires `rg` on the PATH inside the project's container / dev environment.
- `list_dir` paginates to prevent blowing out agent context on dense trees.
