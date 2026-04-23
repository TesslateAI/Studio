# OpenSail Testing

## Purpose

Context for the test suites in OpenSail: orchestrator (pytest), frontend (vitest + Playwright), `tesslate-agent` package, btrfs CSI (Go), and desktop smoke tests.

## Key files

| Path | Purpose |
|------|---------|
| `TESTING.md` (repo root) | Top-level test runner guide (unit, integration, e2e) |
| `docker-compose.test.yml` | Spins up `postgres-test` on port 5433 for integration tests |
| `orchestrator/tests/conftest.py` | Sets env vars before imports, registers pytest markers, seeds mocks |
| `orchestrator/tests/routers/conftest.py` | Router-level fixtures |
| `orchestrator/tests/integration/conftest.py` | Integration fixtures (real DB session, authenticated client) |
| `orchestrator/tests/k8s/conftest.py` | Minikube fixtures |
| `orchestrator/tests/agents/conftest.py` | Agent ticket + budget fixtures |
| `app/src/test/setup.ts` | Vitest jsdom setup |
| `packages/tesslate-agent/tests/` | Agent package unit tests (tools, orchestration, CLI) |
| `services/btrfs-csi/integration/Makefile` | `make test` and `make load-test` (privileged Docker) |
| `desktop/tests/smoke_test.py` | Desktop sidecar + SQLite migration smoke checks |

## pytest markers

Declared in `orchestrator/tests/conftest.py::pytest_configure`:

| Marker | Meaning |
|--------|---------|
| `unit` | Fast, fully mocked |
| `mocked` | Alias for pure-mock tests |
| `integration` | Requires Postgres on `localhost:5433` |
| `e2e` | Playwright end-to-end |
| `slow` | Long running |
| `docker` | Requires Docker daemon |
| `kubernetes` / `minikube` | Requires K8s cluster |
| `llm` | Uses real LiteLLM (`llama-4-maverick` via proxy) |
| `deterministic` | Determinism verification |
| `oracle` | Golden input/output comparison |

## Related contexts

- `/docs/ci-cd/CLAUDE.md` for CI pipeline that runs these
- `/docs/guides/environment-variables.md` for env vars required by tests
- `/docs/packages/CLAUDE.md` for `tesslate-agent` test layout

## When to load

- Adding new tests, new pytest markers, or new CI jobs
- Diagnosing flaky tests or CI failures
- Wiring up fixtures for a new subsystem
