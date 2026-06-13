@echo off
REM Desinstala AttendanceBridge POR COMPLETO (usuario + sistema).
REM Tras esto no vuelve a arrancar ni al iniciar sesion ni al encender el PC.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
echo.
pause
