@echo off
rem Starts YT Downloader. Runs setup first if it hasn't been run yet.
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    call "%~dp0setup.bat"
    exit /b
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0run.pyw"
