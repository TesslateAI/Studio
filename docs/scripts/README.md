# Scripts Reference

> Every script in `scripts/` is documented here. Scripts are grouped by subdirectory; each row names the file, the invocation, and what it does.

## Root-level helpers

| Script | Purpose |
|--------|---------|
| `scripts/README.md` | Legacy in-tree README (older structure); this doc supersedes it. |
| `scripts/README_ANALYZER.md` | User guide for `analyze_codebase.py`: unused code, duplicates, complexity. |
| `scripts/analyze_codebase.py` | AST (Python) + regex (TS/JS) analyzer. Flags unused functions, duplicate files, and high-complexity modules. Writes reports under `analysis-output/`. |
| `scripts/analyze_deps.py` | Builds a dependency graph over orchestrator/app sources and writes JSON for downstream tooling. |
| `scripts/build_mermaid.py` | Turns the JSON from `analyze_deps.py` into a Mermaid dependency diagram. |
| `scripts/check_bases.py` | Prints current marketplace bases in the dev database. Sanity check after running seeds. |
| `scripts/create_admin.py` | Create or promote an admin user in the orchestrator DB. |
| `scripts/diagnose_container_return.py` | Times the preview-URL hand-back for a just-started project. Used to debug slow container returns. |
| `scripts/fix_uninitialized_containers.py` | Backfills Container rows whose `volume_name` is NULL so they can start. |
| `scripts/generate-favicons.js` | Node helper: regenerate favicon PNGs from the SVG source. |
| `scripts/generate-secret-key.py` | Prints a 32-byte hex string for use as `SECRET_KEY`. |
| `scripts/aws-deploy.sh` | AWS EKS deploy wrapper: Terraform plan/apply, ECR image builds, kustomize apply. See the `aws-deploy` skill for workflow details. |
| `scripts/clear-shell-env.sh` | Unsets shell env vars that would otherwise shadow `.env`. Run if a local env var is leaking into the orchestrator. |
| `scripts/docker.sh` | Docker Compose swiss-knife: `up`, `down`, `logs`, `rebuild`, clean-slate reset. See the `docker-dev` skill. |
| `scripts/install-macos.sh` | Interactive macOS installer: Docker, Node, Python, env bootstrap, first run. |
| `scripts/kctx.sh` | Prints available kubectl contexts. Does NOT switch context (context switching is banned; always pass `--context=<name>` explicitly per [CLAUDE.md](../../CLAUDE.md)). |
| `scripts/manage_user.sh` | Create test users and upgrade subscription plans across dev/beta/prod. |
| `scripts/minikube.sh` | Minikube swiss-knife: start, stop, load image, deploy overlay, tail logs. See the `minikube-dev` skill. |
| `scripts/notify.sh` | Send a Slack notification (extensible to other providers). Used by local cron jobs and other skills. See the `notify` skill for credential setup. |
| `scripts/regenerate_user_keys.py` | Regenerate every user's LiteLLM key to drop per-key model allowlists. One-shot after widening team model access. |
| `scripts/secrets_migrate_audit.py` | Audit Container rows for env vars that look like ambiguous or unmigrated secret references. |
| `scripts/seed_all_apps.sh` | Build seed-app external images, roll the minikube backend, and seed every Tesslate App (7 apps). |
| `scripts/test.sh` | Convenience wrapper for the pytest suite. |
| `scripts/test_container_e2e.py` | End-to-end test: create project, start container, hit dev URL, tear down. |
| `scripts/test_nextjs_e2e.py` | Next.js-specific lifecycle test: create, start, build, preview URL assertion. |
| `scripts/timing_test.py` | Timing harness for Next.js 16 project creation and startup (run inside the backend pod). |

## deployment/

Local development scripts. See [deployment.md](deployment.md) for full details.

| Script | Purpose |
|--------|---------|
| `deployment/build-dev-image.sh` | Bash: build `tesslate-devserver:latest`, optional `--push` and `--no-cache`. |
| `deployment/build-dev-image.bat` | Windows equivalent of `build-dev-image.sh`. |
| `deployment/run-backend.sh` | Start the orchestrator (`uvicorn app.main:app --reload`). |
| `deployment/run-frontend.sh` | Start the React dev server (`npm run dev`). |
| `deployment/setup-docker-dev.sh` | Bash setup: clone env, install deps, bring up compose stack. |
| `deployment/setup-docker-dev.bat` | Windows equivalent of `setup-docker-dev.sh`. |
| `deployment/start-all-with-traefik.bat` | Windows: run services natively with Traefik in Docker. Preferred hybrid dev mode. |
| `deployment/start-all.bat` | Windows legacy launcher without Traefik. Preview containers do not route; use `start-all-with-traefik.bat` instead. |
| `deployment/verify-env.bat` | Windows CMD env checker. |
| `deployment/verify-env.ps1` | PowerShell env checker. |
| `deployment/verify_env.py` | Cross-platform env checker (Python). Canonical: prefer this over the batch/ps1 duplicates. |

## kubernetes/

| Script | Purpose |
|--------|---------|
| `kubernetes/manage-k8s.sh` | Deploy, update, scale, log-tail, and backup against the current kubectl context. Always invoke with an explicit `--context=` flag (see [CLAUDE.md](../../CLAUDE.md)). |
| `kubernetes/cleanup-k8s.sh` | Two-mode cleanup: (1) delete user project namespaces only, (2) wipe database too. Destructive; no `--dry-run`. |

## litellm/

Scripts for managing LiteLLM teams, virtual keys, and model access. See [litellm.md](litellm.md).

