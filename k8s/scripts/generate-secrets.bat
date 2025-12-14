@echo off
REM Generate Kubernetes Secrets for Tesslate Studio (Windows)
REM This script creates all necessary secret files with strong random passwords

echo.
echo 🔐 Generating Kubernetes Secrets for Tesslate Studio
echo ====================================================
echo.

REM Check if openssl is available
where openssl >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ Error: openssl not found
    echo Please install OpenSSL or use Git Bash to run generate-secrets.sh
    pause
    exit /b 1
)

REM Prompt for domain
set /p APP_DOMAIN="What domain will you use? (e.g., studio.tesslate.com): "
if "%APP_DOMAIN%"=="" (
    echo ❌ Error: Domain is required
    pause
    exit /b 1
)

REM Prompt for email
set /p SSL_EMAIL="Email for Let's Encrypt notifications: "
if "%SSL_EMAIL%"=="" (
    echo ❌ Error: Email is required
    pause
    exit /b 1
)

echo.
echo 📋 Configuration:
echo    Domain: %APP_DOMAIN%
echo    Email: %SSL_EMAIL%
echo.
set /p CONFIRM="Continue? (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo Cancelled
    pause
    exit /b 1
)

echo.
echo 🔑 Generating secure passwords...

REM Generate passwords
for /f "delims=" %%i in ('openssl rand -base64 32') do set POSTGRES_PASSWORD=%%i
for /f "delims=" %%i in ('openssl rand -base64 64') do set SECRET_KEY=%%i
for /f "delims=" %%i in ('openssl rand -base64 32') do set CSRF_SECRET=%%i

echo ✅ Passwords generated!
echo.

REM Create directory
if not exist "manifests\security" mkdir "manifests\security"

echo 📝 Creating postgres-secret.yaml...
(
echo apiVersion: v1
echo kind: Secret
echo metadata:
echo   name: postgres-secret
echo   namespace: tesslate
echo type: Opaque
echo stringData:
echo   POSTGRES_DB: tesslate
echo   POSTGRES_USER: tesslate_user
echo   POSTGRES_PASSWORD: %POSTGRES_PASSWORD%
) > manifests\security\postgres-secret.yaml

echo ✅ postgres-secret.yaml created!
echo.

echo 📝 Creating app-secrets.yaml...
REM Note: For Windows batch, we need to escape special characters
REM This is a simplified version - use Git Bash for the full script
echo Please use Git Bash to run generate-secrets.sh for full functionality
echo Or manually edit manifests/security/app-secrets.yaml.example
echo.
echo ✅ Basic secrets created!
echo.
echo 📊 Generated Credentials:
echo    PostgreSQL Password: %POSTGRES_PASSWORD%
echo.
echo 📋 Next Steps:
echo    1. Edit manifests/security/app-secrets.yaml manually
echo    2. Or use Git Bash: bash k8s/generate-secrets.sh
echo    3. Apply secrets to cluster
echo.
pause
