@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ZYTONA APP — Build Windows EXE

echo ========================================
echo   ZYTONA APP  -  Build .exe (Windows)
echo ========================================
echo.

where py >nul 2>&1
if %errorLevel%==0 (
  set PY=py -3
) else (
  where python >nul 2>&1
  if %errorLevel%==0 (
    set PY=python
  ) else (
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    echo Enable "Add python.exe to PATH".
    pause
    exit /b 1
  )
)

echo [1/3] Installing build dependencies...
%PY% -m pip install -U pip
%PY% -m pip install -r requirements.txt
%PY% -m pip install -r requirements-build.txt
if errorlevel 1 (
  echo ERROR: pip install failed.
  pause
  exit /b 1
)

echo.
echo [2/3] Cleaning old build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [3/3] Building ZYTONA_APP.exe ...
%PY% -m PyInstaller --noconfirm --clean zytona_app.spec
if errorlevel 1 (
  echo.
  echo BUILD FAILED.
  pause
  exit /b 1
)

echo.
echo ========================================
echo   DONE
echo   EXE:  %cd%\dist\ZYTONA_APP.exe
echo ========================================
echo.
echo Right-click the EXE -^> Run as administrator
echo (UAC prompt should also ask for Admin automatically).
echo.
explorer "%cd%\dist"
pause
