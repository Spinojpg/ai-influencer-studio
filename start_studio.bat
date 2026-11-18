@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  AI Influencer Studio - Jednostavno
echo  Adresa: http://127.0.0.1:7860
echo ============================================
echo.
echo Ako se preglednik ne otvori sam, otvori tu adresu rucno.
echo ComfyUI mora vec slusati na http://127.0.0.1:8188
echo Ako nije pokrenut, prvo start_comfy.bat ili pokreni_sve.bat
echo.

set "PY="
if exist "C:\ComfyUI-Zluda\venv\Scripts\python.exe" (
    set "PY=C:\ComfyUI-Zluda\venv\Scripts\python.exe"
    echo Koristim Python iz C:\ComfyUI-Zluda\venv
)

if not defined PY (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3.11 -c "import sys" >nul 2>&1
        if not errorlevel 1 (
            set "PY=py -3.11"
            echo Koristim py -3.11
        )
    )
)

if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PY=python"
        echo Koristim python iz PATH-a
    )
)

if not defined PY (
    echo [GRESKA] Nisam nasao Python.
    echo Ocekujem C:\ComfyUI-Zluda\venv\Scripts\python.exe
    echo ili py -3.11
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0studio.py" (
    echo [GRESKA] Nema studio.py u ovoj mapi:
    echo   %~dp0
    echo.
    pause
    exit /b 1
)

echo Pokrecem studio.py ...
echo.
%PY% "%~dp0studio.py"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo Studio je zavrsio sa kodom %RC%.
    pause
)
endlocal
exit /b %RC%
