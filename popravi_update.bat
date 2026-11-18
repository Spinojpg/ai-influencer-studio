@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo   AI Influencer Studio - popravi update
echo ============================================
echo.
echo Ako u aplikaciji vidis novu verziju, a nakon zatvaranja
echo se vrati stara, stari updater nije mogao zamijeniti
echo datoteke dok je program bio otvoren.
echo.
echo Ovaj program instalira datoteke iz OVE mape u:
echo   %LOCALAPPDATA%\AIInfluencerStudio\app
echo Korisnicki podaci u mapi data ostaju.
echo.

if not exist "%~dp0studio.py" (
  echo GRESKA: pokreni ovaj fajl iz raspakirane mape simple-studio
  echo u kojoj stoje studio.py i version.json.
  pause
  exit /b 1
)
if not exist "%~dp0instaliraj.bat" (
  echo GRESKA: nema instaliraj.bat pored ovog fajla.
  pause
  exit /b 1
)

echo Pokrecem instalaciju...
call "%~dp0instaliraj.bat"
exit /b %ERRORLEVEL%
