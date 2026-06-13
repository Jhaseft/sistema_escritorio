$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "=================== AttendanceBridge - ESTADO ===================" -ForegroundColor Cyan

# 1) Proceso corriendo? (puede correr como tu usuario o como SYSTEM)
$proc = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*capture_service.py*" }
if ($proc) {
    Write-Host ("PROCESO: CORRIENDO  (PID {0})" -f ($proc.ProcessId -join ', ')) -ForegroundColor Green
} else {
    Write-Host "PROCESO: no detectado (si corre como SYSTEM puede no verse sin admin; mira el log)" -ForegroundColor Yellow
}

# 2) Autostart de SISTEMA (tarea programada)
$task = Get-ScheduledTask -TaskName "AttendanceBridge-Capture" -ErrorAction SilentlyContinue
if ($task) { Write-Host ("AUTOSTART SISTEMA (tarea): SI  (Estado: {0})  -> arranca al encender el PC" -f $task.State) -ForegroundColor Green }
else { Write-Host "AUTOSTART SISTEMA (tarea): no" }

# 3) Autostart de USUARIO (acceso directo en carpeta Inicio)
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) "AttendanceBridge.lnk"
if (Test-Path $lnk) { Write-Host "AUTOSTART USUARIO (.lnk): SI  -> arranca al iniciar sesion" -ForegroundColor Green }
else { Write-Host "AUTOSTART USUARIO (.lnk): no" }

if (-not $task -and -not (Test-Path $lnk)) {
    Write-Host "  -> No hay autostart configurado. Ejecuta install.bat para instalarlo." -ForegroundColor Yellow
}

# 4) Resumen de la base
Write-Host "`n--- Fichajes guardados ---" -ForegroundColor Cyan
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($py) { & $py (Join-Path $Root "db_summary.py") }

# 5) Log de captura
Write-Host "`n--- Ultimas lineas del log ---" -ForegroundColor Cyan
Get-Content (Join-Path $Root "logs\capture.log") -Tail 10 -ErrorAction SilentlyContinue

Write-Host "`n================================================================" -ForegroundColor Cyan
