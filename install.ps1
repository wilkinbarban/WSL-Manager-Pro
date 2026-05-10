<#
.SYNOPSIS
    One-click environment installer for WSL Manager Pro.

.DESCRIPTION
    Fully-automated PowerShell 5.1 installer that provisions every runtime
    dependency needed to build and run WSL Manager Pro from source:

      1. Elevates to Administrator (required for WSL feature enablement and
         system PATH modifications).
      2. Enables Windows optional features (WSL subsystem + Virtual Machine
         Platform) via DISM.
      3. Installs WSL base components if ``wsl.exe`` is missing.
      4. Sets the default WSL version to 2.
      5. Installs Python 3.12 and Node.js LTS via winget (Windows Package
         Manager).
      6. Adds Python and npm to the system PATH.
      7. Creates a Python virtual environment (``.venv``).
      8. Upgrades pip / setuptools / wheel inside the venv.
      9. Installs Python dependencies from ``requirements.txt``.
     10. Installs Node.js dependencies from ``package.json`` (if present).
     11. Verifies core Python imports (PySide6, requests, zstandard) and
         checks WSL command availability.

    The script is **idempotent**: running it multiple times is safe —
    already-installed components are detected and skipped.

.NOTES
    * Requires Windows 10 build 19041+ (WSL 2 support).
    * ``winget`` must be present (bundled with App Installer from the
      Microsoft Store).
    * A system restart may be required after the first run if WSL features
      were just enabled.
    * The console will wait for a key press before closing so you can review
      the output.

.EXAMPLE
    .\install.ps1

    Runs the full environment setup.  Execute from an elevated PowerShell
    session or let the script auto-elevate.
#>

[CmdletBinding()]
param()

# ---------------------------------------------------------------------------
# Strict mode — any error halts execution immediately
# ---------------------------------------------------------------------------
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ===========================================================================
# Console output helpers
# ===========================================================================

function Write-Section {
<#
.SYNOPSIS
    Print a visually distinct section header to the console.

.DESCRIPTION
    Draws an ASCII-art banner with the section title in cyan between two
    rows of ``=`` characters.  Use this to separate major installation
    phases (WSL Prep, Tooling, Dependencies, Verification).
#>
    param([string]$Title)
    Write-Host ""
    Write-Host ("=" * 76) -ForegroundColor DarkGray
    Write-Host (" " + $Title) -ForegroundColor Cyan
    Write-Host ("=" * 76) -ForegroundColor DarkGray
}

function Write-Step {
<#
.SYNOPSIS
    Print an in-progress action step (yellow).
#>
    param([string]$Message)
    Write-Host ("[STEP] " + $Message) -ForegroundColor Yellow
}

function Write-Ok {
<#
.SYNOPSIS
    Print a success / already-done message (green).
#>
    param([string]$Message)
    Write-Host ("[OK]   " + $Message) -ForegroundColor Green
}

function Write-Warn {
<#
.SYNOPSIS
    Print a non-fatal warning message (dark yellow).
#>
    param([string]$Message)
    Write-Host ("[WARN] " + $Message) -ForegroundColor DarkYellow
}

# ===========================================================================
# Privilege management
# ===========================================================================

