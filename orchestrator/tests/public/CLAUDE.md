# Public API Tests

Mirrors `orchestrator/app/routers/public/`. Each router file has a corresponding `test_<name>.py` of unit tests; cross-router flows go under `integration/`.

## When to load this context

- Writing or modifying tests for any `/api/public/*` or `/api/v1/*` endpoint.
- Debugging a failing public-API test.

## Structure

```
tests/public/
├── test_marketplace.py             # unit tests for routers/public/marketplace.py
├── test_models.py                  # unit tests for routers/public/models.py
└── integration/
    └── test_public_api_integration.py   # end-to-end across public routers
```

## Conventions

1. **Mirror the router filename.** `routers/public/sync.py` → `tests/public/test_sync.py`.
2. **Unit vs integration.** Unit tests mock the DB/external services and exercise a single router; integration tests use the real test DB (`conftest.py` fixtures in `tests/`) and span multiple endpoints.
3. **Scope coverage.** Every endpoint must have at least one test that asserts the required `Permission` scope is enforced (missing scope → 403).
4. **API-key auth helpers** — reuse fixtures from `tests/conftest.py` for minting `tsk_` keys rather than constructing them by hand.
5. **Cache-header assertions** on GET endpoints — verify ETag + Cache-Control appear, since desktop relies on them.

## Running

From `orchestrator/`:

```bash
pytest tests/public/ -v
pytest tests/public/integration/ -v
```

## Gotchas

- Import paths: tests import from `app.routers.public.<name>`, not `app.routers.<name>`. After moving a router into `public/`, grep tests for the old import path.
- `conftest.py` remains at `tests/conftest.py` — do not duplicate fixtures into `tests/public/`.
- The integration test file relies on the `public_routers` list in `app/routers/public/__init__.py` being registered in `main.py` — if a new router is added to the list but not covered integration-side, add a smoke test.

## Related contexts

- `orchestrator/app/routers/public/CLAUDE.md` — router conventions.
- `orchestrator/tests/conftest.py` — shared fixtures (API keys, users, teams, test DB).
