# Git Tools (`git_ops/`)

Read-only git inspection tools. All shell out to the standard `git` CLI via the active orchestrator's `execute_command` backend and parse output into structured dicts. None are in `TOOL_REQUIRED_SCOPES`.

## Tools

| Tool | File | Output |
|------|------|--------|
| `git_log` | `git_log_tool.py` | Structured per-commit records using a custom `--pretty=format` with `\x1e`/`\x1f` separators to avoid escaping ambiguity in commit messages. |
| `git_blame` | `git_blame_tool.py` | Line-porcelain blame: per-line commit, author, timestamp, subject, contents. |
| `git_status` | `git_status_tool.py` | Parses `git status --porcelain=v2 --branch --show-stash` into branch metadata, tracked changes with index/worktree status characters, renames/copies (with scores and original paths), untracked, ignored, and stash count. |
| `git_diff` | `git_diff_tool.py` | Four modes: `base..target`, `base only`, `staged=True` (`--cached`), or default (unstaged worktree). Parses unified diff into per-file, per-hunk records. |

## Registration

`register_git_ops_tools(registry)` registers all four.

## Notes

- All commands run in the container's working directory; respect the container's active branch.
- Output is structured, not raw text: agents consume fields like `commits[].sha`, `hunks[].lines[]`.
