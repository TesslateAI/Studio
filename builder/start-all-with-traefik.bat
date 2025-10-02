@echo off
echo Starting 8-22-25 Studio with Traefik...
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
docker network inspect builder-devserver-network > nul 2>&1
if %errorlevel% neq 0 (
    echo Creating Docker network builder-devserver-network...
    docker network create builder-devserver-network
)

REM Start Traefik using docker-compose
echo Starting Traefik reverse proxy...
cd ..
docker-compose up -d traefik
cd builder

REM Wait for Traefik to be ready
echo Waiting for Traefik to start...
timeout /t 5 /nobreak > nul

REM Start backend on port 8005
echo Starting backend on port 8005...
start "Backend Server" cmd /k "cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8005"

REM Wait a bit for backend to start
timeout /t 3 /nobreak > nul

REM Start frontend dev server
echo Starting frontend dev server...
start "Frontend Dev Server" cmd /k "cd frontend && npm run dev"

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
echo   Backend:   http://localhost:8005
echo.
echo Production Access:
echo   Frontend:  https://your-domain.com/
echo   Backend:   https://your-domain.com/api
echo.
echo ======================================
echo.
echo To stop all services:
echo   1. Close this window
echo   2. Run: docker-compose down
echo.
pause