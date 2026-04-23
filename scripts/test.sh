#!/usr/bin/env bash
#
# Convenience script for running tests locally.
#
# Usage:
#   ./scripts/test.sh [unit|integration|e2e|all]
#
# Examples:
#   ./scripts/test.sh unit         # Run backend + frontend unit tests
#   ./scripts/test.sh integration  # Run backend integration tests (requires PG on 5433)
#   ./scripts/test.sh e2e          # Run Playwright E2E tests (requires backend + frontend running)
#   ./scripts/test.sh all          # Run all tests in sequence

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Test mode (default: all)
MODE="${1:-all}"

echo -e "${GREEN}=== OpenSail Test Runner ===${NC}"
echo -e "Mode: ${YELLOW}${MODE}${NC}\n"

# Function to run backend unit tests
run_backend_unit() {
  echo -e "${GREEN}Running backend unit tests...${NC}"
  cd "$PROJECT_ROOT/orchestrator"

  # Check if pytest is available
  if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest not found. Install with: pip install -e '.[dev]'${NC}"
    exit 1
  fi

  pytest -m "unit or mocked" --tb=short || {
    echo -e "${RED}Backend unit tests failed${NC}"
    exit 1
  }

  echo -e "${GREEN}✓ Backend unit tests passed${NC}\n"
}

# Function to run frontend unit tests
run_frontend_unit() {
  echo -e "${GREEN}Running frontend unit tests...${NC}"
  cd "$PROJECT_ROOT/app"

  # Check if node_modules exists
  if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing frontend dependencies...${NC}"
    npm ci
  fi

  npm run test -- --run || {
    echo -e "${RED}Frontend unit tests failed${NC}"
    exit 1
  }

  echo -e "${GREEN}✓ Frontend unit tests passed${NC}\n"
}

# Function to run backend integration tests
run_backend_integration() {
  echo -e "${GREEN}Running backend integration tests...${NC}"

  # Check if PostgreSQL is running on port 5433
  if ! nc -z localhost 5433 2>/dev/null; then
    echo -e "${YELLOW}PostgreSQL not detected on port 5433. Starting docker-compose.test.yml...${NC}"
    cd "$PROJECT_ROOT"
    docker compose -f docker-compose.test.yml up -d

    # Wait for PostgreSQL to be ready
    echo -e "${YELLOW}Waiting for PostgreSQL to be ready...${NC}"
    sleep 5
  fi

  cd "$PROJECT_ROOT/orchestrator"

  # Run migrations
  echo -e "${YELLOW}Running database migrations...${NC}"
  DATABASE_URL="postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test" \
    alembic upgrade head

  # Run tests
  pytest tests/integration/ -m integration --tb=short || {
    echo -e "${RED}Backend integration tests failed${NC}"
    exit 1
  }

  echo -e "${GREEN}✓ Backend integration tests passed${NC}\n"
}

# Function to run E2E tests
run_e2e() {
  echo -e "${GREEN}Running Playwright E2E tests...${NC}"

  # Check if backend is running
  if ! curl -s http://localhost:8000/health &> /dev/null; then
    echo -e "${RED}Error: Backend not running on port 8000${NC}"
    echo -e "${YELLOW}Start with: cd orchestrator && uvicorn app.main:app --host 0.0.0.0 --port 8000${NC}"
    exit 1
  fi

  # Check if frontend is running
  if ! curl -s http://localhost:5173 &> /dev/null; then
    echo -e "${RED}Error: Frontend not running on port 5173${NC}"
    echo -e "${YELLOW}Start with: cd app && npm run dev${NC}"
    exit 1
  fi

  cd "$PROJECT_ROOT/app"

  # Install Playwright if needed
  if [ ! -d "node_modules/@playwright/test" ]; then
    echo -e "${YELLOW}Installing Playwright...${NC}"
    npm install --save-dev @playwright/test
    npx playwright install --with-deps chromium
  fi

  npx playwright test || {
    echo -e "${RED}E2E tests failed${NC}"
    exit 1
  }

  echo -e "${GREEN}✓ E2E tests passed${NC}\n"
}

# Run tests based on mode
case "$MODE" in
  unit)
    run_backend_unit
    run_frontend_unit
    ;;

  integration)
    run_backend_integration
    ;;

  e2e)
    run_e2e
    ;;

  all)
    echo -e "${GREEN}=== Running all tests ===${NC}\n"
    run_backend_unit
    run_frontend_unit
    run_backend_integration
    run_e2e
    echo -e "${GREEN}=== All tests passed! ===${NC}"
    ;;

  *)
    echo -e "${RED}Invalid mode: $MODE${NC}"
    echo -e "Usage: ./scripts/test.sh [unit|integration|e2e|all]"
    exit 1
    ;;
esac

echo -e "${GREEN}Done!${NC}"
