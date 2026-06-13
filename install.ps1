# Instalador de AttendanceBridge -- metodo SISTEMA (tarea programada como SYSTEM).
# Arranca al ENCENDER el PC (con o sin login) y se reinicia solo si se cae.
#
# - Se auto-eleva a Administrador. La ventana elevada queda ABIERTA (-NoExit) para
#   que puedas LEER cualquier error; cierrala tu cuando termines de leer.
# - Guarda TODO lo que ocurre en logs\install.log (transcript completo).
#   -NoPause : no espera Enter al final (solo para uso automatizado)
param([switch]$NoPause)

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Se necesitan permisos de Administrador. Abriendo ventana elevada..." -ForegroundColor Yellow
    # -NoExit: la ventana elevada NO se cierra al terminar/fallar -> puedes leer el error.
    Start-Process powershell -Verb RunAs -ArgumentList "-NoExit -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    return
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logFile = Join-Path $Root "logs\install.log"
New-Item -ItemType Directory -Force -Path (Split-Path $logFile) -ErrorAction SilentlyContinue | Out-Null
Start-Transcript -Path $logFile -Append -ErrorAction SilentlyContinue | Out-Null

$ErrorActionPreference = "Stop"
try {
    Write-Host ("=== Instalando AttendanceBridge (metodo sistema) [{0}] ===" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor Cyan

    # 1) Localizar pythonw.exe
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { throw "Python no esta en el PATH. Instala Python 3 (64-bit) y marca 'Add to PATH'." }
    $pythonw = Join-Path (Split-Path $py) "pythonw.exe"
    if (-not (Test-Path $pythonw)) { throw "No se encontro pythonw.exe junto a: $py" }
    Write-Host "pythonw: $pythonw"

    # 2) (Sin dependencias externas: el capturador usa solo la libreria estandar)

    # 3) Detener instancias previas (evitar duplicados; el equipo limita conexiones)
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
      Where-Object { $_.CommandLine -like "*capture_service.py*" } |
      ForEach-Object { Write-Host "Deteniendo instancia previa PID $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    # 4) Registrar la tarea: SYSTEM, al arranque, auto-reinicio ante fallos
    $capture = Join-Path $Root "capture_service.py"
    if (-not (Test-Path $capture)) { throw "No se encontro capture_service.py en $Root" }
    $actC = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$capture`"" -WorkingDirectory $Root
    $trgC = New-ScheduledTaskTrigger -AtStartup
    $setC = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
    $prn  = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName "AttendanceBridge-Capture" -Action $actC -Trigger $trgC `
            -Settings $setC -Principal $prn -Force | Out-Null
    Write-Host "Tarea 'AttendanceBridge-Capture' registrada (SYSTEM, al arranque)." -ForegroundColor Green

    # 5) Arrancar y VERIFICAR (proceso + que la tarea no la borre el antivirus)
    Write-Host "Arrancando y verificando (hasta 12s)..."
    Start-ScheduledTask -TaskName "AttendanceBridge-Capture"
    $proc = $null
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 1
        $proc = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
                Where-Object { $_.CommandLine -like "*capture_service.py*" }
        if ($proc) { break }
    }
    Start-Sleep -Seconds 2  # dar tiempo a que el antivirus reaccione (suele borrar la tarea aqui)
    $task  = Get-ScheduledTask -TaskName "AttendanceBridge-Capture" -ErrorAction SilentlyContinue
    $state = if ($task) { $task.State } else { "BORRADA" }

    Write-Host ""
    if (-not $task) {
        Write-Host "PROBLEMA -> la tarea fue BORRADA segundos despues de crearse." -ForegroundColor Red
        Write-Host "CAUSA: un ANTIVIRUS (360 Total Security) elimina la tarea de autoarranque." -ForegroundColor Red
        Write-Host "  Solucion: en 360 -> Defensa Activa / Registro de proteccion, PERMITE/CONFIA" -ForegroundColor Yellow
        Write-Host "  la creacion de la tarea (busca 'AttendanceBridge' o 'tarea programada' y dale Confiar)." -ForegroundColor Yellow
    }
    elseif ($proc) {
        Write-Host ("EXITO -> capturador corriendo como SYSTEM (PID {0}). Tarea: {1}." -f ($proc.ProcessId -join ', '), $state) -ForegroundColor Green
        Write-Host "Arranca al ENCENDER el PC (con o sin login) y se reinicia si se cae." -ForegroundColor Green
    }
    else {
        Write-Host ("ADVERTENCIA -> la tarea existe (Estado: {0}) pero el proceso no arranco." -f $state) -ForegroundColor Yellow
        Write-Host "Revisa logs\capture.log y la lista blanca del antivirus." -ForegroundColor Yellow
    }
    Write-Host "Logs en: $Root\logs\  (registro completo en install.log)"
}
catch {
    Write-Host ""
    Write-Host ("ERROR durante la instalacion: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host $_.ScriptStackTrace
}
finally {
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
    if (-not $NoPause) {
        Write-Host ""
        Read-Host "Presiona Enter para cerrar (o cierra la ventana cuando termines de leer)" | Out-Null
    }
}
