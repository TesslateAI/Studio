# OpenSail CI/CD Reference

Complete reference for GitHub Actions workflows, local git hooks, commit rules, and the skills lockfile.

## GitHub Actions workflows

All workflows live in `.github/workflows/`.

### `ci.yml`

Runs on pull requests to `main` or `develop` and pushes to `develop`. Concurrency group cancels in-progress runs for the same ref.

| Job | Depends on | Timeout | Steps |
|-----|------------|---------|-------|
| `backend-unit` | (none) | 10m | Python 3.11, install `tesslate-agent` + `orchestrator[dev]`, `ruff check app/`, migration linter (rejects top-level `op.create_foreign_key` / `op.drop_constraint` / `op.create_unique_constraint` / `op.alter_column` outside `batch_alter_table`), `pytest -m "unit or mocked" --maxfail=5` |
| `frontend-unit` | (none) | 10m | Node 20, `npm ci --force`, ESLint, `tsc` typecheck, `vitest --run` |
| `backend-integration` | `backend-unit` | 15m | Postgres 15 service on 5433, alembic upgrade head, `pytest tests/integration/ -m integration --junit-xml=…` |
| `e2e` | `backend-integration`, `frontend-unit` | 20m | Postgres service, install backend + frontend deps, Playwright browsers, run uvicorn + `npm run dev` in background, `npx playwright test`, always uploads `playwright-report`, uploads traces only on failure |

Environment injected into test jobs:

| Var | Value |
|-----|-------|
| `DATABASE_URL` | `postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test` |
| `SECRET_KEY` | `test-secret-key-*` per-job |
| `DEPLOYMENT_MODE` | `docker` |
| `LITELLM_API_BASE` | `http://localhost:4000/v1` (unused, tests mock) |
| `LITELLM_MASTER_KEY` | `test-key` |
| `TEST_HELPERS_ENABLED` | `1` (E2E only) |

Artifacts: integration junit XML, Playwright HTML report (30d), Playwright traces on failure (30d).

### `desktop-build.yml`

Triggers on tags `desktop-v*` or manual dispatch. Matrix build across four runners; 60m timeout per job.

| Matrix label | Platform | Rust target |
|--------------|----------|-------------|
| `macos-arm64` | `macos-latest` | `aarch64-apple-darwin` |
| `macos-x64` | `macos-13` | `x86_64-apple-darwin` |
| `windows-x64` | `windows-latest` | `x86_64-pc-windows-msvc` |
| `linux-x64` | `ubuntu-22.04` | `x86_64-unknown-linux-gnu` |

Steps: checkout with submodules, Linux system deps (webkit, appindicator, rsvg, patchelf, ssl, pkg-config) on Linux only, Rust toolchain with target, `Swatinem/rust-cache` workspaces `desktop/src-tauri`, Node 20 + `pnpm@9`, Python 3.11, install sidecar build deps (including PyInstaller), run `alembic upgrade head` against a fresh SQLite smoke DB, `python build_sidecar.py`, `cargo install tauri-cli --version '^2.0' --locked`, `cargo tauri build --target <matrix.target>`.

Signing secrets are all optional with `||''` fallbacks so unsigned builds still succeed:

| Purpose | Secrets |
|---------|---------|
| macOS codesign | `APPLE_SIGNING_IDENTITY`, `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` |
| Windows codesign | `WINDOWS_SIGNING_CERT`, `WINDOWS_SIGNING_CERT_PASSWORD` |
| Tauri updater | `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` |

Artifacts uploaded per matrix entry (`tesslate-studio-<label>`, 30d retention): `.dmg`, `.msi`, `.exe`, `.AppImage`, `.deb`.

### `deploy-production.yml`

Manual (`workflow_dispatch`) only. 45m timeout. Concurrency group `deploy-production` (no cancel).

Steps:

