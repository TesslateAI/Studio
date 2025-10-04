@echo off
echo Starting Tesslate Studio with Traefik...
echo.

REM Check if Docker is running
docker version > nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Docker is not running. Please start Docker Desktop first.
    pause
    exit /b 1
)

REM Create network if it doesn't exist
echo Checking Docker network...
docker network inspect tesslate-network > nul 2>&1
if %errorlevel% neq 0 (
    echo Creating Docker network tesslate-network...
    docker network create tesslate-network
)

REM Start Traefik using docker-compose
echo Starting Traefik reverse proxy...
cd ..
docker-compose up -d traefik
cd scripts

REM Wait for Traefik to be ready
echo Waiting for Traefik to start...
timeout /t 5 /nobreak > nul

REM Start orchestrator on port 8000
echo Starting orchestrator on port 8000...
start "Orchestrator Service" cmd /k "cd ..\orchestrator && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

REM Wait a bit for orchestrator to start
timeout /t 3 /nobreak > nul

REM Start AI service on port 8001
echo Starting AI service on port 8001...
start "AI Service" cmd /k "cd ..\ai-service && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001"

REM Wait a bit for AI service to start
timeout /t 2 /nobreak > nul

REM Start frontend dev server
echo Starting frontend dev server...
start "Frontend Dev Server" cmd /k "cd ..\app && npm run dev"

echo.
echo ======================================
echo All services are starting...
echo ======================================
echo.
echo Local Access:
echo   Frontend:  http://localhost/
echo   Backend:   http://localhost/api
echo   Traefik:   http://localhost:8080
echo.
echo Direct Access (for debugging):
echo   Frontend:  http://localhost:5173
echo   Orchestrator: http://localhost:8000
echo   AI Service:   http://localhost:8001
echo.
echo Production Access:
echo   Frontend:  https://your-domain.com/
echo   Backend:   https://your-domain.com/api
echo.
echo ======================================
echo.
echo To stop all services:
echo   1. Close the service windows
echo   2. Run: docker-compose down
echo.
pause
