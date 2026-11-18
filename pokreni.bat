@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "STUDIO_APP_DIR=%~dp0"
if "%STUDIO_APP_DIR:~-1%"=="\" set "STUDIO_APP_DIR=%STUDIO_APP_DIR:~0,-1%"
if exist "%STUDIO_APP_DIR%\..\data" set "STUDIO_DATA_DIR=%STUDIO_APP_DIR%\..\data"

set "PYW=C:\ComfyUI-Zluda\venv\Scripts\pythonw.exe"
set "PY=C:\ComfyUI-Zluda\venv\Scripts\python.exe"

if exist "%PYW%" (
  start "" "%PYW%" "%STUDIO_APP_DIR%\launcher.py"
  exit /b 0
)
if exist "%PY%" (
  start "" "%PY%" "%STUDIO_APP_DIR%\launcher.py"
  exit /b 0
)

where py >nul 2>&1
if not errorlevel 1 (
  start "" py -3.11 "%STUDIO_APP_DIR%\launcher.py"
  exit /b 0
)

where pythonw >nul 2>&1
if not errorlevel 1 (
  start "" pythonw "%STUDIO_APP_DIR%\launcher.py"
  exit /b 0
)

where python >nul 2>&1
if not errorlevel 1 (
  start "" python "%STUDIO_APP_DIR%\launcher.py"
  exit /b 0
)

echo GRESKA: nisam nasao Python.
echo Ocekujem C:\ComfyUI-Zluda\venv\Scripts\pythonw.exe ili py -3.11
pause
exit /b 1
