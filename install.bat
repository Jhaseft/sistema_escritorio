@echo off
REM Instala AttendanceBridge como tarea de SISTEMA (arranca con o sin login).
REM install.ps1 pide Administrador automaticamente y muestra el resultado.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
