@echo off
REM ============================================================================
REM Build Dev Container Image (Windows)
REM ============================================================================
REM Builds the development server Docker image with pre-installed dependencies
REM This image is used for user project containers in both Docker and Kubernetes
REM
REM Usage:
REM   scripts\deployment\build-dev-image.bat              # Build for local Docker
REM   scripts\deployment\build-dev-image.bat --push       # Build and push to registry
REM   scripts\deployment\build-dev-image.bat --no-cache   # Force rebuild
REM ============================================================================

setlocal enabledelayedexpansion

REM Get script directory and project root
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\..\"

REM Default values
set PUSH_TO_REGISTRY=false
set NO_CACHE=
set BUILD_PLATFORM=

REM Parse arguments
:parse_args
if "%~1"=="" goto end_parse_args
if /i "%~1"=="--push" (
    set PUSH_TO_REGISTRY=true
    shift
    goto parse_args
)
if /i "%~1"=="--no-cache" (
    set NO_CACHE=--no-cache
    shift
    goto parse_args
)
if /i "%~1"=="--platform" (
    set BUILD_PLATFORM=--platform %~2
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--help" goto show_help
if /i "%~1"=="-h" goto show_help
echo Error: Unknown option %~1
exit /b 1

:show_help
echo Usage: %~nx0 [OPTIONS]
echo.
echo Options:
echo   --push         Push image to DigitalOcean Container Registry
echo   --no-cache     Build without using cache
echo   --platform     Specify platform (e.g., linux/amd64)
echo   --help, -h     Show this help message
exit /b 0

:end_parse_args

REM Image names
set LOCAL_IMAGE=tesslate-devserver:latest
set REMOTE_IMAGE=registry.digitalocean.com/finetune/tesslate-dev-server:latest

echo ============================================
echo Building Tesslate Dev Server Image
echo ============================================
echo.

REM Build the image
echo [BUILD] Building dev server image...
cd /d "%PROJECT_ROOT%\orchestrator"

docker build -f Dockerfile.devserver -t "%LOCAL_IMAGE%" %NO_CACHE% %BUILD_PLATFORM% .

if errorlevel 1 (
    echo [ERROR] Failed to build dev server image
    exit /b 1
)

echo [SUCCESS] Dev server image built successfully: %LOCAL_IMAGE%

REM Push to registry if requested
if "%PUSH_TO_REGISTRY%"=="true" (
    echo.
    echo [PUSH] Pushing to DigitalOcean Container Registry...

    REM Load DOCR_TOKEN from k8s\.env if it exists
    if exist "%PROJECT_ROOT%\k8s\.env" (
        for /f "usebackq tokens=1,* delims==" %%a in ("%PROJECT_ROOT%\k8s\.env") do (
            if /i "%%a"=="DOCR_TOKEN" set "DOCR_TOKEN=%%b"
        )
    )

    if not defined DOCR_TOKEN (
        echo [ERROR] DOCR_TOKEN not found. Please set it in k8s\.env
        echo         Get your token from: https://cloud.digitalocean.com/account/api/tokens
        exit /b 1
    )

    REM Login to DigitalOcean Container Registry
    echo !DOCR_TOKEN! | docker login registry.digitalocean.com -u !DOCR_TOKEN! --password-stdin

    if errorlevel 1 (
        echo [ERROR] Failed to login to DigitalOcean Container Registry
        exit /b 1
    )

    REM Tag for remote registry
    docker tag "%LOCAL_IMAGE%" "%REMOTE_IMAGE%"

    REM Push to registry
    docker push "%REMOTE_IMAGE%"

    if errorlevel 1 (
        echo [ERROR] Failed to push image to registry
        exit /b 1
    )

    echo [SUCCESS] Image pushed successfully: %REMOTE_IMAGE%
)

echo.
echo ============================================
echo Build Complete!
echo ============================================
echo.
echo Local image:  %LOCAL_IMAGE%
if "%PUSH_TO_REGISTRY%"=="true" (
    echo Remote image: %REMOTE_IMAGE%
)
echo.
echo Next steps:
if "%PUSH_TO_REGISTRY%"=="true" (
    echo   * Image is ready for Kubernetes deployment
    echo   * Run: kubectl rollout restart deployment -n tesslate-user-environments
) else (
    echo   * Image is ready for local Docker development
    echo   * Run: docker compose up -d
    echo   * To push to registry: %~nx0 --push
)
echo.

endlocal
