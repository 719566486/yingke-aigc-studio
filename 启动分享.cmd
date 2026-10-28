@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0share_start.ps1"
if errorlevel 1 pause