| Script | Purpose |
|--------|---------|
| `litellm/check_models.py` | Fetch LiteLLM URL + master key from the beta cluster, list models, and hit each with a tiny completion to verify reachability. |
| `litellm/create_key_direct.py` | Create a LiteLLM key directly, skipping the user creation step (for spot testing). |
| `litellm/create_litellm_team.py` | Create the `internal` LiteLLM team used for access control on default models. |
| `litellm/create_virtual_key_for_user.py` | Issue a virtual LiteLLM key for one named user. |
| `litellm/fix_user_keys.py` | Create LiteLLM keys for every orchestrator user missing one. |
| `litellm/migrate_litellm_keys.py` | One-shot migration: generate keys for pre-existing users after enabling per-user keys. |
| `litellm/setup_user_litellm.py` | Add users to the `internal` team and refresh their keys. |
| `litellm/test_litellm_endpoints.py` | Probe LiteLLM endpoint permutations to discover the working URL. |
| `litellm/update_litellm_models.py` | Rewrite every user key to allow the current `LITELLM_DEFAULT_MODELS` set. |
| `litellm/update_litellm_team.py` | Update user keys to use the `internal` team / access group. |

## migration/unified-snapshots/

One-shot production migration from the old linear CAS layer format to the new unified snapshot DAG. See [migration.md](migration.md).

| File | Purpose |
|------|---------|
| `migration/unified-snapshots/MIGRATION_GUIDE.md` | Human-facing playbook for the migration. |
| `migration/unified-snapshots/README.md` | Quick summary of the scripts and order. |
| `migration/unified-snapshots/backup_s3.sh` | Server-side copy the entire `btrfs-snapshots` bucket (blobs, index, manifests, tombstones). Non-destructive. |
| `migration/unified-snapshots/convert_manifests.py` | Rewrite CAS manifests from linear Layer format to DAG Snapshot format. |
| `migration/unified-snapshots/rollback.sh` | Restore the bucket from the backup created by `backup_s3.sh`. |
| `migration/unified-snapshots/run_migration.sh` | Phase-by-phase orchestrator for the full migration. |

## migrations/

Standalone column-add scripts predating Alembic adoption for marketplace tables. New schema work should go through `orchestrator/alembic/versions/` instead.

| Script | Purpose |
|--------|---------|
| `migrations/add_avatar_url_column.py` | Add `avatar_url` to `marketplace_agents`. |
| `migrations/add_tool_configs_column.py` | Add `tool_configs` JSON column to `marketplace_agents`. |

## seed/

Thin wrappers around canonical seeders in `orchestrator/app/seeds/`. Run via `docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/<script>.py` or inside a shell on the orchestrator pod. See [seed.md](seed.md).

| Script | Purpose |
|--------|---------|
| `seed/bump_litellm_budgets.py` | Raise every user's LiteLLM budget cap to $10,000 (one-shot after defaults changed). |
| `seed/delete_all_agents.py` | Delete every marketplace agent plus user-agent associations. |
| `seed/delete_seeded_agents.py` | Delete only agents that came from the seed data (leaves user-owned agents alone). |
| `seed/seed_community_bases.py` | Seed community marketplace bases. |
| `seed/seed_deployment_targets.py` | Seed Vercel/Netlify/Cloudflare marketplace deployment targets. |
| `seed/seed_marketplace_agents.py` | Seed the first-party marketplace agents. |
| `seed/seed_marketplace_bases.py` | Seed the initial marketplace bases. |
| `seed/seed_mcp_servers.py` | CLI wrapper around the MCP server catalog seeder (runs automatically at backend startup too). |
| `seed/seed_opensource_agents.py` | Seed open-source marketplace agents (community/OSS entries). |
| `seed/seed_skills.py` | Seed marketplace skills (15+ skill bodies). |
| `seed/seed_test_scenarios.py` | Create a test ultra-plan user with projects that exercise timeline DAG, snapshots, and sync. |
| `seed/seed_themes.py` | Seed themes from the bundled JSON files in `orchestrator/app/seeds/themes/`. |
| `seed/simulate_activity.py` | Fire random file writes, reads, snapshots, syncs, and forks at the test user's projects to populate real data. |
| `seed/update_tesslate_agent.py` | Update the existing Tesslate Agent row to the open-source methodology prompt and toolset. |

## terraform/

| File | Purpose |
|------|---------|
| `terraform/QUICKSTART.md` | Fast path for running Terraform against a new environment. |
| `terraform/README.md` | Full reference for the AWS stack layout and variables. |
| `terraform/secrets.sh` | Upload, download, and view `terraform.{env}.tfvars` via AWS Secrets Manager. Avoids checking secrets into git. |

## utilities/

| Script | Purpose |
|--------|---------|
| `utilities/check_agents.py` | Dump every `MarketplaceAgent` row to stdout. Quick sanity check after seeding. |
| `utilities/cleanup-local.py` | Complete local Docker cleanup: remove containers, projects, and wipe database data. Destructive. |
| `utilities/generate_tool_info.py` | Instantiate an `IterativeAgent` and dump the full `_get_tool_info()` output for docs. |
| `utilities/make_user_admin.py` | Flip the `is_admin` flag on a user by username. |
| `utilities/test_all_endpoints.sh` | Smoke-test every API endpoint. |
| `utilities/verify_agent_abstraction.py` | Verify the agent factory can build every agent type from its DB row. |

## See also

- [deployment.md](deployment.md): deployment script details
- [seed.md](seed.md): seed script details
- [litellm.md](litellm.md): LiteLLM operations
- [migration.md](migration.md): unified-snapshots migration playbook summary
- [kubernetes.md](kubernetes.md): K8s management helpers
- [terraform.md](terraform.md): Terraform state and secrets
- [utilities.md](utilities.md): misc admin and test helpers
