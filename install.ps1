#Requires -Version 5.1
<#
.SYNOPSIS
    WSL Manager Pro - One-command installer and launcher for Windows.

.DESCRIPTION
    Validates the Python runtime (requires >=3.14),
    creates an isolated virtual environment, installs all dependencies,
    and launches the application.

.EXAMPLE
    # Run from PowerShell:
    .\install.ps1

    # Or directly from GitHub:
    irm https://raw.githubusercontent.com/wilkinbarban/WSL-Manager-Pro/master/install.ps1 | iex

.NOTES
    Platform : Windows 10/11
    Author   : wilkinbarban
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Version = "1.0.1"

# 1. Host settings
$Host.UI.RawUI.WindowTitle = "WSL Manager Pro - Instalando..."
Clear-Host

Write-Host ""
Write-Host "  *** W S L   M A N A G E R   P R O ***" -ForegroundColor Magenta
Write-Host "  ========================================" -ForegroundColor DarkCyan
Write-Host "   Instalador y Lanzador - Version $Version" -ForegroundColor Gray
Write-Host "  ========================================" -ForegroundColor DarkCyan
Write-Host ""

# Status indicator helper
function Show-Step {
    param (
        [string]$Message
    )
    Write-Host "  >> $Message..." -ForegroundColor Gray
}

# Error presentation helper
function Show-Error {
    param (
        [string]$Title,
        [string]$Detail,
        [string]$Action
    )
    Write-Host ""
    Write-Host "  [ERROR] $Title" -ForegroundColor Red
    Write-Host "  --------------------------------------------------------" -ForegroundColor Red
    Write-Host "   Detalle : $Detail" -ForegroundColor Yellow
    Write-Host "   Accion  : $Action" -ForegroundColor Cyan
    Write-Host "  --------------------------------------------------------" -ForegroundColor Red
    Write-Host ""
    Read-Host "  Presione Enter para salir..."
    exit 1
}

