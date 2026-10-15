@echo off
cd /d "%~dp0"
set "PYTHON=python"
if exist "..\.venv\Scripts\python.exe" set "PYTHON=..\.venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"
if not exist "runtime\accounts.json" "%PYTHON%" app.py --init-users
"%PYTHON%" app.py
pause
