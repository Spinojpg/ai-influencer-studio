@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM Uvijek kreni iz C:\ComfyUI-Zluda. Pokretanje comfyui-n.bat iz druge
REM mape cesto lomi putanje do venv, modela i custom nodeova.

echo ============================================
echo  Pokretanje ComfyUI-Zluda
echo  Mapa: C:\ComfyUI-Zluda
echo  Skripta: comfyui-n.bat
echo  API: http://127.0.0.1:8188
echo ============================================
echo.

if not exist "C:\ComfyUI-Zluda\comfyui-n.bat" (
    echo [GRESKA] Nema C:\ComfyUI-Zluda\comfyui-n.bat
    echo Provjeri je li ComfyUI-Zluda instaliran u tu mapu.
    echo.
    pause
    exit /b 1
)

cd /d C:\ComfyUI-Zluda
if errorlevel 1 (
    echo [GRESKA] Ne mogu uci u C:\ComfyUI-Zluda
    pause
    exit /b 1
)

echo Radna mapa je sada: %CD%
echo Pokrecem comfyui-n.bat ...
echo.
call comfyui-n.bat
set "RC=%ERRORLEVEL%"
echo.
echo ComfyUI je zavrsio sa kodom %RC%.
pause
endlocal
exit /b %RC%
