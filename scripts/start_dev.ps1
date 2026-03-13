<#
.SYNOPSIS
    Start both the FastAPI backend (port 3001) and React frontend (port 3000).

.DESCRIPTION
    Launches the backend and frontend as parallel background jobs from a single
    terminal.  Press Ctrl+C to tear down both processes.

.EXAMPLE
    .\scripts\start_dev.ps1
#>

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SERVER_DIR = Join-Path $ROOT "server"
$CLIENT_DIR = Join-Path $ROOT "client" "medscribe"
$VENV_PYTHON = Join-Path $SERVER_DIR ".venv" "Scripts" "python.exe"

# ── Preflight checks ────────────────────────────────────────────────────────
if (-not (Test-Path $VENV_PYTHON)) {
    Write-Host "[ERROR] Python venv not found at $VENV_PYTHON" -ForegroundColor Red
    Write-Host "  Run:  cd server && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

$NPM = Get-Command npm -ErrorAction SilentlyContinue
if (-not $NPM) {
    Write-Host "[ERROR] npm not found in PATH" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path (Join-Path $CLIENT_DIR "node_modules"))) {
    Write-Host "[INFO] Installing frontend dependencies..." -ForegroundColor Yellow
    Push-Location $CLIENT_DIR
    npm install
    Pop-Location
}

# ── Launch backend ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Starting Backend (FastAPI :3001) ===" -ForegroundColor Cyan

$backendJob = Start-Job -Name "backend" -ScriptBlock {
    param($pythonExe, $serverDir)
    Set-Location $serverDir
    & $pythonExe -m uvicorn main:app --reload --host 127.0.0.1 --port 3001
} -ArgumentList $VENV_PYTHON, $SERVER_DIR

# ── Launch frontend ──────────────────────────────────────────────────────────
Write-Host "=== Starting Frontend (React  :3000) ===" -ForegroundColor Green

$frontendJob = Start-Job -Name "frontend" -ScriptBlock {
    param($clientDir)
    Set-Location $clientDir
    $env:BROWSER = "none"          # don't auto-open browser
    npm start
} -ArgumentList $CLIENT_DIR

# ── Stream output until Ctrl+C ──────────────────────────────────────────────
Write-Host ""
Write-Host "Both servers starting — press Ctrl+C to stop." -ForegroundColor Yellow
Write-Host "  Backend  -> http://localhost:3001"
Write-Host "  Frontend -> http://localhost:3000"
Write-Host ""

try {
    while ($true) {
        # Receive and print output from both jobs
        @($backendJob, $frontendJob) | ForEach-Object {
            $tag = if ($_.Name -eq "backend") { "[API]" } else { "[WEB]" }
            $color = if ($_.Name -eq "backend") { "Cyan" } else { "Green" }
            Receive-Job $_ 2>&1 | ForEach-Object {
                Write-Host "$tag $_" -ForegroundColor $color
            }
        }

        # Check if either job failed
        if ($backendJob.State -eq "Failed") {
            Write-Host "[ERROR] Backend crashed." -ForegroundColor Red
            Receive-Job $backendJob 2>&1 | Write-Host
            break
        }
        if ($frontendJob.State -eq "Failed") {
            Write-Host "[ERROR] Frontend crashed." -ForegroundColor Red
            Receive-Job $frontendJob 2>&1 | Write-Host
            break
        }

        Start-Sleep -Milliseconds 500
    }
}
finally {
    Write-Host ""
    Write-Host "Shutting down..." -ForegroundColor Yellow
    Stop-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
    Remove-Job $backendJob, $frontendJob -Force -ErrorAction SilentlyContinue
    Write-Host "Done." -ForegroundColor Green
}
