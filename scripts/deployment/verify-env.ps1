# Tesslate Studio - Environment Configuration Checker
# PowerShell script for Windows

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Tesslate Studio - Environment Configuration Check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Check if .env file exists
if (-not (Test-Path ".env")) {
    Write-Host "[ERROR] .env file not found!" -ForegroundColor Red
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
Write-Host "------------------------------"

$domain = if ($envVars['APP_DOMAIN']) { $envVars['APP_DOMAIN'] } else { "studio.localhost" }
$protocol = if ($envVars['APP_PROTOCOL']) { $envVars['APP_PROTOCOL'] } else { "http" }
$appUrl = "$protocol`://$domain"

Write-Host "  Domain: $domain" -ForegroundColor Cyan
Write-Host "  Protocol: $protocol" -ForegroundColor Cyan
Write-Host "  Full URL: $appUrl" -ForegroundColor Cyan
Write-Host "  Ports:" -ForegroundColor Cyan

$appPort = if ($envVars['APP_PORT']) { $envVars['APP_PORT'] } else { "80" }
$securePort = if ($envVars['APP_SECURE_PORT']) { $envVars['APP_SECURE_PORT'] } else { "443" }
$backendPort = if ($envVars['BACKEND_PORT']) { $envVars['BACKEND_PORT'] } else { "8000" }
$frontendPort = if ($envVars['FRONTEND_PORT']) { $envVars['FRONTEND_PORT'] } else { "5173" }
$traefikPort = if ($envVars['TRAEFIK_DASHBOARD_PORT']) { $envVars['TRAEFIK_DASHBOARD_PORT'] } else { "8080" }

Write-Host "   - Web: $appPort" -ForegroundColor Gray
Write-Host "   - Secure: $securePort" -ForegroundColor Gray
Write-Host "   - Backend: $backendPort" -ForegroundColor Gray
Write-Host "   - Frontend: $frontendPort" -ForegroundColor Gray
Write-Host "   - Traefik Dashboard: $traefikPort" -ForegroundColor Gray
Write-Host ""

Write-Host "Required Variables Check:" -ForegroundColor White
Write-Host "------------------------------"

$hasErrors = $false
$hasWarnings = $false

# Check SECRET_KEY
$defaultSecretKeys = @(
    'your-secret-key-here-change-this-in-production',
    'your_secret_key_here',
    'change-this-in-production',
    'change-this-to-a-random-secret-key-for-security'
)

if (-not $envVars['SECRET_KEY'] -or $defaultSecretKeys -contains $envVars['SECRET_KEY']) {
    Write-Host "[ERROR] SECRET_KEY not configured (using default is insecure)" -ForegroundColor Red
    Write-Host "   Generate with: openssl rand -base64 64" -ForegroundColor Gray
    $hasErrors = $true
} else {
    Write-Host "[OK] SECRET_KEY is configured" -ForegroundColor Green
}

# Check Database Configuration
$defaultDbPasswords = @('dev_password_change_me', 'your_postgres_password_here')

if (-not $envVars['DATABASE_URL']) {
    Write-Host "[ERROR] DATABASE_URL not configured" -ForegroundColor Red
    $hasErrors = $true
} elseif ($envVars['POSTGRES_PASSWORD'] -and $defaultDbPasswords -contains $envVars['POSTGRES_PASSWORD']) {
    Write-Host "[WARNING] POSTGRES_PASSWORD using default (change for production)" -ForegroundColor Yellow
    Write-Host "   Generate with: openssl rand -base64 32" -ForegroundColor Gray
    $hasWarnings = $true
} else {
    Write-Host "[OK] Database configured" -ForegroundColor Green
}

# Check LiteLLM Configuration
$defaultLitellmKeys = @('your-litellm-master-key-here', 'your_litellm_master_key_here')

if (-not $envVars['LITELLM_API_BASE'] -or $envVars['LITELLM_API_BASE'] -match '^https://your-litellm') {
    Write-Host "[WARNING] LITELLM_API_BASE not configured (AI features won't work)" -ForegroundColor Yellow
    $hasWarnings = $true
} elseif (-not $envVars['LITELLM_MASTER_KEY'] -or $defaultLitellmKeys -contains $envVars['LITELLM_MASTER_KEY']) {
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
Write-Host "------------------------------"

# Check GitHub OAuth
$defaultGithubValues = @('your_github_client_id', 'your_github_client_secret')

if ($envVars['GITHUB_CLIENT_ID'] -and $envVars['GITHUB_CLIENT_SECRET'] -and
    $defaultGithubValues -notcontains $envVars['GITHUB_CLIENT_ID'] -and
    $defaultGithubValues -notcontains $envVars['GITHUB_CLIENT_SECRET']) {
    Write-Host "[OK] GitHub OAuth configured" -ForegroundColor Green
} else {
    Write-Host "[INFO] GitHub OAuth not configured (optional)" -ForegroundColor Gray
}

# Deployment mode
$deploymentMode = if ($envVars['DEPLOYMENT_MODE']) { $envVars['DEPLOYMENT_MODE'] } else { "docker" }
Write-Host "[INFO] Deployment mode: $deploymentMode" -ForegroundColor Cyan

# Traefik configuration (Docker mode only)
if ($deploymentMode -eq 'docker') {
    $certResolver = if ($envVars['TRAEFIK_CERT_RESOLVER']) { $envVars['TRAEFIK_CERT_RESOLVER'] } else { "letsencrypt" }
    Write-Host "[INFO] SSL certificate resolver: $certResolver" -ForegroundColor Cyan

    $defaultTraefikHash = 'admin:$$2y$$10$$EIHbchqg0sjZLr9iZINqA.6Za7wPjGAVdTER2ob5whDLtHkkZSGbC'
    if (-not $envVars['TRAEFIK_BASIC_AUTH'] -or $envVars['TRAEFIK_BASIC_AUTH'] -eq $defaultTraefikHash) {
        Write-Host "[WARNING] TRAEFIK_BASIC_AUTH using default (admin:admin) - Change for production!" -ForegroundColor Yellow
        $hasWarnings = $true
    } else {
        Write-Host "[OK] Traefik dashboard auth configured" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan

# Final status
if ($hasErrors) {
    Write-Host "[ERROR] Configuration has errors. Please fix them before starting." -ForegroundColor Red
} elseif ($hasWarnings) {
    Write-Host "[WARNING] Configuration has warnings. Some features may not work." -ForegroundColor Yellow
} else {
    Write-Host "[OK] Configuration is perfect!" -ForegroundColor Green
}

Write-Host ""
Write-Host "To start the application:" -ForegroundColor White

if ($deploymentMode -eq 'docker') {
    Write-Host "  Docker Compose (Development):" -ForegroundColor Gray
    Write-Host "    docker compose up -d" -ForegroundColor Cyan
    Write-Host "  Docker Compose (Production):" -ForegroundColor Gray
    Write-Host "    docker compose -f docker-compose.prod.yml up -d" -ForegroundColor Cyan
} else {
    Write-Host "  Kubernetes:" -ForegroundColor Gray
    Write-Host "    cd k8s && ./scripts/deployment/deploy-all.sh" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Then access at:" -ForegroundColor White
Write-Host "  Application: $appUrl" -ForegroundColor Green

if ($deploymentMode -eq 'docker') {
    Write-Host "  Traefik Dashboard: $appUrl/traefik" -ForegroundColor Green
    Write-Host "     (default: admin/admin - change TRAEFIK_BASIC_AUTH!)" -ForegroundColor Gray
}

Write-Host "============================================================" -ForegroundColor Cyan

if ($hasErrors) {
    exit 1
}
