@echo off
echo Starting Tesslate Studio...
echo.
echo WARNING: This script starts services WITHOUT Traefik!
echo User dev containers will NOT work. Use start-all-with-traefik.bat instead.
echo.

REM Start orchestrator service on port 8000
echo Starting orchestrator service on port 8000 (with built-in AI)...
start "Orchestrator Service" cmd /k "cd ..\.. && cd orchestrator && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

REM Wait a bit for orchestrator to start
timeout /t 3 /nobreak > nul

REM Start frontend dev server
echo Starting frontend dev server...
start "Frontend Dev Server" cmd /k "cd ..\.. && cd app && npm run dev"

echo.
echo Services are starting...
echo Orchestrator: http://localhost:8000 (includes built-in AI)
echo Frontend: http://localhost:5173
echo.
echo NOTE: User dev containers require Traefik!
echo Use start-all-with-traefik.bat for full functionality.
echo.
echo Close this window to keep servers running, or press Ctrl+C to stop.
pause