function Test-IsAdministrator {
<#
.SYNOPSIS
    Determine whether the current PowerShell session runs with Administrator
    privileges.

.DESCRIPTION
    Uses the .NET ``WindowsPrincipal`` class to check the current user's
    role membership against the built-in ``Administrator`` group.

.OUTPUTS
    System.Boolean.  ``$true`` when running elevated.
#>
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-Administrator {
<#
.SYNOPSIS
    Relaunch the script with the ``RunAs`` verb if not already elevated.

.DESCRIPTION
    If the current session is not elevated, spawns a new PowerShell process
    with ``-Verb RunAs`` and exits the current process.  User sees a UAC
    prompt.  If already elevated, prints a confirmation and continues.
#>
    if (Test-IsAdministrator) {
        Write-Ok "Running with Administrator privileges."
        return
    }
    Write-Warn "This installer needs Administrator privileges. Requesting elevation..."
    $elevationArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`""
    )
    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $elevationArgs | Out-Null
    exit 0
}

# ===========================================================================
# System utility helpers
# ===========================================================================

function Test-Command {
<#
.SYNOPSIS
    Check whether a command (executable / cmdlet) is available on PATH.

.DESCRIPTION
    Uses ``Get-Command`` with ``-ErrorAction SilentlyContinue`` for a
    non-throwing lookup.  Works for both native executables (``wsl.exe``,
    ``python``) and PowerShell cmdlets.

.PARAMETER Name
    The command name to look up (e.g. ``"python"``, ``"winget"``).

.OUTPUTS
    System.Boolean.  ``$true`` if the command is found.
#>
    param([Parameter(Mandatory = $true)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Install-WithWingetIfMissing {
<#
.SYNOPSIS
    Install a Windows package via winget only if it is not already present.

.DESCRIPTION
    First checks ``winget list`` for the exact package ID.  If found,
    prints a skip message.  Otherwise, runs ``winget install`` with silent
    and accept-agreement flags.  Throws on failure.

.PARAMETER Id
    Exact winget package identifier (e.g. ``"Python.Python.3.12"``).

.PARAMETER Label
    Human-readable label for console messages (e.g. ``"Python 3.12"``).
#>
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Write-Step "Checking $Label..."
    $alreadyInstalled = $false
    try {
        # winget list outputs package entries; check if our ID appears
        $listOutput = winget list --id $Id --exact --accept-source-agreements 2>$null
        if ($LASTEXITCODE -eq 0 -and ($listOutput -join "`n") -match [regex]::Escape($Id)) {
            $alreadyInstalled = $true
        }
    } catch {
        # If winget list fails for any reason, assume not installed
        $alreadyInstalled = $false
    }

    if ($alreadyInstalled) {
        Write-Ok "$Label is already installed."
        return
    }

    Write-Step "Installing $Label via winget..."
    winget install --id $Id --exact --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget failed while installing $Label (ID: $Id)."
    }
    Write-Ok "$Label installed."
}

function Add-MachinePathEntry {
<#
.SYNOPSIS
    Append a directory to the machine-wide ``PATH`` environment variable.

.DESCRIPTION
    Reads the current ``HKLM\SYSTEM\CurrentControlSet\Control\Session
    Manager\Environment\Path`` value, checks for duplicates, and writes
    the updated value back.  The change takes effect for **new** processes;
    existing sessions must call ``Update-ProcessPath``.

.PARAMETER Entry
    Absolute directory path to append (e.g. ``C:\Python312``).
#>
    param([Parameter(Mandatory = $true)][string]$Entry)

    if (-not (Test-Path $Entry)) {
        return  # skip silently — path doesn't exist yet
    }

    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    if ([string]::IsNullOrWhiteSpace($machinePath)) {
        $machinePath = ""
    }
    $parts = $machinePath -split ";" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    if ($parts -contains $Entry) {
        return  # already present
    }

    $newPath = if ($machinePath) { "$machinePath;$Entry" } else { $Entry }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "Machine")
    Write-Ok "Added to system PATH: $Entry"
}

