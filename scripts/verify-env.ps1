# Tesslate Studio - Environment Configuration Checker
# PowerShell script for Windows

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Tesslate Studio - Environment Configuration Check" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Check if .env file exists
if (-not (Test-Path ".env")) {
    Write-Host "ERROR: .env file not found!" -ForegroundColor Red
    Write-Host "   Run: Copy-Item .env.example .env" -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] .env file found" -ForegroundColor Green
Write-Host ""

# Read .env file
$envContent = Get-Content ".env" | Where-Object { $_ -notmatch '^\s*#' -and $_ -match '=' }
$envVars = @{}

foreach ($line in $envContent) {
    if ($line -match '^([^=]+)=(.*)$') {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim()

        # Handle variable substitution for common patterns
        if ($value -match '\$\{([^}]+)\}') {
            $varName = $matches[1]
            if ($envVars.ContainsKey($varName)) {
                $value = $value -replace "\$\{$varName\}", $envVars[$varName]
            }
        }

        $envVars[$key] = $value
    }
}

Write-Host "Current Configuration:" -ForegroundColor White
Write-Host "----------------------"
Write-Host "  Domain: $($envVars['APP_DOMAIN'])" -ForegroundColor Cyan
Write-Host "  Protocol: $($envVars['APP_PROTOCOL'])" -ForegroundColor Cyan
Write-Host "  Full URL: $($envVars['APP_PROTOCOL'])://$($envVars['APP_DOMAIN'])" -ForegroundColor Cyan
Write-Host "  Ports:" -ForegroundColor Cyan
Write-Host "   - Web: $($envVars['APP_PORT'])" -ForegroundColor Gray
Write-Host "   - Secure: $($envVars['APP_SECURE_PORT'])" -ForegroundColor Gray
Write-Host "   - Backend: $($envVars['BACKEND_PORT'])" -ForegroundColor Gray
Write-Host "   - Frontend: $($envVars['FRONTEND_PORT'])" -ForegroundColor Gray
Write-Host "   - Traefik Dashboard: $($envVars['TRAEFIK_DASHBOARD_PORT'])" -ForegroundColor Gray
Write-Host ""

Write-Host "Required Variables Check:" -ForegroundColor White
Write-Host "-------------------------"

$hasErrors = $false
$hasWarnings = $false

# Check SECRET_KEY
if (-not $envVars['SECRET_KEY'] -or $envVars['SECRET_KEY'] -eq 'change-this-to-a-random-secret-key-for-security') {
    Write-Host "[ERROR] SECRET_KEY not configured (using default is insecure)" -ForegroundColor Red
    $hasErrors = $true
} else {
    Write-Host "[OK] SECRET_KEY is configured" -ForegroundColor Green
}

# Check LiteLLM Configuration
if (-not $envVars['LITELLM_MASTER_KEY'] -or $envVars['LITELLM_MASTER_KEY'] -eq 'your-litellm-master-key-here') {
    Write-Host "[WARNING] LITELLM_MASTER_KEY not configured (AI features won't work)" -ForegroundColor Yellow
    Write-Host "    Using LiteLLM proxy at: $($envVars['LITELLM_API_BASE'])" -ForegroundColor Gray
    $hasWarnings = $true
} else {
    Write-Host "[OK] LiteLLM proxy configured at $($envVars['LITELLM_API_BASE'])" -ForegroundColor Green

    # Display configured models
    if ($envVars['LITELLM_DEFAULT_MODELS']) {
        Write-Host "   Configured AI models:" -ForegroundColor Green
        $models = $envVars['LITELLM_DEFAULT_MODELS'] -split ','
        foreach ($model in $models) {
            Write-Host "      - $($model.Trim())" -ForegroundColor Gray
        }
    }
}

Write-Host ""
Write-Host "Optional Features:" -ForegroundColor White
Write-Host "------------------"

# Check GitHub OAuth
if ($envVars['GITHUB_CLIENT_ID'] -and $envVars['GITHUB_CLIENT_ID'] -ne 'your_github_client_id_here') {
    Write-Host "[OK] GitHub OAuth configured" -ForegroundColor Green
} else {
    Write-Host "[INFO] GitHub OAuth not configured (optional)" -ForegroundColor Gray
}

# Check LiteLLM
if ($envVars['LITELLM_MASTER_KEY'] -and $envVars['LITELLM_MASTER_KEY'] -ne 'your_litellm_master_key_here') {
    Write-Host "[OK] LiteLLM configured" -ForegroundColor Green
} else {
    Write-Host "[INFO] LiteLLM not configured (optional)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan

$appUrl = "$($envVars['APP_PROTOCOL'])://$($envVars['APP_DOMAIN'])"

if ($hasErrors) {
    Write-Host "[ERROR] Configuration has errors. Please fix them before starting." -ForegroundColor Red
    exit 1
} elseif ($hasWarnings) {
    Write-Host "[WARNING] Configuration has warnings. Some features may not work." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "To start the application:" -ForegroundColor White
    Write-Host "  docker-compose up -d" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Then access at:" -ForegroundColor White
    Write-Host "  Application: $appUrl" -ForegroundColor Green
    Write-Host "  Traefik Dashboard: $appUrl/traefik (admin:admin)" -ForegroundColor Green
} else {
    Write-Host "[OK] Configuration is perfect!" -ForegroundColor Green
    Write-Host ""
    Write-Host "To start the application:" -ForegroundColor White
    Write-Host "  docker-compose up -d" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Then access at:" -ForegroundColor White
    Write-Host "  Application: $appUrl" -ForegroundColor Green
    Write-Host "  Traefik Dashboard: $appUrl/traefik (admin:admin)" -ForegroundColor Green
}
Write-Host "================================================" -ForegroundColor Cyan