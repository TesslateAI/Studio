@echo off
REM Tesslate Studio - Docker Development Setup Script (Windows)
REM This script helps you quickly set up the development environment

echo ==================================
echo Tesslate Studio Docker Setup
echo ==================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running. Please start Docker Desktop and try again.
    exit /b 1
)

echo [OK] Docker is running

REM Change to project root directory
cd ..\..

REM Create root .env if it doesn't exist
if not exist ".env" (
    echo Creating root .env file...
    copy .env.example .env >nul
    echo [OK] Created .env
    echo [WARNING] IMPORTANT: Edit .env and set your SECRET_KEY and LITELLM_MASTER_KEY
) else (
    echo [OK] Root .env already exists
)

REM Create app .env if it doesn't exist
if not exist "app\.env" (
    echo Creating frontend .env file...
    copy app\.env.example app\.env >nul
    echo [OK] Created app\.env
) else (
    echo [OK] Frontend .env already exists
)

REM Create traefik acme.json if it doesn't exist
if not exist "traefik\acme.json" (
    echo Creating traefik\acme.json...
    type nul > traefik\acme.json
    echo [OK] Created traefik\acme.json
) else (
    echo [OK] traefik\acme.json already exists
)

echo.
echo Checking configuration...

REM Check if required environment variables are set
findstr /C:"your-secret-key-here-change-this-in-production" .env >nul 2>&1
if not errorlevel 1 (
    echo [WARNING] SECRET_KEY is not configured in .env
    set NEEDS_CONFIG=true
)

findstr /C:"your-litellm-master-key-here" .env >nul 2>&1
if not errorlevel 1 (
    echo [WARNING] LITELLM_MASTER_KEY is not configured in .env
    set NEEDS_CONFIG=true
)

if defined NEEDS_CONFIG (
    echo.
    echo Please edit .env and set:
    echo   1. SECRET_KEY ^(must be at least 32 characters^)
    echo   2. LITELLM_MASTER_KEY ^(for your LiteLLM proxy^)
    echo.
    pause
)

echo.
echo ==================================
echo Starting Docker Compose...
echo ==================================

REM Start services
docker compose up -d

if errorlevel 1 (
    echo [ERROR] Failed to start services
    exit /b 1
)

echo.
echo [OK] Services started successfully!
echo.
echo ==================================
echo Access the application:
echo ==================================
echo   Frontend:  http://studio.localhost
echo   Backend:   http://api.localhost
echo   Traefik:   http://traefik.localhost:8080
echo.
echo ==================================
echo Useful commands:
echo ==================================
echo   View logs:        docker compose logs -f
echo   Stop services:    docker compose down
echo   Restart:          docker compose restart
echo.
echo Setup complete! Happy coding!
