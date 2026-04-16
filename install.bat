@echo off
:: ============================================================
::  VeniceBeach Auto-Booker – Windows Installer
::  Einfach doppelklicken oder als Administrator ausfuehren.
:: ============================================================

:: Deinstallations-Option: install.bat /uninstall
if /i "%1"=="/uninstall" goto :uninstall

:: PowerShell-Skript mit umgangenem ExecutionPolicy aufrufen
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
goto :eof

:uninstall
echo.
echo  Deinstalliere VeniceBeach Auto-Booker...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Stop-ScheduledTask  'VeniceBeach-AutoBooker' -ErrorAction SilentlyContinue; ^
   Unregister-ScheduledTask 'VeniceBeach-AutoBooker' -Confirm:$false -ErrorAction SilentlyContinue; ^
   Stop-Process -Name pythonw -Force -ErrorAction SilentlyContinue; ^
   Write-Host '  Deinstallation abgeschlossen.' -ForegroundColor Green"
echo.
pause
