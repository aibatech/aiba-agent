@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo AIBA is not installed. Run Install-AIBA-Windows.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" aiba_launcher.py --serve
pause
