# OpenSail Testing

Reference for every test suite in the repo, how to run it, and where the fixtures live.

See `TESTING.md` at the repo root for the short runbook; this page is the knowledge graph entry.

## Test categories

| Category | Pytest marker | Where | Typical speed |
|----------|---------------|-------|---------------|
| Unit / mocked | `unit`, `mocked` | `orchestrator/tests/**` non-integration tests | ~1 to 2s |
| Integration | `integration` | `orchestrator/tests/integration/` | ~10 to 20s |
| E2E | `e2e` | `app/tests/e2e/` (Playwright) | ~30 to 60s |
| Oracle (golden) | `oracle` | `orchestrator/tests/agent/oracle/`, `tests/fixtures/oracle_scenarios/` | Fast |
| LLM | `llm` | `orchestrator/tests/agent/llm/` (empty scaffold today) | Slow, costs money |
| Soak / chaos | (none) | `orchestrator/tests/soak/` | Hours |
| Smoke | (module level) | `desktop/tests/smoke_test.py` | Seconds |
| Go integration | `go test` build tags | `services/btrfs-csi/integration/` | Minutes |

## Running tests per subsystem

### Backend (orchestrator)

```bash
cd orchestrator

# Unit + mocked only (fast, no DB)
pytest -m "unit or mocked"

# Integration (requires Postgres on 5433)
docker compose -f ../docker-compose.test.yml up -d
alembic upgrade head
pytest tests/integration/ -m integration

# Single file or single test
pytest tests/routers/test_chat_ws_authz.py -k "test_name" -vv

# Oracle / golden tests
pytest -m oracle tests/agent/oracle/

# Collect only (no execution)
pytest --collect-only tests/
```

### Frontend (app)

```bash
cd app

# Vitest unit tests (watch)
npm run test

# Vitest single run (CI mode)
npm run test -- --run

# Playwright E2E
npm run test:e2e           # headless
npm run test:e2e:headed    # visible browser
npm run test:e2e:ui        # UI runner
npx playwright show-report # view last HTML report
```

Colocated vitest tests live next to the component (`*.test.ts` / `*.test.tsx`); the `__tests__/` folder is used for grouped app-level suites (apps marketplace, install wizards, iframe host, etc.).

### tesslate-agent package

```bash
cd packages/tesslate-agent
pytest tests/
```

Hierarchy:

```
tests/
  agent/
    test_tesslate_agent.py    # core agent loop
    test_litellm_adapter.py   # model adapter
    test_registry.py          # tool registry
    tools/
      file_ops/   # read_write, edit, apply_patch, undo, read_many_files, view_image, edit_history
      git_ops/    # status, log, diff, blame (shared conftest)
      shell_ops/  # bash, session, python_repl, background, write_stdin
      nav_ops/    # list_dir, glob, grep
      planning_ops/  # update_plan
      delegation_ops/
      memory_ops/
      web_ops/    # search, fetch
  orchestration/test_local_orchestrator.py
  cli/test_runner_smoke.py
```

### btrfs CSI (Go)

```bash
cd services/btrfs-csi/integration

# Standard integration tests inside a privileged Docker container
make test

# Load tests (larger pool, longer timeout)
make load-test
```

Covers: bundle round-trip, dirty tracking, drain/parallel, end-to-end lifecycle, file ops gRPC, garbage collector, hub resolve, load, metrics, node ops gRPC, object store, S3 native, sync daemon, template build.

### Desktop smoke

```bash
# Automated subset runs in CI
pytest desktop/tests/smoke_test.py -m automated
```

Covers: `alembic upgrade head` on a fresh SQLite DB, sidecar entrypoint resolution, PyInstaller bundle sanity.

## docker-compose.test.yml

One service, `postgres-test`, exposed on `localhost:5433`:

| Env | Value |
|-----|-------|
| `POSTGRES_DB` | `tesslate_test` |
| `POSTGRES_USER` | `tesslate_test` |
| `POSTGRES_PASSWORD` | `testpass` |

