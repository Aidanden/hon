@echo off
chcp 65001 >nul
cd /d "%~dp0"

net session >nul 2>&1
if %errorLevel% neq 0 (
  echo Requesting Administrator...
  powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

where py >nul 2>&1
if %errorLevel%==0 (
  py -3 -m pip install -r requirements.txt
  py -3 main.py
  goto :eof
)

where python >nul 2>&1
if %errorLevel%==0 (
  python -m pip install -r requirements.txt
  python main.py
  goto :eof
)

echo Python not found. Install Python 3.10+ from https://www.python.org/downloads/
echo Make sure "Add python.exe to PATH" is checked.
pause
