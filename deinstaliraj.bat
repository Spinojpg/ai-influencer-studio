@echo off
setlocal EnableExtensions
set "INSTALL_ROOT=%LOCALAPPDATA%\AIInfluencerStudio"
set "APP_DIR=%INSTALL_ROOT%\app"
set "DATA_DIR=%INSTALL_ROOT%\data"
set "WIPE_DATA="

if /I "%~1"=="/podaci" set "WIPE_DATA=1"
if /I "%~1"=="--podaci" set "WIPE_DATA=1"
if /I "%~1"=="/data" set "WIPE_DATA=1"

echo ============================================
echo   AI Influencer Studio - uklanjanje
echo ============================================
echo.
echo Brise se aplikacija iz:
echo   %APP_DIR%
echo Uklanjaju se precaci "AI Influencer Studio".
echo.

if defined WIPE_DATA goto wipe_yes
echo Korisnicki podaci u mapi data OSTAJU:
echo   %DATA_DIR%
echo.
echo Ako zelis obrisati i podatke, zatvori ovo i pokreni:
echo   deinstaliraj.bat /podaci
echo ili tipkaj DA velikim slovima ispod.
set "ANS="
set /p ANS=Obrisati i korisnicke podatke? 
if /I "%ANS%"=="DA" set "WIPE_DATA=1"
goto do_remove

:wipe_yes
echo UPOZORENJE: brisem i korisnicke podatke u %DATA_DIR%
echo.

:do_remove
del "%USERPROFILE%\Desktop\AI Influencer Studio.lnk" >nul 2>&1
del "%PUBLIC%\Desktop\AI Influencer Studio.lnk" >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\AI Influencer Studio.lnk" >nul 2>&1

if exist "%APP_DIR%" rmdir /s /q "%APP_DIR%"
if exist "%INSTALL_ROOT%\backup" if defined WIPE_DATA rmdir /s /q "%INSTALL_ROOT%\backup"
if exist "%DATA_DIR%" if defined WIPE_DATA rmdir /s /q "%DATA_DIR%"

if exist "%APP_DIR%" echo GRESKA: nisam mogao obrisati %APP_DIR% - zatvori Studio pa pokusaj opet.
if exist "%APP_DIR%" exit /b 1

if not exist "%DATA_DIR%" if not exist "%INSTALL_ROOT%\backup" if exist "%INSTALL_ROOT%" rmdir "%INSTALL_ROOT%" >nul 2>&1

echo.
echo Uklonjeno.
if not defined WIPE_DATA echo Podaci su ostali u %DATA_DIR%
echo.
pause
exit /b 0
