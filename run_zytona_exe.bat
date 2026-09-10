@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "%~dp0dist\ZYTONA_APP.exe" (
  powershell -Command "Start-Process -FilePath '%~dp0dist\ZYTONA_APP.exe' -Verb RunAs"
  exit /b
)

echo EXE not found. Build it first with build_windows.bat
pause
