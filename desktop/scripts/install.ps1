# OpenSail desktop installer for Windows.
#
# Usage:
#   irm <DOWNLOAD_HOST>/install.ps1 | iex
#
# Downloads the NSIS installer and runs it silently. The install is per-user
# (lands in %LOCALAPPDATA%\OpenSail) and needs no admin rights — the MSI is
# deliberately not used here because its per-machine scope forces a UAC prompt.
#
# Override the source or pinned version with environment variables:
#   $env:OPENSAIL_INSTALL_BASE_URL = '...'
#   $env:OPENSAIL_VERSION = '0.1.0'

$ErrorActionPreference = 'Stop'

# ── configuration ──────────────────────────────────────────────────────────
# Download host. The orchestrator at your-domain.com serves the desktop
# release surface (see orchestrator/app/routers/desktop_releases.py) and
# 302-redirects to the actual binary on GitHub Releases. Override with
# OPENSAIL_INSTALL_BASE_URL for self-hosted Studio deployments.
$baseUrl = if ($env:OPENSAIL_INSTALL_BASE_URL) { $env:OPENSAIL_INSTALL_BASE_URL }
           else { 'https://your-domain.com/desktop/releases' }
$version = if ($env:OPENSAIL_VERSION) { $env:OPENSAIL_VERSION } else { '0.1.0' }

# ── detect architecture ────────────────────────────────────────────────────
$arch = switch ($env:PROCESSOR_ARCHITECTURE) {
    'AMD64' { 'x64' }
    default { throw "unsupported architecture: $($env:PROCESSOR_ARCHITECTURE) (only x64 builds are published)" }
}

$artifact = "OpenSail_${version}_${arch}-setup.exe"
$url      = "$baseUrl/$version/$artifact"
$dest     = Join-Path $env:TEMP $artifact

# ── download ───────────────────────────────────────────────────────────────
Write-Host "opensail-install: downloading $url"
# TODO(release): verify a published .sha256 alongside the artifact.
try {
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
} catch {
    throw "download failed: $url`n$_"
}

# ── install ────────────────────────────────────────────────────────────────
Write-Host 'opensail-install: running installer (per-user, silent)'
$proc = Start-Process -FilePath $dest -ArgumentList '/S' -Wait -PassThru
Remove-Item $dest -ErrorAction SilentlyContinue

if ($proc.ExitCode -ne 0) {
    throw "installer exited with code $($proc.ExitCode)"
}

$installDir = Join-Path $env:LOCALAPPDATA 'OpenSail'
Write-Host "opensail-install: done — installed to $installDir"
Write-Host 'opensail-install: launch OpenSail from the Start menu.'