# Lightweight execution runner with progress spinner and real-time package feedback
function Run-WithProgress {
    param (
        [string]$FileName,
        [string]$Arguments,
        [string]$Message
    )
    $pinfo = New-Object System.Diagnostics.ProcessStartInfo
    $pinfo.FileName = $FileName
    $pinfo.Arguments = $Arguments
    $pinfo.RedirectStandardOutput = $true
    $pinfo.RedirectStandardError = $true
    $pinfo.UseShellExecute = $false
    $pinfo.CreateNoWindow = $true
    
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $pinfo
    
    $stdoutList = New-Object System.Collections.Generic.List[string]
    $stderrList = New-Object System.Collections.Generic.List[string]
    
    # Register events for non-blocking stream capture
    $p.EnableRaisingEvents = $true
    
    $outEvent = Register-ObjectEvent -InputObject $p -EventName "OutputDataReceived" -Action {
        if ($EventArgs.Data) {
            $Event.MessageData.Add($EventArgs.Data)
            $script:LastRawLine = $EventArgs.Data
        }
    } -MessageData $stdoutList
    
    $errEvent = Register-ObjectEvent -InputObject $p -EventName "ErrorDataReceived" -Action {
        if ($EventArgs.Data) {
            $Event.MessageData.Add($EventArgs.Data)
        }
    } -MessageData $stderrList
    
    try {
        $script:LastRawLine = ""
        $p.Start() | Out-Null
        $p.BeginOutputReadLine()
        $p.BeginErrorReadLine()
    } catch {
        return [PSCustomObject]@{ Success = $false; Stdout = ""; Stderr = $_.Exception.Message; ExitCode = -1; Error = $_.Exception.Message }
    }
    
    $spinner = @('|', '/', '-', '\')
    $i = 0
    while (-not $p.HasExited) {
        $displayMessage = $Message
        $lastLine = $script:LastRawLine
        if ($lastLine) {
            if ($lastLine -match 'Downloading\s+([a-zA-Z0-9_\-\.]+)') {
                $displayMessage = "Descargando $($Matches[1])"
            } elseif ($lastLine -match 'Installing collected packages:\s*(.*)') {
                $displayMessage = "Instalando paquetes"
            } elseif ($lastLine -match 'Requirement already satisfied:\s*([a-zA-Z0-9_\-\.\:\(\)\ ]+)') {
                $matched = $Matches[1]
                if ($matched -match '^([a-zA-Z0-9_\-]+)') {
                    $displayMessage = "Verificando $($Matches[1])"
                }
            }
        }
        
        # Limit message length to fit beautifully in standard terminal
        if ($displayMessage.Length -gt 50) {
            $displayMessage = $displayMessage.Substring(0, 47) + "..."
        }
        
        Write-Host -NoNewline "`r  $($spinner[$i]) $displayMessage..." -ForegroundColor Cyan
        Start-Sleep -Milliseconds 100
        $i = ($i + 1) % $spinner.Count
    }
    
    Unregister-Event -SourceIdentifier $outEvent.Name -ErrorAction SilentlyContinue
    Unregister-Event -SourceIdentifier $errEvent.Name -ErrorAction SilentlyContinue
    
    $stdout = $stdoutList -join "`n"
    $stderr = $stderrList -join "`n"
    $exitCode = $p.ExitCode
    
    Write-Host -NoNewline "`r                                                                              `r"
    
    if ($exitCode -eq 0) {
        Write-Host "  [OK] $Message [Completado]" -ForegroundColor Green
        return [PSCustomObject]@{ Success = $true; Stdout = $stdout; Stderr = ""; ExitCode = 0; Error = "" }
    } else {
        Write-Host "  [FAIL] $Message [Fallo]" -ForegroundColor Red
        return [PSCustomObject]@{ Success = $false; Stdout = $stdout; Stderr = $stderr; ExitCode = $exitCode; Error = "" }
    }
}

# Resolve a safe base path for all file operations
$ScriptRootCandidates = @(
    $PSScriptRoot,
    $(if (-not [string]::IsNullOrWhiteSpace($PSCommandPath)) { Split-Path -Parent $PSCommandPath }),
    (Get-Location).Path,
    '.'
)

$ScriptRoot = $null
foreach ($candidate in $ScriptRootCandidates) {
    if (-not [string]::IsNullOrWhiteSpace($candidate)) {
        $ScriptRoot = $candidate.Trim()
        break
    }
}

if ([string]::IsNullOrWhiteSpace($ScriptRoot)) {
    Show-Error "Error de Directorio" "No se pudo determinar el directorio de trabajo." "Ejecute el instalador desde un directorio con permisos de lectura y escritura."
}

# --- Step A: Bootstrap mode verification ---
$RequiredFiles = @('main.py', 'requirements.txt')
$IsProjectRoot = $true
foreach ($file in $RequiredFiles) {
    if (-not (Test-Path (Join-Path $ScriptRoot $file))) {
        $IsProjectRoot = $false
        break
    }
}

if (-not $IsProjectRoot) {
    Write-Host "  [!] Archivos de proyecto no encontrados en el directorio actual." -ForegroundColor Yellow
    Write-Host "  [INFO] Entrando a modo Bootstrapper remoto: descargando repositorio..." -ForegroundColor Cyan
    
    $RepoOwner   = 'wilkinbarban'
    $RepoName    = 'WSL-Manager-Pro'
    $Branch      = 'master'
    $ArchiveUrl  = "https://github.com/$RepoOwner/$RepoName/archive/refs/heads/$Branch.zip"
    $DesktopDir  = [Environment]::GetFolderPath('Desktop')
    if ([string]::IsNullOrWhiteSpace($DesktopDir)) {
        $DesktopDir = Join-Path $HOME 'Desktop'
    }
    $InstallDir  = if ($env:WMP_INSTALL_DIR) { $env:WMP_INSTALL_DIR } else { Join-Path $DesktopDir $RepoName }
    $TempZip     = Join-Path $env:TEMP "$RepoName-$Branch.zip"
    $TempExtract = Join-Path $env:TEMP "$RepoName-bootstrap-$(Get-Random)"

    # Download Repository Zip
    $dlArgs = "-NoProfile -Command `"Invoke-WebRequest -Uri '$ArchiveUrl' -OutFile '$TempZip' -UseBasicParsing`""
    $dlRes = Run-WithProgress "powershell" $dlArgs "Descargando repositorio de GitHub"
    if (-not $dlRes.Success) {
        Show-Error "Fallo de Descarga" "No se pudo descargar el repositorio desde GitHub." "Verifique su conexion a Internet y que github.com sea accesible."
    }

    # Verify Zip Size
    $zipSize = (Get-Item $TempZip).Length
    if ($zipSize -lt 1024) {
        Remove-Item -Force $TempZip -ErrorAction SilentlyContinue
        Show-Error "Integridad Invalida" "El archivo descargado es invalido o corrupto." "Vuelva a intentar la ejecucion."
    }

    # Extract Zip File
    $null = New-Item -ItemType Directory -Path $TempExtract -Force
    $extArgs = "-NoProfile -Command `"Expand-Archive -Path '$TempZip' -DestinationPath '$TempExtract' -Force`""
    $extRes = Run-WithProgress "powershell" $extArgs "Extrayendo repositorio del instalador"
    Remove-Item -Force $TempZip -ErrorAction SilentlyContinue
    
    if (-not $extRes.Success) {
        Remove-Item -Recurse -Force $TempExtract -ErrorAction SilentlyContinue
        Show-Error "Extraccion Fallida" "No se pudo descomprimir el archivo del repositorio." "Asegurese de contar con espacio en disco."
    }

    $ExtractedRoot = Join-Path $TempExtract "$RepoName-$Branch"
    if (-not (Test-Path $ExtractedRoot)) {
        Remove-Item -Recurse -Force $TempExtract -ErrorAction SilentlyContinue
        Show-Error "Estructura Invalida" "La carpeta esperada tras la extraccion no existe." "Vuelva a intentar la ejecucion."
    }

    # Move files to final directory
    Show-Step "Instalando archivos del repositorio"
    if (Test-Path $InstallDir) {
        Write-Host "  [!] Carpeta destino existente. Actualizando archivos en-lugar..." -ForegroundColor Yellow
        Get-ChildItem -Path $ExtractedRoot | Where-Object { $_.Name -ne '.venv' } | ForEach-Object {
            $dest = Join-Path $InstallDir $_.Name
            Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
        }
    } else {
        Move-Item -Path $ExtractedRoot -Destination $InstallDir
    }
    Remove-Item -Recurse -Force $TempExtract -ErrorAction SilentlyContinue

    $LocalInstaller = Join-Path $InstallDir 'install.ps1'
    if (-not (Test-Path $LocalInstaller)) {
        Show-Error "Script Faltante" "El script install.ps1 no se encontro en el directorio instalado." "Reporte este error al autor del proyecto."
    }

    Write-Host "  [OK] Repositorio instalado con exito." -ForegroundColor Green
    Write-Host "  [INFO] Delegando arranque al instalador local..." -ForegroundColor Cyan
    Set-Location $InstallDir
    & $LocalInstaller
    exit $LASTEXITCODE
}

# --- Step 0: Check WSL Environment ---
Show-Step "Verificando entorno de Windows Subsystem for Linux (WSL)"

$wslInstalled = $false
$wslPath = Join-Path $env:SystemRoot "System32\wsl.exe"
if (-not (Test-Path $wslPath)) {
    $wslPath = Join-Path $env:SystemRoot "SysNative\wsl.exe"
}
if (Test-Path $wslPath) {
    $wslInstalled = $true
} else {
    if (Get-Command "wsl.exe" -ErrorAction SilentlyContinue) {
        $wslInstalled = $true
    }
}

if (-not $wslInstalled) {
    # Check compatibility
    $build = [Environment]::OSVersion.Version.Build
    if ($build -lt 19041) {
        Show-Error "WSL no Soportado" "Su version de Windows (Build $build) es demasiado antigua." "WSL 2 requiere Windows 10 Build 19041 o superior. Por favor, actualice Windows."
    }

    $virtEnabled = $true
    try {
        $processors = Get-CimInstance -ClassName Win32_Processor -ErrorAction SilentlyContinue
        if ($processors) {
            foreach ($p in $processors) {
                if ($p.VirtualizationFirmwareEnabled -eq $false) {
                    $virtEnabled = $false
                    break
                }
            }
        }
    } catch {}

    if (-not $virtEnabled) {
        Show-Error "Virtualizacion Desactivada" "La virtualizacion asistida por hardware (VT-x/AMD-V) esta desactivada en la BIOS." "Active la virtualizacion en la configuracion de firmware de su placa base (BIOS/UEFI) antes de continuar."
    }

    Write-Host "  [!] Windows Subsystem for Linux (WSL) no esta instalado en este sistema." -ForegroundColor Yellow
    $choice = Read-Host "  ¿Desea instalar WSL de forma automatica ahora? (Requiere elevacion y reinicio) [S/N]"
    if ($choice -match '^[sSyY]$') {
        # Check if running as Admin
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

        if (-not $isAdmin) {
            Write-Host "  [INFO] Solicitando elevacion de privilegios de Administrador..." -ForegroundColor Cyan
            $ScriptPath = $MyInvocation.MyCommand.Path
            if ([string]::IsNullOrWhiteSpace($ScriptPath) -and -not [string]::IsNullOrWhiteSpace($PSCommandPath)) {
                $ScriptPath = $PSCommandPath
            }
            if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
                Show-Error "Error de Elevacion" "No se pudo determinar la ruta del script para la elevacion." "Ejecute PowerShell como Administrador e intente nuevamente."
            }
            $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
            try {
                Start-Process powershell -ArgumentList $argList -Verb RunAs -Wait
            } catch {
                Show-Error "Acceso Denegado" "La solicitud de elevacion fue cancelada o rechazada." "Debe ejecutar el script como Administrador para poder instalar WSL."
            }
            # After returning from elevation check if WSL is now available
            if (-not (Test-Path $wslPath) -and -not (Get-Command "wsl.exe" -ErrorAction SilentlyContinue)) {
                Write-Host "  [INFO] La instalacion requiere reiniciar el sistema para completarse." -ForegroundColor Yellow
                exit 0
            }
        } else {
            # We are admin, execute wsl --install
            Write-Host "  [INFO] Iniciando instalacion de WSL..." -ForegroundColor Cyan
            # wsl.exe might not be present yet in path, run dism or wsl.exe --install
            # WSL 2 is installed using `wsl --install --no-distribution` or calling powershell command
            $installRes = Run-WithProgress "powershell.exe" "-NoProfile -Command `"wsl --install --no-distribution`"" "Instalando WSL y activando caracteristicas"
            if ($installRes.Success) {
                Write-Host ""
                Write-Host "  [OK] WSL instalado con exito." -ForegroundColor Green
                $reboot = Read-Host "  Es necesario reiniciar el sistema para completar la instalacion. ¿Desea reiniciar ahora? [S/N]"
                if ($reboot -match '^[sSyY]$') {
                    Write-Host "  [INFO] Reiniciando el sistema en 5 segundos..." -ForegroundColor Yellow
                    Start-Sleep -Seconds 5
                    Restart-Computer -Force
                    exit 0
                } else {
                    Write-Host "  [WARNING] Por favor, reinicie su computadora manualmente antes de volver a ejecutar el programa." -ForegroundColor Yellow
                    exit 0
                }
            } else {
                $errText = if ($installRes.Stderr) { $installRes.Stderr } else { $installRes.Error }
                Show-Error "Error de Instalacion" "No se pudo instalar WSL automaticamente. Codigo de salida: $($installRes.ExitCode)" "Detalle: $errText`nIntente ejecutar manualmente en una consola de Administrador: wsl --install --no-distribution"
            }
        }
    } else {
        Show-Error "WSL Requerido" "No se puede continuar sin WSL instalado en el sistema." "Instale WSL manualmente ejecutando 'wsl --install' y vuelva a intentarlo."
    }
}

