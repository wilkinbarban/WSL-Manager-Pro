<#
.SYNOPSIS
    WSL Manager Pro — Secure remote installer (download without Git).

.DESCRIPTION
    Downloads the latest WSL Manager Pro repository from GitHub as a ZIP
    archive to the user's Desktop, extracts it, verifies the downloaded
    files, and delegates to the local ``install.ps1`` for fully automated
    environment setup.

    This script is designed to be invoked remotely via::

        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force;
        irm https://raw.githubusercontent.com/wilkinbarban/WSL-Manager-Pro/master/install_secure.ps1 | iex

    It can also be run locally after downloading.

.NOTES
    * Requires Administrator privileges (auto-elevates via install.ps1).
    * The repository is downloaded and extracted to
      ``%USERPROFILE%\Desktop\WSL-Manager-Pro`` by default.
    * If the target directory already exists, it is removed and re-created.
    * No Git installation required — uses built-in PowerShell ``Invoke-WebRequest``
      and ``Expand-Archive``.
    * All console messages are in English.
#>

[CmdletBinding()]
param(
    [string]$InstallDir = "$env:USERPROFILE\Desktop\WSL-Manager-Pro",
    [string]$RepoUrl   = "https://github.com/wilkinbarban/WSL-Manager-Pro",
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
function Write-Warn { param([string]$M) Write-Host "[WARN] $M" -ForegroundColor DarkYellow }

function Test-IsAdministrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ===========================================================================
# Main
# ===========================================================================
Write-Banner
Write-Host "Target directory : $InstallDir" -ForegroundColor Gray
Write-Host "Repository       : $RepoUrl"   -ForegroundColor Gray
Write-Host "Branch           : $Branch"     -ForegroundColor Gray
Write-Host ""

# Step 1 — Prepare ZIP download URL
$zipUrl = "$RepoUrl/archive/refs/heads/$Branch.zip"
$zipPath = Join-Path $env:TEMP "WSL-Manager-Pro-$Branch.zip"
$extractPath = Join-Path $env:TEMP "WSL-Manager-Pro-extract"

# Step 2 — Download repository as ZIP
Write-Step "Downloading repository from $zipUrl ..."
try {
    # Remove any previous temporary files
    if (Test-Path $zipPath) { Remove-Item -Path $zipPath -Force }
    if (Test-Path $extractPath) { Remove-Item -Path $extractPath -Recurse -Force }

    # Download with progress bar
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
    Write-Ok "Repository ZIP downloaded successfully ($([math]::Round((Get-Item $zipPath).Length / 1KB)) KB)."
}
catch {
    Write-Err "Failed to download repository from $zipUrl. Check your internet connection and try again."
}

# Step 3 — Extract ZIP
Write-Step "Extracting archive..."
try {
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
    Write-Ok "Archive extracted successfully."
}
catch {
    Write-Err "Failed to extract the downloaded ZIP archive. The file may be corrupted."
}

# The ZIP contains a top-level folder named "WSL-Manager-Pro-<branch>"
$extractedFolder = Join-Path $extractPath "WSL-Manager-Pro-$Branch"
if (-not (Test-Path $extractedFolder)) {
    # Fallback: try to find any single folder inside the extract path
    $items = Get-ChildItem -Path $extractPath -Directory
    if ($items.Count -eq 1) {
        $extractedFolder = $items[0].FullName
    } else {
        Write-Err "Could not locate the extracted repository folder."
    }
}
Write-Ok "Found extracted repository at: $extractedFolder"

# Step 4 — Copy to target directory
Write-Step "Copying files to '$InstallDir'..."
if (Test-Path $InstallDir) {
    Write-Step "Removing previous installation directory..."
    Remove-Item -Path $InstallDir -Recurse -Force
    Write-Ok "Previous installation removed."
}

# Create parent directory if needed
$parentDir = Split-Path -Parent $InstallDir
if (-not (Test-Path $parentDir)) {
    New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
}

# Re-create the target directory explicitly (ensures it's a container,
# not a leftover leaf item, which can happen when running via iex).
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

# Copy contents (not the folder itself) to the target
Copy-Item -Path "$extractedFolder\*" -Destination $InstallDir -Recurse -Force
Write-Ok "Files copied to target directory."

# Step 5 — Clean up temporary files
Write-Step "Cleaning up temporary files..."
Remove-Item -Path $zipPath -Force -ErrorAction SilentlyContinue
Remove-Item -Path $extractPath -Recurse -Force -ErrorAction SilentlyContinue
Write-Ok "Temporary files cleaned up."

# Step 6 — Verify critical files
Write-Step "Verifying critical files..."
$installScript = Join-Path $InstallDir "install.ps1"
$distrosFile   = Join-Path $InstallDir "distros.json"

$missing = @()
if (-not (Test-Path $installScript)) { $missing += "install.ps1" }
if (-not (Test-Path $distrosFile))   { $missing += "distros.json" }

if ($missing.Count -gt 0) {
    Write-Err "Critical files missing: $($missing -join ', '). The download may be incomplete or the branch may not contain these files."
}
Write-Ok "All critical files present."

# Step 7 — Delegate to install.ps1
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
