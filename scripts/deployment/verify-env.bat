@echo off
REM Tesslate Studio - Environment Configuration Checker
REM Batch script for Windows

echo ================================================
echo Tesslate Studio - Environment Configuration Check
echo ================================================
echo.

REM Check if .env file exists
if not exist ".env" (
    echo ERROR: .env file not found!
    echo    Run: copy .env.example .env
    exit /b 1
)

echo [OK] .env file found
echo.

REM Simple check for required variables
echo Checking configuration...
echo.

findstr /C:"LITELLM_MASTER_KEY=your-litellm-master-key-here" .env >nul
if %errorlevel% equ 0 (
    echo [WARNING] LITELLM_MASTER_KEY not configured - AI features won't work
) else (
    echo [OK] LiteLLM proxy is configured

    REM Display configured models
    for /f "tokens=2 delims==" %%a in ('findstr /C:"LITELLM_DEFAULT_MODELS=" .env') do (
        echo [INFO] Configured AI models: %%a
    )
)

findstr /C:"SECRET_KEY=change-this-to-a-random-secret-key-for-security" .env >nul
if %errorlevel% equ 0 (
    echo [ERROR] SECRET_KEY not configured - using default is insecure
    echo.
    echo Please update your .env file with proper values!
    pause
    exit /b 1
) else (
    echo [OK] SECRET_KEY is configured
)

echo.
echo ================================================
echo Configuration appears valid!
echo.
echo To start the application:
echo   docker-compose up -d
echo.
echo Then access at:
echo   Application: http://studio.localhost
echo   Traefik Dashboard: http://studio.localhost/traefik (admin:admin)
echo ================================================
pause