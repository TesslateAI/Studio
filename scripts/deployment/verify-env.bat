@echo off
REM Tesslate Studio - Environment Configuration Checker
REM Batch script for Windows

echo ============================================================
echo Tesslate Studio - Environment Configuration Check
echo ============================================================
echo.

REM Check if .env file exists
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo    Run: copy .env.example .env
    exit /b 1
)

echo [OK] .env file found
echo.

REM Simple check for required variables
echo Checking configuration...
echo.

REM Check SECRET_KEY
findstr /C:"SECRET_KEY=your-secret-key-here-change-this-in-production" .env >nul
if %errorlevel% equ 0 (
    echo [ERROR] SECRET_KEY not configured - using default is insecure
    echo    Generate with: openssl rand -base64 64
    set HAS_ERRORS=1
    goto :check_complete
)

findstr /C:"SECRET_KEY=your_secret_key_here" .env >nul
if %errorlevel% equ 0 (
    echo [ERROR] SECRET_KEY not configured - using default is insecure
    echo    Generate with: openssl rand -base64 64
    set HAS_ERRORS=1
    goto :check_complete
)

echo [OK] SECRET_KEY is configured

REM Check DATABASE_URL
findstr /C:"DATABASE_URL=" .env >nul
if %errorlevel% neq 0 (
    echo [ERROR] DATABASE_URL not configured
    set HAS_ERRORS=1
) else (
    echo [OK] Database configured
)

REM Check POSTGRES_PASSWORD
findstr /C:"POSTGRES_PASSWORD=dev_password_change_me" .env >nul
if %errorlevel% equ 0 (
    echo [WARNING] POSTGRES_PASSWORD using default - change for production
    echo    Generate with: openssl rand -base64 32
)

findstr /C:"POSTGRES_PASSWORD=your_postgres_password_here" .env >nul
if %errorlevel% equ 0 (
    echo [WARNING] POSTGRES_PASSWORD using default - change for production
    echo    Generate with: openssl rand -base64 32
)

REM Check LiteLLM Configuration
findstr /C:"LITELLM_API_BASE=https://your-litellm" .env >nul
if %errorlevel% equ 0 (
    echo [WARNING] LITELLM_API_BASE not configured - AI features won't work
    goto :optional_features
)

findstr /C:"LITELLM_MASTER_KEY=your-litellm-master-key-here" .env >nul
if %errorlevel% equ 0 (
    echo [WARNING] LITELLM_MASTER_KEY not configured - AI features won't work
    goto :optional_features
)

findstr /C:"LITELLM_MASTER_KEY=your_litellm_master_key_here" .env >nul
if %errorlevel% equ 0 (
    echo [WARNING] LITELLM_MASTER_KEY not configured - AI features won't work
    goto :optional_features
)

echo [OK] LiteLLM proxy is configured

REM Display configured models
for /f "tokens=2 delims==" %%a in ('findstr /C:"LITELLM_DEFAULT_MODELS=" .env') do (
    echo [INFO] Configured AI models: %%a
)

:optional_features
echo.
echo Optional Features:
echo ------------------------------

REM Check GitHub OAuth
findstr /C:"GITHUB_CLIENT_ID=your_github_client_id" .env >nul
if %errorlevel% neq 0 (
    findstr /C:"GITHUB_CLIENT_ID=" .env | findstr /V /C:"GITHUB_CLIENT_ID=$" >nul
    if %errorlevel% equ 0 (
        echo [OK] GitHub OAuth configured
    ) else (
        echo [INFO] GitHub OAuth not configured ^(optional^)
    )
) else (
    echo [INFO] GitHub OAuth not configured ^(optional^)
)

REM Check deployment mode
for /f "tokens=2 delims==" %%a in ('findstr /C:"DEPLOYMENT_MODE=" .env') do (
    echo [INFO] Deployment mode: %%a
)

REM Check Traefik auth for Docker mode
findstr /C:"DEPLOYMENT_MODE=docker" .env >nul
if %errorlevel% equ 0 (
    findstr /C:"TRAEFIK_BASIC_AUTH=admin:$$2y$$10$$EIHbchqg0sjZLr9iZINqA.6Za7wPjGAVdTER2ob5whDLtHkkZSGbC" .env >nul
    if %errorlevel% equ 0 (
        echo [WARNING] TRAEFIK_BASIC_AUTH using default ^(admin:admin^)
        echo    Change for production!
    )
)

:check_complete
echo.
echo ============================================================

if defined HAS_ERRORS (
    echo [ERROR] Configuration has errors. Please fix them before starting.
    echo.
    echo Please update your .env file with proper values!
    pause
    exit /b 1
)

echo Configuration appears valid!
echo.
echo To start the application:
echo   Docker Compose ^(Development^):
echo     docker compose up -d
echo   Docker Compose ^(Production^):
echo     docker compose -f docker-compose.prod.yml up -d
echo.
echo Then access at:
for /f "tokens=2 delims==" %%a in ('findstr /C:"APP_PROTOCOL=" .env') do set APP_PROTOCOL=%%a
for /f "tokens=2 delims==" %%b in ('findstr /C:"APP_DOMAIN=" .env') do set APP_DOMAIN=%%b

if not defined APP_PROTOCOL set APP_PROTOCOL=http
if not defined APP_DOMAIN set APP_DOMAIN=studio.localhost

echo   Application: %APP_PROTOCOL%://%APP_DOMAIN%
echo   Traefik Dashboard: %APP_PROTOCOL%://%APP_DOMAIN%/traefik
echo      ^(default: admin/admin - change TRAEFIK_BASIC_AUTH!^)
echo ============================================================
pause
