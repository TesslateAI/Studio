# Git Components

Git-specific UI in `app/src/components/git/`. General git operations live in `components/panels/GitHubPanel.tsx` and `components/modals/` (GitCommitDialog, GitHubConnectModal, GitHubImportModal, RepoImportModal).

## File Index

| File | Purpose |
|------|---------|
| `git/GitHistoryViewer.tsx` | Commit-history list for a project. Fetches via `gitApi.getHistory(projectId)`, shows author, date, SHA, message. Paginates client-side |

## Related Docs

- `docs/app/components/panels/CLAUDE.md` – GitHubPanel (commit, push, pull UX)
- `docs/app/components/modals/CLAUDE.md` – commit dialog, import modal, connect modal
- `docs/app/api/git-api.md` – git API walkthrough
