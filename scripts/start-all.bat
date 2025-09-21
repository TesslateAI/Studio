@echo off
echo Starting Tesslate Studio...
echo.

REM Start orchestrator service on port 8000
echo Starting orchestrator service on port 8000...
start "Orchestrator Service" cmd /k "cd orchestrator && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

REM Wait a bit for orchestrator to start
timeout /t 3 /nobreak > nul

REM Start AI service on port 8001
echo Starting AI service on port 8001...
start "AI Service" cmd /k "cd ai-service && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001"

REM Wait a bit for AI service to start
timeout /t 2 /nobreak > nul

REM Start frontend dev server
echo Starting frontend dev server...
start "Frontend Dev Server" cmd /k "cd app && npm run dev"

echo.
echo All services are starting...
echo Orchestrator: http://localhost:8000
echo AI Service: http://localhost:8001
echo Frontend: http://localhost:5173
echo.
echo Close this window to keep servers running, or press Ctrl+C to stop.
pause