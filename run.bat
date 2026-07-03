@echo off
REM ===========================================================
REM  ALBATROSS  -  Sentinel-2 field console launcher
REM  Double-click this file to start the dashboard.
REM ===========================================================
setlocal
REM pushd (not cd) so this also works from a network / UNC path
REM (\\server\share\...): it maps the share to a temp drive letter.
pushd "%~dp0"

if not exist "requirements.txt" goto :nofiles

REM --- self-update if this folder is a git checkout ----------
if exist ".git" (
    where git >nul 2>&1 && git pull --ff-only
)

REM --- make sure Python is available -------------------------
python --version >nul 2>&1
if errorlevel 1 goto :nopython

REM --- install dependencies on first run ---------------------
python -c "import fastapi, geopandas, tifffile" >nul 2>&1
if not errorlevel 1 goto :launch
echo [Albatross] First run: installing dependencies, this may take a minute...
python -m pip install -r requirements.txt
if errorlevel 1 goto :depsfail

:launch
REM --- open the browser a few seconds after the server boots -
echo [Albatross] Launching on http://127.0.0.1:8137
start "" /min cmd /c "ping -n 4 127.0.0.1 >nul & start http://127.0.0.1:8137"

REM --- run the server (Ctrl+C in this window to stop) --------
python -m uvicorn app:app --host 127.0.0.1 --port 8137

echo.
echo [Albatross] Server stopped.
popd
pause
exit /b 0

:nofiles
echo.
echo  ============================================================
echo   [Albatross] The app files were not found next to run.bat.
echo   Current folder: %CD%
echo.
echo   Fix: right-click the downloaded ZIP, choose "Extract All",
echo   then open the extracted folder and run run.bat from there.
echo  ============================================================
echo.
popd
pause
exit /b 1

:nopython
echo.
echo   [Albatross] Python was not found on your PATH.
echo   Install Python 3.11+ from https://python.org and run this again.
echo   Tip: during install, tick "Add Python to PATH".
echo.
popd
pause
exit /b 1

:depsfail
echo.
echo   [Albatross] Dependency install failed. See the messages above.
echo.
popd
pause
exit /b 1
