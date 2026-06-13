# Desinstala AttendanceBridge POR COMPLETO.
# Detiene el proceso y elimina AMBOS autostart: el de usuario (acceso directo en
# la carpeta Inicio) y el de sistema (Tarea Programada). Tras esto, NO vuelve a
# arrancar nunca mas (ni al iniciar sesion ni al encender el PC).
# Solo eleva a Administrador si realmente existe una tarea de sistema que quitar.
$ErrorActionPreference = "SilentlyContinue"
Write-Host "=== Desinstalando AttendanceBridge ===" -ForegroundColor Cyan

function Stop-Capture {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
      Where-Object { $_.CommandLine -like "*capture_service.py*" } |
      ForEach-Object { Write-Host "Deteniendo proceso PID $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force }
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# --- 1) Matar el proceso que corre ahora ---
Stop-Capture

# --- 2) Quitar autostart de USUARIO (acceso directo en carpeta Inicio) ---
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) "AttendanceBridge.lnk"
if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "Autostart de USUARIO eliminado." -ForegroundColor Green }
else { Write-Host "Autostart de usuario: no existia." }

# --- 3) Quitar autostart de SISTEMA (Tarea Programada) ---
$task = Get-ScheduledTask -TaskName "AttendanceBridge-Capture" -ErrorAction SilentlyContinue
if ($task) {
    if (-not $isAdmin) {
        Write-Host "Hay una tarea de sistema. Pidiendo Administrador para eliminarla..." -ForegroundColor Yellow
        Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        Write-Host "Continua en la ventana de Administrador que se abrio."
        return
    }
    Stop-ScheduledTask  -TaskName "AttendanceBridge-Capture" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "AttendanceBridge-Capture" -Confirm:$false
    Unregister-ScheduledTask -TaskName "AttendanceBridge-Export"  -Confirm:$false  # por si quedo de versiones viejas
    Stop-Capture  # por si la lanzo la cuenta SYSTEM
    Write-Host "Autostart de SISTEMA (tarea) eliminado." -ForegroundColor Green
}
else {
    Write-Host "Autostart de sistema (tarea): no existia."
}

Write-Host ""
Write-Host "LISTO. AttendanceBridge NO volvera a arrancar (ni al iniciar sesion ni al encender el PC)." -ForegroundColor Cyan
Write-Host "Los archivos siguen en la carpeta. Para borrarlos del todo: elimina la carpeta del proyecto."
