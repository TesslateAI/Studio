@echo off
echo Starting 8-22-25 Studio...
echo.

REM Start backend on port 8005
echo Starting backend on port 8005...
start "Backend Server" cmd /k "cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8005"

REM Wait a bit for backend to start
timeout /t 3 /nobreak > nul

REM Start frontend dev server
echo Starting frontend dev server...
start "Frontend Dev Server" cmd /k "cd frontend && npm run dev"

echo.
echo Both servers are starting...
echo Backend: http://localhost:8005
echo Frontend: http://localhost:5173
echo.
echo Close this window to keep servers running, or press Ctrl+C to stop.
pause