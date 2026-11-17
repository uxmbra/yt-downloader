@echo off
rem Double-click to install everything YT Downloader needs (first time only).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo Setup failed. See the message above.
)
pause