Lifecycle:

```bash
docker compose -f docker-compose.test.yml up -d   # start
docker compose -f docker-compose.test.yml down    # stop (keeps volume)
docker compose -f docker-compose.test.yml down -v # stop + drop volume
```

## Orchestrator test tree

Grouped by subsystem. Files named `test_*.py` unless noted.

| Subdirectory | Covers |
|--------------|--------|
| `tests/agent/unit/` | Kanban tool, tool registry, todo tools, project metadata tools, output formatter, pydantic models |
| `tests/agent/tools/` | Diff editing, file ops, load_skill (builtin), pending user input, project_control, request_node_config, secret_scrubber, tool oracle; tool-family subdirs mirror `packages/tesslate-agent/tests/agent/tools/` |
| `tests/agent/integration/` | Kanban end-to-end flow |
| `tests/agent/e2e/` | `tesslate-agent` API workflow, tesslate-agent security |
| `tests/agent/oracle/` | Oracle model adapter, golden scenario runner |
| `tests/agent/llm/` | Reserved for real-LLM tests (scaffold only) |
| `tests/agent/test_model_adapter_dbless.py` | Model adapter without DB |
| `tests/agents/` | Ticket allocator, approval, budget |
| `tests/agent_bridge/` | Bridge import shape |
| `tests/apps/` | Tesslate Apps: manifest parser/merger/schema freeze (2025-01, 2025-02), publisher, installer, wave1/2/3 models + routers, approval pipeline (wave7), yanks, bundles, submissions, billing dispatcher, runtime source/fork, job-only compute, hosted agent config/runtime, webhook rotation, key lifecycle, event bus, seed apps e2e, version endpoint, creator URLs |
| `tests/integration/` | Auth (login, refresh, magic link), marketplace (agents, bases, themes) team scoping, MCP team scoping, RBAC (audit log, billing, project members, edge cases), projects, teams, agent chat over SQLite, agent lifecycle on minikube, backfill migration, file operations, LiteLLM keys, setup-config, builtin skill integration + guard, feature flags, node config flow, referral security |
| `tests/admin/unit/` | Admin endpoints unit tests |
| `tests/cloud/` | Cloud client, pairing router, token store |
| `tests/containers/` | Isolation, file extraction, orchestrator lifecycle |
| `tests/deployment/` | Deployment builder, manager, providers, routers, env override, guards; `e2e/`, `integration/`, `unit/` subdirs |
| `tests/desktop/` | Agent session list, config mode, directory CRUD, factory per-project, handoff client + transport, sidecar entrypoint |
| `tests/gateway/` | Local gateway + Redis gateway parity |
| `tests/k8s/` | Compute manager, container startup timing, project lifecycle, timing observer |
| `tests/marketplace/` | Install router, installer, local marketplace dual-source |
| `tests/migrations/` | Individual Alembic migration shape tests (e.g., 0049 runtime fields, 0050 orchestration, 0051 workspace directories) |
| `tests/orchestration/` | Local runtime: ports, project root |
| `tests/public/` | Public API surface: agents, agents handoff, k8s projects, marketplace + install, pairing, deps, models, projects sync |
| `tests/pubsub/` | Local pub/sub |
| `tests/rbac/` | API key scopes (unit + integration), permissions |
| `tests/routers/` | Chat WS authz, desktop routers, node config router, project create runtime, no relationship shadowing |
| `tests/services/` | Builtin skill discovery, checkpoint manager, config parser + sync, credit system, env/export resolver, feature flags, file placement, fileops client, git URL security, hub client bundle, magic link, node config presets + discovery, nodeops client, project fs, rate limit, runtime probe, secret manager dual-read, session router, skill markers, snapshot manager, template builder, volume manager |
| `tests/services/mcp/` | Bridge manager, OAuth flow + integration + storage, routers smoke, scoping |
| `tests/services/orchestration/` | Container image + env, local orchestrator, local project aware, pod env resolution |
| `tests/shell/` | PTY broker, shell API, shell session e2e + lifecycle, tsinit client |
| `tests/soak/` | Soak harness (chaos agent, event log, user worker, job.yaml) |
| `tests/sync/` | Sync client, sync router |
| `tests/task_queue/` | Factory, local queue |
| `tests/tmux/` | Placeholder |
| `tests/types/` | GUID TypeDecorator |
| Root-level | `test_chat_auto_title.py`, `test_compliance.py`, `test_internal_api.py`, `test_namespace_reaper.py`, `test_project_auto_add_base.py`, `test_retry_logic.py`, `test_validate_file_path.py` |

