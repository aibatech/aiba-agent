@echo off
cd /d "%~dp0"
python installers\docker_wizard.py
if errorlevel 1 pause
