@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1 && py -3 -m pip install -r requirements.txt && py -3 main.py && goto :eof
where python >nul 2>&1 && python -m pip install -r requirements.txt && python main.py && goto :eof
echo Python not found.
pause
