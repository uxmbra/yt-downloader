@echo off
rem Builds dist\YT Downloader\YT Downloader.exe (portable, no Python needed).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"
pause
