# ==============================================================================
# MedScribe — Stop All Services
# ==============================================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  MedScribe - Stopping All Services" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Stop uvicorn processes
Write-Host "[1/3] Stopping backend (uvicorn)..." -ForegroundColor Yellow
Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
# Also kill python processes running on port 3001
$backendPid = (Get-NetTCPConnection -LocalPort 3001 -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
if ($backendPid) {
    $backendPid | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Write-Host "  Backend stopped." -ForegroundColor Green
} else {
    Write-Host "  Backend was not running." -ForegroundColor Gray
}

# Stop node/react dev server
Write-Host "[2/3] Stopping frontend (React dev server)..." -ForegroundColor Yellow
$frontendPid = (Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
if ($frontendPid) {
    $frontendPid | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Write-Host "  Frontend stopped." -ForegroundColor Green
} else {
    Write-Host "  Frontend was not running." -ForegroundColor Gray
}

# Stop PostgreSQL container
Write-Host "[3/3] Stopping PostgreSQL (Docker)..." -ForegroundColor Yellow
docker stop medicaltranscriptionapp-db-1 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  PostgreSQL stopped." -ForegroundColor Green
} else {
    Write-Host "  PostgreSQL was not running." -ForegroundColor Gray
}

Write-Host ""
Write-Host "All services stopped." -ForegroundColor Cyan
Write-Host ""
