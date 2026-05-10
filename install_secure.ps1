<#
.SYNOPSIS
    WSL Manager Pro — Secure remote installer (bootstrap without cloning).

.DESCRIPTION
    Downloads the latest WSL Manager Pro repository from GitHub to the
    user's Desktop, verifies the downloaded files, and delegates to the
    local ``install.ps1`` for fully automated environment setup.

    This script is designed to be invoked remotely via::

        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force;
        irm https://raw.githubusercontent.com/wilkinbarban/WSL-Manager-Pro/master/install_secure.ps1 | iex

    It can also be run locally after downloading.

.NOTES
    * Requires Administrator privileges (auto-elevates via install.ps1).
    * The repository is cloned to ``%USERPROFILE%\Desktop\WSL-Manager-Pro``
      by default.
    * If the target directory already exists, the script updates it via
      ``git pull`` (if a ``.git`` folder is present) or prompts the user.
    * All console messages are in English.
#>

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:USERPROFILE\Desktop\WSL-Manager-Pro",
    [string]$RepoUrl   = "https://github.com/wilkinbarban/WSL-Manager-Pro.git",
    [string]$Branch    = "master"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ===========================================================================
# Console helpers
# ===========================================================================
function Write-Banner {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  WSL Manager Pro — Secure Remote Installer" -ForegroundColor White
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step { param([string]$M) Write-Host "[STEP] $M" -ForegroundColor Yellow }
function Write-Ok   { param([string]$M) Write-Host "[OK]   $M" -ForegroundColor Green }
function Write-Err  { param([string]$M) Write-Host "[ERR]  $M" -ForegroundColor Red; throw $M }

function Test-IsAdministrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ===========================================================================
# Prerequisites check
# ===========================================================================
function Test-GitAvailable {
    return $null -ne (Get-Command git -ErrorAction SilentlyContinue)
}

# ===========================================================================
# Main
# ===========================================================================
Write-Banner
Write-Host "Target directory : $InstallDir" -ForegroundColor Gray
Write-Host "Repository       : $RepoUrl"   -ForegroundColor Gray
Write-Host "Branch           : $Branch"     -ForegroundColor Gray
Write-Host ""

# Step 1 — Check prerequisites
Write-Step "Checking prerequisites..."
if (-not (Test-GitAvailable)) {
    Write-Err "Git is not installed or not on PATH. Please install Git from https://git-scm.com and retry."
}
Write-Ok "Git is available."

# Step 2 — Clone or update the repository
if (Test-Path $InstallDir) {
    Write-Step "Directory '$InstallDir' already exists."
    if (Test-Path (Join-Path $InstallDir ".git")) {
        Write-Step "Existing git repository detected. Pulling latest changes..."
        Push-Location $InstallDir
        try {
            git fetch origin
            git checkout $Branch
            git pull origin $Branch
            Write-Ok "Repository updated successfully."
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "[WARN] Directory exists but is not a git repository." -ForegroundColor DarkYellow
        $response = Read-Host "Remove and re-clone? (y/N)"
        if ($response -eq 'y' -or $response -eq 'Y') {
            Write-Step "Removing existing directory..."
            Remove-Item -Path $InstallDir -Recurse -Force
            Write-Step "Cloning repository..."
            git clone --branch $Branch --depth 1 $RepoUrl $InstallDir
            Write-Ok "Repository cloned successfully."
        } else {
            Write-Host "[INFO] Will attempt to use existing directory. If install.ps1 is missing, it will fail." -ForegroundColor Gray
        }
    }
} else {
    Write-Step "Cloning repository to '$InstallDir'..."
    $parentDir = Split-Path -Parent $InstallDir
    if (-not (Test-Path $parentDir)) {
        New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
    }
    git clone --branch $Branch --depth 1 $RepoUrl $InstallDir
    Write-Ok "Repository cloned successfully."
}

# Step 3 — Verify critical files
Write-Step "Verifying critical files..."
$installScript = Join-Path $InstallDir "install.ps1"
$distrosFile   = Join-Path $InstallDir "distros.json"

$missing = @()
if (-not (Test-Path $installScript)) { $missing += "install.ps1" }
if (-not (Test-Path $distrosFile))   { $missing += "distros.json" }

if ($missing.Count -gt 0) {
    Write-Err "Critical files missing: $($missing -join ', '). The repository may be incomplete or the branch may not contain these files."
}
Write-Ok "All critical files present."

# Step 4 — Delegate to install.ps1
Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host "  Delegating to install.ps1 for automated setup..." -ForegroundColor White
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host ""

Push-Location $InstallDir
try {
    if (Test-IsAdministrator) {
        & .\install.ps1
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Err "install.ps1 returned exit code $LASTEXITCODE. Please review the output above."
        }
    } else {
        Write-Step "Requesting elevation and waiting for install.ps1 to complete..."
        $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -PassThru -Wait -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$installScript`""
        )
        if ($null -eq $proc) {
            Write-Err "Could not launch elevated install.ps1 process."
        }
        if ($proc.ExitCode -ne 0) {
            Write-Host ""
            Write-Err "Elevated install.ps1 returned exit code $($proc.ExitCode). Please review the elevated console output."
        }
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host "  WSL Manager Pro — Setup complete!" -ForegroundColor White
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""
Write-Host "The project is located at: $InstallDir" -ForegroundColor Cyan
Write-Host ""
Write-Host "To launch the application:" -ForegroundColor Gray
Write-Host "  cd `"$InstallDir`"" -ForegroundColor White
Write-Host "  .\.venv\Scripts\python.exe .\main.py" -ForegroundColor White
Write-Host ""
Read-Host -Prompt "Press Enter to close this window"