## Fixtures

Session fixtures in `tests/conftest.py`:

| Fixture | Purpose |
|---------|---------|
| `event_loop` (session) | Shared asyncio loop |
| `mock_user`, `mock_project`, `mock_db` | Plain mocks for unit tests |
| `test_context` | Dict combining user, project, DB (passed to tool executors) |

Golden data (`tests/fixtures/`):

- `golden_parser_inputs.json`
- `golden_patches.json`
- `golden_tool_outputs.json`
- `oracle_scenarios/` (JSON/YAML scenarios for the oracle runner)

Scoped conftests add integration DB sessions, router HTTP clients, K8s clients, etc.

## Frontend test layout

| Path | Covers |
|------|--------|
| `app/src/test/setup.ts` | Global vitest setup (jsdom, mocks) |
| `app/src/__tests__/apps/` | App install wizard, bundle install wizard, apps marketplace page, fork modal |
| `app/src/components/apps/IframeAppHost.test.tsx` | Iframe host for embedded apps |
| `app/src/components/RouteGuards.test.tsx`, `DeploymentTargetNode.test.ts` | Route + canvas node |
| `app/src/contexts/*.test.tsx` | Auth (initial 401, refresh), admin, wallet, apps, feature flag |
| `app/src/pages/*.test.tsx` | Creator studio, my apps, logout, login magic-link flag, admin submission workbench, admin yank center, admin marketplace review, app workspace, creator app publish, creator billing, import redirect |
| `app/src/lib/api.*.test.ts` | Login-flow 401, refresh, deployment routing, feature flags, config sync, credential hierarchy |
| `app/tests/e2e/` | Playwright E2E (auth.setup.ts plus spec folders) |

## Writing new tests

Backend integration template:

```python
import pytest

@pytest.mark.integration
@pytest.mark.asyncio
async def test_my_feature(authenticated_client):
    client, user = authenticated_client
    resp = await client.post("/api/foo", json={"a": 1})
    assert resp.status_code == 200
```

Playwright template:

```ts
import { test, expect } from '@playwright/test';

test('flow works', async ({ page }) => {
  await page.goto('/my-page');
  await page.click('button:has-text("Action")');
  await expect(page.locator('.result')).toBeVisible();
});
```

Go test (btrfs CSI):

```go
// integration/my_feature_test.go
//go:build integration
package integration
```

## Common issues

| Symptom | Fix |
|---------|-----|
| Port 5433 in use | `kill $(lsof -ti:5433)` then restart compose |
| "database locked" | Ensure you're hitting 5433 (test DB), not 5432 (dev) |
| Playwright browser missing | `npx playwright install --with-deps chromium` |
| Backend not ready for E2E | Run `alembic upgrade head` before starting uvicorn |
| `tesslate-agent` import missing | `pip install -e "../packages/tesslate-agent"` first (conftest auto-adds to sys.path but install is required for entry points) |
| Privileged denied on btrfs tests | `make test` needs `--privileged` Docker to create loopback btrfs |

## Performance tips

- `pytest -k name` narrows by substring
- `pytest --maxfail=1 -x` stops on first failure
- `pytest -n auto` for xdist parallelism (install `pytest-xdist` as a dev dep)
- `npx playwright test --grep "name"` filters E2E
- `--workers=1` avoids Playwright race conditions when debugging