# --- Step 1: Detect Python Environment ---
Show-Step "Verificando entorno de Python"

$pythonCmd = $null
$launchers = @("py -3.14", "py -3.15", "py -3.16", "py -3.13")
foreach ($launcher in $launchers) {
    try {
        $parts = $launcher -split " "
        $cmdName = $parts[0]
        $cmd = try { (Get-Command $cmdName).Source } catch { $cmdName }
        $arg = $parts[1]
        $res = & $cmd $arg --version 2>&1
        if ($lastExitCode -eq 0 -and $res -match 'Python\s+([0-9\.]+)') {
            $ver = [version]$Matches[1]
            if ($ver -ge [version]"3.14") {
                $pythonCmd = $launcher
                break
            }
        }
    } catch {}
}

if (-not $pythonCmd) {
    try {
        $res = & python --version 2>&1
        if ($lastExitCode -eq 0 -and $res -match 'Python\s+([0-9\.]+)') {
            $ver = [version]$Matches[1]
            if ($ver -ge [version]"3.14") {
                $pythonCmd = "python"
            }
        }
    } catch {}
}

# Install Python 3.14 automatically if missing
if (-not $pythonCmd) {
    Write-Host "  [!] Python compatible (3.14 o superior) no detectado en el sistema." -ForegroundColor Yellow
    
    $wingetCheck = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $wingetCheck) {
        Show-Error "Python No Encontrado" "No se encontro Python ni el instalador winget en el sistema." "Instale manualmente Python 3.14 desde https://www.python.org/downloads/ (marcando 'Add Python to PATH')."
    }
    
    $installRes = Run-WithProgress "winget" "install --id Python.Python.3.14 --accept-source-agreements --accept-package-agreements" "Instalando Python 3.14"
    if (-not $installRes.Success) {
        Show-Error "Instalacion de Python Fallida" "Fallo al instalar Python 3.14 mediante winget." "Por favor, realice la instalacion manual desde el sitio web de Python."
    }
    
    # Reload environment path for the current process
    $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('PATH', 'User')
    
    foreach ($launcher in $launchers) {
        try {
            $parts = $launcher -split " "
            $cmdName = $parts[0]
            $cmd = try { (Get-Command $cmdName).Source } catch { $cmdName }
            $arg = $parts[1]
            $res = & $cmd $arg --version 2>&1
            if ($lastExitCode -eq 0 -and $res -match 'Python\s+([0-9\.]+)') {
                $ver = [version]$Matches[1]
                if ($ver -ge [version]"3.14") {
                    $pythonCmd = $launcher
                    break
                }
            }
        } catch {}
    }
    
    if (-not $pythonCmd) {
        Show-Error "Reinicio de Consola Requerido" "Python fue instalado correctamente pero la terminal actual aun no reconoce el comando." "Cierre todas las ventanas de consola abiertas y vuelva a ejecutar install.ps1."
    }
}

