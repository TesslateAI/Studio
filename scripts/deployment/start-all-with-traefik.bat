@echo off
REM ============================================================================
REM Tesslate Studio - Hybrid Mode Startup Script
REM ============================================================================
REM
REM WHAT THIS DOES:
REM   - Starts Traefik reverse proxy in Docker (REQUIRED for user containers)
REM   - Starts main services natively on host (faster hot reload)
REM
REM WHY TRAEFIK IS REQUIRED:
REM   Even though main services run natively, user development containers
REM   need Traefik for routing. Multiple user projects can't all use the
REM   same port, so Traefik provides hostname-based routing:
REM     - user1-project5.localhost -> Container A (port 5173)
REM     - user2-project8.localhost -> Container B (port 5173)
REM
REM NETWORK ARCHITECTURE:
REM   ┌─────────────────────────────────────────────┐
REM   │ Host Machine                                 │
REM   │  • Orchestrator: localhost:8000 (built-in AI)│
REM   │  • Frontend: localhost:5173                 │
REM   └──────────────────┬──────────────────────────┘
REM                      │ Creates containers
REM                      ▼
REM   ┌─────────────────────────────────────────────┐
REM   │ Docker Network: tesslate-network            │
REM   │  ┌──────────┐  ┌─────────────────────────┐ │
REM   │  │ Traefik  │─▶│ User Dev Containers     │ │
REM   │  └──────────┘  │ (dynamic)               │ │
REM   │                └─────────────────────────┘ │
REM   └─────────────────────────────────────────────┘
REM
REM ADVANTAGES:
REM   ✅ Fast hot reload on main services (no Docker rebuild)
REM   ✅ Easy debugging (IDE breakpoints work)
REM   ✅ Lower resource usage than Full Docker
REM   ✅ Still supports multi-user isolation
REM
REM DISADVANTAGES:
REM   ❌ More complex setup (multiple windows)
REM   ❌ Requires manual service management
REM   ❌ Not production-ready (use K8s for production)
REM
REM For other deployment options, see: DEPLOYMENT.md
REM ============================================================================

echo.
echo ============================================================================
echo  Tesslate Studio - Hybrid Mode (Native Services + Traefik)
echo ============================================================================
echo.

REM Check if Docker is running
echo [1/6] Checking Docker availability...
docker version > nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ❌ ERROR: Docker is not running!
    echo.
    echo Please start Docker Desktop and try again.
    echo.
    pause
    exit /b 1
)
echo ✅ Docker is running

REM Create network if it doesn't exist
echo.
echo [2/6] Checking Docker network...
docker network inspect tesslate-network > nul 2>&1
if %errorlevel% neq 0 (
    echo Creating Docker network tesslate-network...
    docker network create tesslate-network
    echo ✅ Network created
) else (
    echo ✅ Network already exists
)

REM Start Traefik using docker-compose
echo.
echo [3/6] Starting Traefik reverse proxy...
echo     (Required for user dev container routing)
cd ..\..
docker-compose up -d traefik
cd scripts\deployment
echo ✅ Traefik started

REM Wait for Traefik to be ready
echo.
echo [4/6] Waiting for Traefik to be ready...
timeout /t 5 /nobreak > nul
echo ✅ Traefik ready

REM Start orchestrator on port 8000
echo.
echo [5/6] Starting backend service...
echo.
echo Starting Orchestrator (Backend API with built-in AI)...
start "Orchestrator Service" cmd /k "cd ..\..\..\orchestrator && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak > nul

echo ✅ Backend service starting...

REM Start frontend dev server
echo.
echo [6/6] Starting frontend...
start "Frontend Dev Server" cmd /k "cd ..\..\..\app && npm run dev"

echo.
echo ============================================================================
echo  🚀 Tesslate Studio is Starting!
echo ============================================================================
echo.
echo 📍 MAIN SERVICES (Native - Fast hot reload):
echo   • Frontend:     http://localhost:5173
echo   • Orchestrator: http://localhost:8000 (with built-in AI)
echo.
echo 📍 TRAEFIK DASHBOARD (Docker):
echo   • Dashboard:    http://localhost:8080
echo.
echo 📍 USER DEV CONTAINERS (Auto-created via Traefik):
echo   • Format:       http://user{id}-project{id}.localhost
echo   • Example:      http://user1-project5.localhost
echo.
echo ============================================================================
echo 💡 TIPS:
echo ============================================================================
echo   • Check separate windows for each service's output
echo   • Frontend will open automatically in browser
echo   • User containers created automatically when projects are created
echo   • Hot reload works on all native services
echo.
echo ⚙️  TO STOP ALL SERVICES:
echo   1. Close all service windows (Orchestrator, Frontend)
echo   2. Run: docker-compose down  (stops Traefik)
echo.
echo 📚 For other deployment options, see: DEPLOYMENT.md
echo ============================================================================
echo.
pause
