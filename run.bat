@echo off
REM ===========================================================
REM  ALBATROSS  -  Sentinel-2 field console launcher
REM  Double-click this file to start the dashboard.
REM ===========================================================
setlocal
cd /d "%~dp0"

REM --- make sure we're actually in the extracted app folder --
if not exist "requirements.txt" (
    echo.
    echo  ============================================================
    echo   [Albatross] The app files were not found next to run.bat.
    echo   Current folder:
    echo     %CD%
    echo.
    echo   This almost always means run.bat was started from INSIDE
    echo   the downloaded .zip. Windows only unpacks this one file to
    echo   a temporary folder, so the rest of the app is missing.
    echo.
    echo   FIX: close this window, then in your Downloads folder
    echo   right-click the Albatross .zip  -^>  "Extract All...",
    echo   open the extracted folder, and double-click run.bat there.
    echo  ============================================================
    echo.
    pause
    exit /b 1
)

REM --- self-update if this folder is a git checkout ----------
if exist ".git" (
    where git >nul 2>&1 && (
        echo [Albatross] Checking for updates...
        git pull --ff-only
    )
)

REM --- make sure Python is available -------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [Albatross] Python was not found on your PATH.
    echo             Install Python 3.11+ from https://python.org and try again.
    pause
    exit /b 1
)

REM --- install dependencies on first run ---------------------
python -c "import fastapi, geopandas, tifffile" >nul 2>&1
if errorlevel 1 (
    echo [Albatross] First run: installing dependencies, this may take a minute...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [Albatross] Dependency install failed. See the messages above.
        pause
        exit /b 1
    )
)

REM --- open the browser a few seconds after the server boots -
echo [Albatross] Launching on http://127.0.0.1:8137
start "" /min cmd /c "ping -n 4 127.0.0.1 >nul & start http://127.0.0.1:8137"

REM --- run the server (Ctrl+C in this window to stop) --------
python -m uvicorn app:app --host 127.0.0.1 --port 8137

echo.
echo [Albatross] Server stopped.
pause