Write-Host "  [OK] Python base detectado ($pythonCmd)" -ForegroundColor Green

# --- Step 2: Virtual Environment Setup ---
$venvDir = Join-Path $ScriptRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$venvPip = Join-Path $venvDir 'Scripts\pip.exe'
$recreateVenv = $false

if (Test-Path $venvPython) {
    try {
        $res = & $venvPython --version 2>&1
        if ($res -match 'Python\s+([0-9\.]+)') {
            $ver = [version]$Matches[1]
            if ($ver -lt [version]"3.14") {
                $recreateVenv = $true
            }
        } else {
            $recreateVenv = $true
        }
    } catch {
        $recreateVenv = $true
    }
}

if ($recreateVenv) {
    Write-Host "  [!] Entorno virtual incompatible detectado. Recreando .venv..." -ForegroundColor Yellow
    Remove-Item -Path $venvDir -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path $venvPython)) {
    $parts = $pythonCmd -split " "
    $cmdName = $parts[0]
    $cmd = try { (Get-Command $cmdName).Source } catch { $cmdName }
    $venvArgs = if ($parts.Length -gt 1) { "$($parts[1]) -m venv `"$venvDir`"" } else { "-m venv `"$venvDir`"" }
    
    $venvRes = Run-WithProgress $cmd $venvArgs "Creando entorno virtual (.venv)"
    if (-not $venvRes.Success) {
        Show-Error "Error de Entorno Virtual" "No se pudo crear la carpeta .venv." "Verifique permisos de escritura en la carpeta del proyecto o intente ejecutar: python -m venv .venv"
    }
} else {
    Write-Host "  [OK] Entorno virtual detectado (.venv)" -ForegroundColor Green
}

# --- Step 3: Dependencies Check & Installation ---
Show-Step "Comprobando dependencias del sistema"

# Disable global pip installation to enforce isolated venv
$env:PIP_USER = "no"

# Upgrade pip quietly
$pipUpgrade = Run-WithProgress $venvPython "-m pip install --no-input --upgrade pip" "Actualizando instalador pip"

# Check dependencies from requirements.txt
$ReqPath = Join-Path $ScriptRoot "requirements.txt"
if (Test-Path $ReqPath) {
    $depsRes = Run-WithProgress $venvPip "install --no-input -r `"$ReqPath`"" "Instalando dependencias de Python"
    if (-not $depsRes.Success) {
        $logFile = Join-Path $venvDir "install.log"
        $errText = if ($depsRes.Stderr) { $depsRes.Stderr } else { $depsRes.Error }
        $errText | Out-File -FilePath $logFile -Encoding utf8
        Show-Error "Error en Dependencias" "Fallo al instalar paquetes de requirements.txt." "Consulte el archivo de log en: $logFile`nIntente ejecutar manualmente: .venv\Scripts\pip.exe install -r requirements.txt"
    }
} else {
    Write-Host "  [!] requirements.txt no encontrado. Omitiendo instalacion de dependencias." -ForegroundColor Yellow
}

# --- Step 4: Run Application ---
Write-Host "  >>> Iniciando WSL Manager Pro..." -ForegroundColor Magenta
Write-Host ""
$Host.UI.RawUI.WindowTitle = "WSL Manager Pro"

try {
    # Launch in background and wait, showing direct app output
    $proc = Start-Process -FilePath $venvPython -ArgumentList "main.py" -NoNewWindow -PassThru -Wait
    $exitCode = $proc.ExitCode
    if ($exitCode -ne 0) {
        Show-Error "Ejecucion Fallida" "La aplicacion finalizo con un codigo de error inesperado ($exitCode)." "Consulte la salida anterior o los archivos de log de la aplicacion para mas detalles."
    }
} catch {
    Show-Error "Fallo Critico al Iniciar" $_.Exception.Message "Compruebe que el entorno virtual no este danado e intente re-ejecutar el script."
}
