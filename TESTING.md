# Testing Guide

Tesslate Studio has three layers of automated testing:

1. **Unit tests** — Fast, mocked, no external dependencies
2. **Integration tests** — Real PostgreSQL database, httpx AsyncClient
3. **E2E tests** — Full browser automation with Playwright

## Quick Start

### Run All Tests
```bash
./scripts/test.sh all
```

### Run Specific Test Suite
```bash
./scripts/test.sh unit         # Backend + frontend unit tests
./scripts/test.sh integration  # Backend integration tests
./scripts/test.sh e2e          # Playwright E2E tests
```

---

## 1. Unit Tests

### Backend Unit Tests

**Location**: `orchestrator/tests/`

**Command**:
```bash
cd orchestrator
pytest -m "unit or mocked"
```

**What they test**:
- Agent tools (file operations, shell commands, etc.)
- Business logic (project creation, user management)
- Utility functions

**Dependencies**: None (fully mocked)

**Speed**: Very fast (~1-2 seconds)

### Frontend Unit Tests

**Location**: `app/src/**/*.test.ts`, `app/src/**/*.test.tsx`

**Command**:
```bash
cd app
npm run test        # Interactive watch mode
npm run test -- --run  # Single run (for CI)
```

**What they test**:
- React components
- Custom hooks
- Utility functions

**Dependencies**: None (jsdom)

**Speed**: Fast (~5-10 seconds)

---

## 2. Integration Tests

**Location**: `orchestrator/tests/integration/`

**Prerequisites**:
```bash
# Start test database (port 5433)
docker compose -f docker-compose.test.yml up -d
```

**Command**:
```bash
cd orchestrator
pytest tests/integration/ -m integration
```

**What they test**:
- Full HTTP request/response cycle (via httpx AsyncClient)
- Real PostgreSQL database operations
- Authentication flows (registration, login, JWT)
- CRUD operations (projects, users)
- Database transactions and rollback

**Test Database**:
- Host: `localhost:5433`
- Database: `tesslate_test`
- User: `tesslate_test`
- Password: `testpass`

**Isolation Pattern**:
Each test runs in its own transaction that rolls back after completion. This provides perfect test isolation with zero cleanup overhead.

**Speed**: Medium (~10-20 seconds)

**Cleanup**:
```bash
# Stop test database
docker compose -f docker-compose.test.yml down
```

---

## 3. E2E Tests (Playwright)

**Location**: `app/tests/e2e/`

**Prerequisites**:
1. Start test database:
   ```bash
   docker compose -f docker-compose.test.yml up -d
   ```

2. Start backend:
   ```bash
   cd orchestrator
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

3. Start frontend:
   ```bash
   cd app
   npm run dev
   ```

**Command**:
```bash
cd app
npm run test:e2e          # Headless mode
npm run test:e2e:headed   # See browser
npm run test:e2e:ui       # Interactive UI mode
```

**What they test**:
- Full user flows (login, project creation, etc.)
- Browser interactions (clicks, form fills, navigation)
- UI rendering and responsiveness

**Auth Setup**:
The `auth.setup.ts` file creates a test user and saves auth state to `.auth/user.json`. All other tests reuse this auth state (no need to login in every test).

**Speed**: Slow (~30-60 seconds)

**Debugging**:
```bash
# Show browser during test
npm run test:e2e:headed

# Interactive UI mode
npm run test:e2e:ui

# View HTML report after run
npx playwright show-report
```

---

## CI Pipeline

The GitHub Actions CI pipeline (`..github/workflows/ci.yml`) runs all three test layers on every PR:

```
┌─────────────────┐  ┌─────────────────┐
│ backend-unit    │  │ frontend-unit   │
└────────┬────────┘  └────────┬────────┘
         │                    │
         └──────────┬─────────┘
                    ▼
         ┌──────────────────┐
         │ backend-integration │
         └──────────┬─────────┘
                    │
                    ▼
         ┌──────────────────┐
         │      e2e         │
         └──────────────────┘
```

**Jobs**:
1. `backend-unit` — Backend unit tests (parallel)
2. `frontend-unit` — Frontend unit tests (parallel)
3. `backend-integration` — Integration tests (depends on backend-unit)
4. `e2e` — E2E tests (depends on backend-integration + frontend-unit)

**Artifacts**:
- Test results (JUnit XML)
- Playwright HTML report
- Playwright traces (on failure)

---

## Writing New Tests

### Backend Integration Test

```python
# orchestrator/tests/integration/test_my_feature.py
import pytest

@pytest.mark.integration
@pytest.mark.asyncio
async def test_my_feature(authenticated_client):
    client, user_data = authenticated_client

    response = await client.post("/api/my-endpoint", json={...})

    assert response.status_code == 200
    assert response.json()["key"] == "value"
```

### Playwright E2E Test

```typescript
// app/tests/e2e/my-feature/my-feature.spec.ts
import { test, expect } from '@playwright/test';

test('my feature works', async ({ page }) => {
  // This test uses stored auth from auth.setup.ts
  await page.goto('/my-page');

  await page.click('button:has-text("Action")');

  await expect(page.locator('.result')).toBeVisible();
});
```

---

## Common Issues

### PostgreSQL port 5433 already in use
```bash
# Find process using port 5433
lsof -ti:5433

# Kill it
kill $(lsof -ti:5433)

# Or use a different port in docker-compose.test.yml
```

### Playwright browser not installed
```bash
cd app
npx playwright install --with-deps chromium
```

### Backend won't start in E2E tests
Check that:
- PostgreSQL is running on port 5433
- Migrations have been run: `alembic upgrade head`
- Environment variables are set correctly

### Tests fail with "database locked"
Make sure you're using the test database on port 5433, not the dev database on 5432.

---

## Performance Tips

**Speed up integration tests**:
- Use `pytest -k "test_name"` to run specific tests
- Use `pytest --maxfail=1` to stop on first failure

**Speed up E2E tests**:
- Use `npx playwright test --grep "test name"` to run specific tests
- Use `--workers=1` to avoid race conditions
- Use `--headed` only when debugging

**CI optimization**:
- Unit tests run in parallel (fastest feedback)
- Integration tests gate E2E (fail fast)
- E2E tests upload artifacts only on failure

---

## Further Reading

- [Pytest Documentation](https://docs.pytest.org/)
- [Playwright Documentation](https://playwright.dev/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [Testing Library](https://testing-library.com/docs/react-testing-library/intro/)

## Installation

### Backend Dependencies

The integration tests require dev dependencies. Install them with:

```bash
cd orchestrator

# Option 1: Using pip with dependency groups (recommended)
pip install -e ".[dev]"

# Option 2: Manual installation if pip doesn't support dependency groups
pip install -e .
pip install pytest pytest-asyncio pytest-cov freezegun pytest-timeout ruff pyright
```

### Frontend Dependencies

```bash
cd app
npm ci

# Install Playwright browsers (first time only)
npx playwright install --with-deps chromium
```

### Verify Installation

```bash
# Backend
cd orchestrator
pytest --version
python -c "import pytest_asyncio; print('pytest-asyncio installed')"

# Frontend
cd app
npx playwright --version
```

