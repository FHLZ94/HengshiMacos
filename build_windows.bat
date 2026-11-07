@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PYTHON%" exit /b 1
"%PYTHON%" build_windows.py
exit /b %errorlevel%
