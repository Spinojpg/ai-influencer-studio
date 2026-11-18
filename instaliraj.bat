@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo   AI Influencer Studio - instalacija
echo ============================================
echo.

set "INSTALL_ROOT=%LOCALAPPDATA%\AIInfluencerStudio"
set "APP_DIR=%INSTALL_ROOT%\app"
set "DATA_DIR=%INSTALL_ROOT%\data"

if not exist "%APP_DIR%" mkdir "%APP_DIR%"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%DATA_DIR%\profiles" mkdir "%DATA_DIR%\profiles"
if not exist "%DATA_DIR%\outputs" mkdir "%DATA_DIR%\outputs"
if not exist "%DATA_DIR%\uploads" mkdir "%DATA_DIR%\uploads"

echo Kopiram aplikaciju u:
echo   %APP_DIR%
echo Podaci ostaju u:
echo   %DATA_DIR%
echo.

rem robocopy kod 0-7 je uspjeh
robocopy "%~dp0." "%APP_DIR%" /E /NFL /NDL /NJH /NJS /NC /NS /NP /XD data __pycache__ .git dist pending-update backup /XF .env studio.db studio.pid update-result.json profiles.json persona.json *.pyc
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 echo GRESKA: kopiranje nije uspjelo, kod %RC%
if %RC% GEQ 8 exit /b 1

rem Stari podaci pored ove mape - preseli bez prepisivanja
if exist "%~dp0.env" if not exist "%DATA_DIR%\.env" copy /y "%~dp0.env" "%DATA_DIR%\.env" >nul
if exist "%~dp0persona.json" if not exist "%DATA_DIR%\persona.json" copy /y "%~dp0persona.json" "%DATA_DIR%\persona.json" >nul
if exist "%~dp0profiles.json" if not exist "%DATA_DIR%\profiles.json" copy /y "%~dp0profiles.json" "%DATA_DIR%\profiles.json" >nul
if exist "%~dp0studio.db" if not exist "%DATA_DIR%\studio.db" copy /y "%~dp0studio.db" "%DATA_DIR%\studio.db" >nul
if exist "%~dp0update.json" if not exist "%DATA_DIR%\update.json" copy /y "%~dp0update.json" "%DATA_DIR%\update.json" >nul
if exist "%~dp0data" (
  echo Preselim postojece podatke iz mape data...
  robocopy "%~dp0data" "%DATA_DIR%" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NC /NS /NP /XF studio.pid update-result.json
)

if not exist "%DATA_DIR%\update.json" if exist "%APP_DIR%\update.json.example" copy /y "%APP_DIR%\update.json.example" "%DATA_DIR%\update.json" >nul
if not exist "%DATA_DIR%\.env" if exist "%APP_DIR%\.env.example" copy /y "%APP_DIR%\.env.example" "%DATA_DIR%\.env" >nul

if not exist "%APP_DIR%\app.ico" if exist "%APP_DIR%\tools\make_icon.py" (
  echo Generiram ikonu...
  if exist "C:\ComfyUI-Zluda\venv\Scripts\python.exe" "C:\ComfyUI-Zluda\venv\Scripts\python.exe" "%APP_DIR%\tools\make_icon.py" "%APP_DIR%\app.ico"
  if not exist "%APP_DIR%\app.ico" py -3.11 "%APP_DIR%\tools\make_icon.py" "%APP_DIR%\app.ico"
)

echo.
echo --------------------------------------------
echo  Auto-update ide s privatnog GitHub repoa:
echo    Spinojpg / ai-influencer-studio
echo  Zato treba GITHUB_TOKEN u data\.env
echo --------------------------------------------
echo.
echo Kako napraviti token, korak po korak:
echo   1. Otvori https://github.com i prijavi se.
echo   2. Klikni avatar gore desno, zatim Settings.
echo   3. Lijevo, skroz dolje: Developer settings.
echo   4. Personal access tokens, pa Fine-grained tokens.
echo   5. Generate new token.
echo   6. Ime npr. AI Influencer Studio update, odaberi rok.
echo   7. Repository access: Only select repositories.
echo   8. Odaberi samo: ai-influencer-studio.
echo   9. Permissions, Contents: Read-only. Ostalo ostavi No access.
echo  10. Generate token i odmah ga kopiraj. GitHub ga vise ne pokazuje.
echo  11. Zalijepi ga ovdje, ili upisi u datoteku:
echo      %DATA_DIR%\.env
echo      u retku: GITHUB_TOKEN=tvoj_token
echo.
echo Detaljne upute na hrvatskom: TOKEN_UPUTE.txt
echo.
set "GHTOKEN="
set /p GHTOKEN=Zalijepi token i pritisni Enter, ili samo Enter za preskociti:
if not defined GHTOKEN goto after_token
if "!GHTOKEN!"=="" goto after_token

set "PYSET="
if exist "C:\ComfyUI-Zluda\venv\Scripts\python.exe" set "PYSET=C:\ComfyUI-Zluda\venv\Scripts\python.exe"
if not defined PYSET (
  where py >nul 2>&1
  if not errorlevel 1 set "PYSET=py -3.11"
)
if not defined PYSET (
  where python >nul 2>&1
  if not errorlevel 1 set "PYSET=python"
)
if not defined PYSET goto token_manual
set "STUDIO_SET_GITHUB_TOKEN=!GHTOKEN!"
%PYSET% "%APP_DIR%\tools\set_github_token.py" "%DATA_DIR%"
set "STUDIO_SET_GITHUB_TOKEN="
set "GHTOKEN="
echo Token je upisan. Ne dijeli ga i ne salji nikome.
goto after_token

:token_manual
echo Nisam nasao Python za upis tokena.
echo Otvori %DATA_DIR%\.env i dodaj red GITHUB_TOKEN=...
set "GHTOKEN="

:after_token
echo.

echo Pravim precace na Desktopu i u izborniku Start...
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\tools\create-shortcuts.ps1" -AppDir "%APP_DIR%" -IconPath "%APP_DIR%\app.ico"
if errorlevel 1 (
  echo PowerShell nije uspio, pokusavam VBS...
  cscript //nologo "%APP_DIR%\tools\create-shortcuts.vbs" "%APP_DIR%" "%APP_DIR%\app.ico"
)

echo.
echo Instalirano.
echo Pokreni preko precaca "AI Influencer Studio".
echo Kljuceve pisi u: %DATA_DIR%\.env
echo Update izvor u:   %DATA_DIR%\update.json
echo.
echo Za uklanjanje: deinstaliraj.bat  - podaci ostaju, osim ako navedes /podaci
echo.
pause
exit /b 0