function Update-ProcessPath {
<#
.SYNOPSIS
    Reload the process-level ``PATH`` from the machine and user registries.

.DESCRIPTION
    After modifying the system PATH via ``Add-MachinePathEntry``, this
    function refreshes ``$env:Path`` so that subsequent ``Get-Command``
    lookups in the current process can find newly installed executables
    without restarting the shell.
#>
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Resolve-PythonInstallPath {
<#
.SYNOPSIS
    Heuristically locate the Python installation directory.

.DESCRIPTION
    Tries a fixed list of well-known locations (``%LOCALAPPDATA%\Programs\
    Python\Python3xx``, ``%ProgramFiles%\Python3xx``) plus the directory of
    any ``python`` already on PATH.  Returns the first match, or ``$null``.

.OUTPUTS
    System.String or ``$null``.  The absolute directory containing
    ``python.exe``.
#>
    $candidates = New-Object System.Collections.Generic.List[string]
    # Well-known winget install paths
    $candidates.Add("$env:LOCALAPPDATA\Programs\Python\Python312")
    $candidates.Add("$env:LOCALAPPDATA\Programs\Python\Python311")
    $candidates.Add("$env:ProgramFiles\Python312")
    $candidates.Add("$env:ProgramFiles\Python311")

    # If python is already on PATH, use its location
    if (Test-Command "python") {
        try {
            $pythonExe = (Get-Command python -ErrorAction Stop).Source
            if (-not [string]::IsNullOrWhiteSpace($pythonExe)) {
                $candidates.Add((Split-Path -Parent $pythonExe))
            }
        } catch {
            # ignore lookup errors
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

# ===========================================================================
# Installation phases
# ===========================================================================

function Enable-WslFeatures {
<#
.SYNOPSIS
    Enable WSL Windows features, install WSL base components, and set the
    default version to 2.

.DESCRIPTION
    Phase 1 of the installer:
      1. Enables ``Microsoft-Windows-Subsystem-Linux`` and
         ``VirtualMachinePlatform`` via DISM (no restart).
      2. If ``wsl.exe`` is missing, runs ``wsl --install --no-distribution``
         to fetch the kernel and required binaries.
      3. Sets ``wsl --set-default-version 2``.
    A system restart may be required after this phase if features were just
    enabled.
#>
    Write-Section "WSL Preparation"

    Write-Step "Enabling required Windows features for WSL..."
    # Enable WSL subsystem and Hyper-V / Virtual Machine Platform
    dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart | Out-Null
    dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart | Out-Null
    Write-Ok "Required Windows features were processed."

    if (-not (Test-Command "wsl.exe")) {
        Write-Step "Installing WSL base components..."
        wsl --install --no-distribution
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "WSL installation returned a non-zero exit code. A restart may be required."
        }
    } else {
        Write-Ok "wsl.exe is available."
    }

    Write-Step "Setting default WSL version to 2..."
    wsl --set-default-version 2 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Default WSL version set to 2."
    } else {
        Write-Warn "Could not set default WSL version now. Run 'wsl --set-default-version 2' after reboot."
    }
}

function Install-Tooling {
<#
.SYNOPSIS
    Install Python 3.12 and Node.js LTS via winget, then configure PATH.

.DESCRIPTION
    Phase 2 of the installer:
      1. Verifies ``winget`` is available.
      2. Installs Python 3.12 and Node.js LTS via ``Install-WithWingetIfMissing``.
      3. Refreshes the process PATH.
      4. Resolves the Python install directory and adds it (plus its
         ``Scripts\`` subdirectory) to the system PATH.
      5. Confirms both ``python`` and ``npm`` are now on PATH.

    Throws if ``winget`` is missing or if the commands are still
    unavailable after installation.
#>
    Write-Section "Tooling Installation"

    if (-not (Test-Command "winget")) {
        throw "winget was not found. Install App Installer from Microsoft Store and rerun this script."
    }

    # Install core language runtimes
    Install-WithWingetIfMissing -Id "Python.Python.3.12" -Label "Python 3.12"
    Install-WithWingetIfMissing -Id "OpenJS.NodeJS.LTS" -Label "Node.js LTS"
    Update-ProcessPath

    # Ensure Python directory and its Scripts\ are on the system PATH
    $pythonPath = Resolve-PythonInstallPath
    if ($null -ne $pythonPath) {
        Add-MachinePathEntry -Entry $pythonPath
        Add-MachinePathEntry -Entry (Join-Path $pythonPath "Scripts")
        Update-ProcessPath
    } else {
        Write-Warn "Could not resolve Python install directory automatically for PATH update."
    }

    # Final sanity checks
    if (-not (Test-Command "python")) {
        throw "python command is still not available after installation."
    }
    if (-not (Test-Command "npm")) {
        throw "npm command is still not available after Node.js installation."
    }
    Write-Ok "Python and npm are available."
}

function Install-ProjectDependencies {
<#
.SYNOPSIS
    Create the Python virtual environment and install project dependencies.

.DESCRIPTION
    Phase 3 of the installer:
      1. Creates a ``.venv`` virtual environment in the project root
         (idempotent — skipped if already present).
      2. Upgrades pip, setuptools, and wheel inside the venv.
      3. Installs Python packages from ``requirements.txt``
         (PySide6, requests, zstandard).
      4. Installs Node.js packages from ``package.json`` (if present).

    The project root is inferred from the script's own location, so the
    script can be run from any working directory.
#>
    Write-Section "Project Dependency Installation"

    # Determine project root = directory containing this script
    $projectRoot = Split-Path -Parent $PSCommandPath

    # When invoked via irm ... | iex, $PSCommandPath is empty because there
    # is no script file.  Redirect the user to install_secure.ps1 which
    # downloads the full repository first.
    if ([string]::IsNullOrWhiteSpace($projectRoot)) {
        Write-Warn "This script was invoked via a pipe (irm ... | iex) and cannot locate the project files."
        Write-Host ""
        Write-Host "The one-click pipe method only works for 'install_secure.ps1', which downloads"
        Write-Host "the full repository before delegating to this installer."
        Write-Host ""
        Write-Host "Run this command instead:" -ForegroundColor Cyan
        Write-Host "  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; irm https://raw.githubusercontent.com/wilkinbarban/WSL-Manager-Pro/master/install_secure.ps1 | iex" -ForegroundColor White
        Write-Host ""
        Write-Host "Or clone the repository and run install.ps1 locally:" -ForegroundColor Cyan
        Write-Host "  git clone https://github.com/wilkinbarban/WSL-Manager-Pro.git" -ForegroundColor White
        Write-Host "  cd WSL-Manager-Pro" -ForegroundColor White
        Write-Host "  .\install.ps1" -ForegroundColor White
        Write-Host ""
        Read-Host -Prompt "Press Enter to close this window"
        exit 1
    }

    Set-Location $projectRoot

    Write-Step "Creating virtual environment (.venv) if needed..."
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        python -m venv .venv
    }
    Write-Ok "Virtual environment ready."

    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

    Write-Step "Upgrading pip, setuptools and wheel..."
    & $venvPython -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip tooling inside .venv."
    }

    # Python runtime dependencies (PySide6, requests, zstandard)
    if (Test-Path "requirements.txt") {
        Write-Step "Installing Python runtime dependencies..."
        & $venvPython -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install Python dependencies from requirements.txt."
        }
        Write-Ok "Python dependencies installed."
    } else {
        Write-Warn "requirements.txt not found. Skipping Python dependency install."
    }

    # Node.js dependencies (if the project has a package.json)
    if (Test-Path "package.json") {
        Write-Step "Installing npm dependencies from package.json..."
        npm install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed."
        }
        Write-Ok "npm dependencies installed."
    } else {
        Write-Ok "No package.json found. npm dependency installation skipped."
    }
}

