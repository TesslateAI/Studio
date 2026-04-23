# OpenSail CI/CD

## Purpose

Context for GitHub Actions workflows, git hooks, commit conventions, lint-staged configuration, and the skills lockfile.

## Key files

| Path | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | Main CI: lint, unit, integration, Playwright E2E |
| `.github/workflows/desktop-build.yml` | Tauri + sidecar matrix build (mac/win/linux) |
| `.github/workflows/deploy-production.yml` | Manual AWS EKS deploy |
| `.github/workflows/sync-to-public.yml` | Mirror private repo to `tesslateai/studio` with filter-repo sanitize |
| `.github/workflows/claude.yml` | Claude Code action (currently `workflow_dispatch` only) |
| `.github/workflows/claude-code-review.yml` | Claude code review action (currently `workflow_dispatch` only) |
| `.github/public-sync.yml` | Exclude + sanitize rules consumed by `sync-to-public.yml` |
| `.github/ISSUE_TEMPLATE/` | Issue templates |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR template |
| `.husky/pre-commit` | Runs `lint-staged` |
| `.husky/commit-msg` | Runs `commitlint` |
| `commitlint.config.js` | Conventional commit type enum |
| `lint-staged.config.js` | Per-file lint/format rules (shell-wrapped for Windows compat) |
| `skills-lock.json` | Pinned marketplace skill hashes |

## Conventions

- Branch `main` is production; PRs target `main` or `develop`.
- `ci.yml` fans out: `backend-unit` + `frontend-unit` run in parallel, `backend-integration` gates on backend-unit, `e2e` gates on both integration + frontend-unit.
- `desktop-build.yml` triggers on tags matching `desktop-v*` or manual dispatch.
- `deploy-production.yml` is manual-only and enforces `github.ref == refs/heads/main`.
- `sync-to-public.yml` uses `PUBLIC_REPO_PAT` (never `GITHUB_TOKEN`) and pinned tool versions; non-fast-forward pushes fail the job unless `force_push=true`.

## Related contexts

- `/docs/testing/CLAUDE.md` for the test suites these workflows run
- `/docs/infrastructure/kubernetes/CLAUDE.md` for the deploy-production target
- `/docs/desktop/CLAUDE.md` for desktop-build context
- `/docs/guides/aws-deployment.md` for manual AWS deploy walkthrough