1. Verify `github.ref == refs/heads/main` (else fail).
2. `aws-actions/configure-aws-credentials@v4` using `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` secrets in `us-east-1`.
3. Install Terraform `~> 1.5` (no wrapper), kubectl.
4. Pull `tesslate/terraform/production` from AWS Secrets Manager into `terraform.production.tfvars`.
5. `terraform init -reconfigure -backend-config=backend-production.hcl`.
6. `terraform plan -detailed-exitcode -out=tfplan` (exit 1 fails, exit 2 marks `has_changes=true`).
7. Post plan output to GitHub Step Summary (collapsible).
8. `terraform apply -auto-approve tfplan`.
9. `./scripts/aws-deploy.sh deploy-k8s production`.
10. `./scripts/aws-deploy.sh build production`.
11. Post pod status to Step Summary via `kubectl get pods -n tesslate -o wide`.
12. Always: delete `terraform.production.tfvars`, `tfplan`, `plan_output.txt`.

### `sync-to-public.yml`

Triggers on push to `main` or manual dispatch (optional `force_push`). Runs on pinned `ubuntu-24.04`. 30m timeout. Serialized by `concurrency: sync-to-public`. Read-only `contents`, push goes through `PUBLIC_REPO_PAT` secret.

Pipeline:

1. Install pinned `yq@v4.44.3` and `git-filter-repo==2.47.0`.
2. Build three rule files from `.github/public-sync.yml`: excludes, replacements, sanitize-patterns.
3. `git filter-repo --invert-paths --paths-from-file excludes --replace-text replacements --force`.
4. Verify rewritten history: enumerate every blob once, alternation-grep against all sanitize patterns, fail with up to 20 leaking blobs + introduction commits.
5. Push to `github.com/tesslateai/studio` on branch `main`, fast-forward-only unless `force_push=true` (then `--force-with-lease`). Non-fast-forward errors emit rich diagnostics.

### `claude.yml` and `claude-code-review.yml`

Both set to `workflow_dispatch` only (triggers commented out). Use the `anthropics/claude-code-action@v1` action with `CLAUDE_CODE_OAUTH_TOKEN` secret when re-enabled.

## public-sync.yml

`.github/public-sync.yml` drives the sanitizer:

| Section | Purpose |
|---------|---------|
| `exclude` | Paths removed from the public history (`.claude/`, `.agents/`, `videos/`, `plan.txt`, `skills-lock.json`, `docs/scratch/`, `docs/proposed/`, `repomix-output.xml`, terraform backend configs + tfvars, the sync workflow itself) |
| `sanitize` | Literal string replacements applied to every blob (AWS account IDs, ECR URL, Cloudflare zone ID, production IP, terraform state bucket, EKS cluster name, internal domains). Order matters: put longer patterns before substrings |

## Husky hooks

Installed by `npm install` in `app/`.

| Hook | Script | Runs |
|------|--------|------|
| `pre-commit` | `.husky/pre-commit` | `npx lint-staged --allow-empty` |
| `commit-msg` | `.husky/commit-msg` | `npx --no -- commitlint --edit $1` |

## Commitlint

`commitlint.config.js` extends `@commitlint/config-conventional`. Allowed types:

`feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `revert`, `build`, `ci`.

`subject-case` is disabled (any case allowed). Header format is standard conventional commits: `type(scope): subject`.

## lint-staged

`lint-staged.config.js` wraps every command with `sh -c` (POSIX) or `cmd /c` (Windows) because lint-staged bypasses the shell.

| Glob | Commands |
|------|----------|
| `app/**/*.{ts,tsx}` | `cd app && npx eslint --fix <files>`, then `npx prettier --write <files>` |
| `app/**/*.{js,jsx,json,css,md}` | `cd app && npx prettier --write <files>` |
| `orchestrator/**/*.py` | `ruff check --fix`, then `ruff format` |

## skills-lock.json

Pins external Claude Code skills by computed hash. Current entries:

| Skill | Source | Source type |
|-------|--------|-------------|
| `frontend-design` | `anthropics/skills` | `github` |
| `remotion-best-practices` | `remotion-dev/skills` | `github` |

The file is excluded from `sync-to-public.yml` and should be updated whenever a skill is added or refreshed.

## Secrets reference

| Secret | Used by |
|--------|---------|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | `deploy-production.yml` |
| `PUBLIC_REPO_PAT` | `sync-to-public.yml` |
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude.yml`, `claude-code-review.yml` |
| `APPLE_*`, `WINDOWS_SIGNING_*`, `TAURI_SIGNING_*` | `desktop-build.yml` (all optional) |