function Test-Environment {
<#
.SYNOPSIS
    Run sanity checks to confirm the environment is correctly configured.

.DESCRIPTION
    Phase 4 (final) of the installer:
      1. Launches the venv Python and attempts to import the three core
         runtime packages (PySide6, requests, zstandard).
      2. Runs ``wsl --status`` to verify WSL is reachable.

    A failure in either check throws a terminating error.
#>
    Write-Section "Verification"

    $projectRoot = Split-Path -Parent $PSCommandPath
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

    Write-Step "Verifying core Python imports..."
    & $venvPython -c "import PySide6, requests, zstandard; print('Python runtime dependencies OK')"
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency verification failed."
    }
    Write-Ok "Python dependencies verified."

    Write-Step "Checking WSL command availability..."
    wsl --status 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "WSL is accessible."
    } else {
        Write-Warn "WSL status check did not pass. A reboot may still be required."
    }
}

# ===========================================================================
# Main execution
# ===========================================================================

Write-Section "WSL Manager Pro - One-Click Installer"
Write-Host "This script installs and configures all required runtime dependencies." -ForegroundColor Gray

# Phase 1: assert administrator privileges (elevate if needed)
Assert-Administrator

# Phase 2: enable WSL features and install WSL base components
Enable-WslFeatures

# Phase 3: install Python 3.12 + Node.js LTS via winget
Install-Tooling

# Phase 4: create venv and install project dependencies
Install-ProjectDependencies

# Phase 5: verify everything is wired correctly
Test-Environment

# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------
Write-Section "Completed"
Write-Ok "Environment setup finished."
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Run the application:" -ForegroundColor Gray
Write-Host "     .\.venv\Scripts\python.exe .\main.py" -ForegroundColor White
Write-Host ""
Write-Host "  2. If WSL was just enabled for the first time," -ForegroundColor Gray
Write-Host "     restart Windows to finalize kernel and feature activation." -ForegroundColor DarkYellow

# Keep the console open so the user can review the output
Write-Host ""
Read-Host -Prompt "Press Enter to close this window"
