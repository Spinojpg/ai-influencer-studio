@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  Pokrecem ComfyUI pa Studio
echo ============================================
echo.

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo ComfyUI vec odgovara na http://127.0.0.1:8188
    echo Preskacem ponovno pokretanje.
    goto :start_studio
)

if not exist "C:\ComfyUI-Zluda\comfyui-n.bat" (
    echo [GRESKA] Nema C:\ComfyUI-Zluda\comfyui-n.bat
    echo.
    pause
    exit /b 1
)

echo Pokrecem ComfyUI u novom prozoru ...
start "ComfyUI" cmd /k "cd /d C:\ComfyUI-Zluda && comfyui-n.bat"

echo Cekam da http://127.0.0.1:8188 odgovori, najvise 5 minuta ...
echo Prvo pokretanje moze potrajati.
echo.

powershell -NoProfile -Command ^
  "$limit=300; $url='http://127.0.0.1:8188/system_stats'; $ok=$false;" ^
  "for ($i=0; $i -lt $limit; $i+=2) {" ^
  "  try { $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2; if ($r.StatusCode -eq 200) { $ok=$true; break } } catch {}" ^
  "  Start-Sleep -Seconds 2;" ^
  "  if (($i %% 20) -eq 0) { Write-Host ('  ... ' + $i + 's') }" ^
  "};" ^
  "if ($ok) { Write-Host 'ComfyUI je spreman.'; exit 0 } else { Write-Host 'ISTEKLO CEKANJE.'; exit 1 }"

if errorlevel 1 (
    echo.
    echo [GRESKA] ComfyUI nije odgovorio u 5 minuta.
    echo Pogledaj prozor ComfyUI za poruku o gresci.
    echo Zatim pokreni start_studio.bat kad API proradi.
    echo.
    pause
    exit /b 1
)

:start_studio
echo.
echo Pokrecem Studio ...
call "%~dp0start_studio.bat"
set "RC=%ERRORLEVEL%"
endlocal
exit /b %RC%
