@echo off
rem Double-click this file to set up the video editor on Windows (it runs setup.ps1).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
