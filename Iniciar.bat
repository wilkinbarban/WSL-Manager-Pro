@powershell -NoProfile -ExecutionPolicy Bypass -Command "$ScriptRoot = '%~dp0'; Invoke-Expression ((Get-Content '%~f0' -Encoding utf8 | Select-Object -Skip 1) -join [Environment]::NewLine)" & exit /b
# WSL Manager Pro local launcher.
# This file intentionally embeds PowerShell after the first BAT line.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Version = "1.0.1"
$Host.UI.RawUI.WindowTitle = "WSL Manager Pro - Iniciando..."
Clear-Host

Write-Host ""
Write-Host "  *** W S L   M A N A G E R   P R O ***" -ForegroundColor Magenta
Write-Host "  ========================================" -ForegroundColor DarkCyan
Write-Host "   Lanzador Local - Version $Version" -ForegroundColor Gray
Write-Host "  ========================================" -ForegroundColor DarkCyan
Write-Host ""

function Show-Step {
    param([string]$Message)
    Write-Host "  >> $Message..." -ForegroundColor Gray
}

function Show-Error {
    param(
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

function Run-WithProgress {
    param(
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
    }
    catch {
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
            }
            elseif ($lastLine -match 'Installing collected packages:\s*(.*)') {
                $displayMessage = "Instalando paquetes"
            }
            elseif ($lastLine -match 'Requirement already satisfied:\s*([a-zA-Z0-9_\-\.\:\(\)\ ]+)') {
                $matched = $Matches[1]
                if ($matched -match '^([a-zA-Z0-9_\-]+)') {
                    $displayMessage = "Verificando $($Matches[1])"
                }
            }
        }

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
    }

    Write-Host "  [FAIL] $Message [Fallo]" -ForegroundColor Red
    return [PSCustomObject]@{ Success = $false; Stdout = $stdout; Stderr = $stderr; ExitCode = $exitCode; Error = "" }
}

function Test-Python314Command {
    param([string]$CommandLine)

    try {
        $parts = $CommandLine -split " "
        $cmdName = $parts[0]
        $cmd = try { (Get-Command $cmdName).Source } catch { $cmdName }
        $argList = @()
        if ($parts.Length -gt 1) {
            $argList = $parts[1..($parts.Length - 1)]
        }

        $res = & $cmd @argList --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $res -match 'Python\s+([0-9\.]+)') {
            $ver = [version]$Matches[1]
            return ($ver -ge [version]"3.14")
        }
    }
    catch { }

    return $false
}

function Get-Python314Command {
    $candidates = @("python", "py -3.14", "py -3.15", "py -3.16")
    foreach ($candidate in $candidates) {
        if (Test-Python314Command $candidate) {
            return $candidate
        }
    }

    return $null
}

if ([string]::IsNullOrWhiteSpace($ScriptRoot)) {
    Show-Error "Error de Directorio" "No se pudo determinar el directorio del lanzador." "Ejecute Iniciar.bat desde la carpeta del proyecto."
}

Set-Location $ScriptRoot
$ProjectRoot = (Get-Location).Path
$RequiredFiles = @('main.py', 'requirements.txt')
foreach ($file in $RequiredFiles) {
    if (-not (Test-Path (Join-Path $ProjectRoot $file))) {
        Show-Error "Proyecto Incompleto" "No se encontro $file en $ProjectRoot." "Descargue el proyecto completo o ejecute el instalador install.ps1."
    }
}

Show-Step "Verificando entorno de Python 3.14 o superior"
$pythonCmd = Get-Python314Command

if (-not $pythonCmd) {
    Write-Host "  [!] Python 3.14+ no detectado en el sistema." -ForegroundColor Yellow

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Show-Error "Python No Encontrado" "No se encontro Python 3.14+ ni winget." "Instale manualmente Python 3.14 desde https://www.python.org/downloads/ y agreguelo al PATH."
    }

    $installRes = Run-WithProgress "winget" "install --id Python.Python.3.14 --accept-source-agreements --accept-package-agreements" "Instalando Python 3.14"
    if (-not $installRes.Success) {
        Show-Error "Instalacion de Python Fallida" "Fallo al instalar Python 3.14 mediante winget." "Instale Python 3.14 manualmente desde el sitio web de Python."
    }

    $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('PATH', 'User')
    $pythonCmd = Get-Python314Command
    if (-not $pythonCmd) {
        Show-Error "Reinicio de Consola Requerido" "Python fue instalado, pero la terminal actual aun no reconoce el comando." "Cierre todas las consolas abiertas y vuelva a ejecutar Iniciar.bat."
    }
}

Write-Host "  [OK] Python base detectado ($pythonCmd)" -ForegroundColor Green

$venvDir = Join-Path $ProjectRoot '.venv'
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
        }
        else {
            $recreateVenv = $true
        }
    }
    catch {
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
        Show-Error "Error de Entorno Virtual" "No se pudo crear la carpeta .venv." "Verifique permisos de escritura o ejecute: python -m venv .venv"
    }
}
else {
    Write-Host "  [OK] Entorno virtual detectado (.venv)" -ForegroundColor Green
}

Show-Step "Comprobando dependencias del sistema"
$env:PIP_USER = "no"

$pipUpgrade = Run-WithProgress $venvPython "-m pip install --no-input --upgrade pip" "Actualizando instalador pip"
if (-not $pipUpgrade.Success) {
    Show-Error "Error de pip" "No se pudo actualizar pip dentro del entorno virtual." "Revise la conexion o ejecute manualmente: .venv\Scripts\python.exe -m pip install --upgrade pip"
}

$ReqPath = Join-Path $ProjectRoot "requirements.txt"
$depsRes = Run-WithProgress $venvPip "install --no-input -r `"$ReqPath`"" "Instalando dependencias de Python"
if (-not $depsRes.Success) {
    $logFile = Join-Path $venvDir "install.log"
    $errText = if ($depsRes.Stderr) { $depsRes.Stderr } else { $depsRes.Error }
    $errText | Out-File -FilePath $logFile -Encoding utf8
    Show-Error "Error en Dependencias" "Fallo al instalar paquetes de requirements.txt." "Consulte el log: $logFile`nIntente manualmente: .venv\Scripts\pip.exe install -r requirements.txt"
}

Write-Host ""
Write-Host "  >>> Iniciando WSL Manager Pro..." -ForegroundColor Magenta
Write-Host ""
$Host.UI.RawUI.WindowTitle = "WSL Manager Pro"

try {
    $proc = Start-Process -FilePath $venvPython -ArgumentList "main.py" -NoNewWindow -PassThru -Wait
    $exitCode = $proc.ExitCode
    if ($exitCode -ne 0) {
        Show-Error "Ejecucion Fallida" "La aplicacion finalizo con codigo de error ($exitCode)." "Consulte los mensajes anteriores o los logs de la aplicacion."
    }
}
catch {
    Show-Error "Fallo Critico al Iniciar" $_.Exception.Message "Compruebe que .venv no este danado y vuelva a ejecutar Iniciar.bat."
}
