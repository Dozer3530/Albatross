# ===========================================================
#  ALBATROSS  -  Sentinel-2 field console launcher (PowerShell)
#  Run:  ./run.ps1      (or right-click > Run with PowerShell)
# ===========================================================
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# --- make sure Python is available ---------------------------
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[Albatross] Python was not found on your PATH." -ForegroundColor Yellow
    Write-Host "            Install Python 3.11+ from https://python.org and try again."
    Read-Host "Press Enter to exit"
    exit 1
}

# --- install dependencies on first run -----------------------
python -c "import fastapi, geopandas, tifffile" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[Albatross] First run: installing dependencies, this may take a minute..." -ForegroundColor Cyan
    python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[Albatross] Dependency install failed. See the messages above." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# --- open the browser shortly after the server boots ---------
Write-Host "[Albatross] Launching on http://127.0.0.1:8137" -ForegroundColor Green
Start-Job { Start-Sleep -Seconds 3; Start-Process "http://127.0.0.1:8137" } | Out-Null

# --- run the server (Ctrl+C to stop) -------------------------
python -m uvicorn app:app --host 127.0.0.1 --port 8137
