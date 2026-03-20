# ==============================================================================
# MedScribe — Start All Services (Database, Backend, Frontend)
# ==============================================================================

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  MedScribe - Starting All Services" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- 1. Start PostgreSQL Docker container ---
Write-Host "[1/3] Starting PostgreSQL (Docker)..." -ForegroundColor Yellow
docker start medicaltranscriptionapp-db-1 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Failed to start PostgreSQL container." -ForegroundColor Red
    Write-Host "  Make sure Docker Desktop is running and the container exists."
    Write-Host "  Create it with:" -ForegroundColor Gray
    Write-Host "    docker run -d --name medicaltranscriptionapp-db-1 -e POSTGRES_DB=medscribe -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 pgvector/pgvector:pg15" -ForegroundColor Gray
    exit 1
}
Write-Host "  PostgreSQL started on port 5432." -ForegroundColor Green
Write-Host ""

# --- 2. Wait for DB to accept connections ---
Write-Host "  Waiting for database to be ready..." -ForegroundColor Gray
Start-Sleep -Seconds 3

# --- 3. Run database migrations ---
Write-Host "[2/3] Running database migrations..." -ForegroundColor Yellow
Push-Location "$rootDir\server"
& .\.venv\Scripts\Activate.ps1
alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WARNING: Migrations failed - the server may still start but could have issues." -ForegroundColor DarkYellow
}
Pop-Location
Write-Host ""

# --- 4. Start backend in a new terminal ---
Write-Host "[3/3] Starting backend and frontend..." -ForegroundColor Yellow

Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
    Set-Location '$rootDir\server'
    & .\.venv\Scripts\Activate.ps1
    Write-Host 'Starting MedScribe Backend on port 3001...' -ForegroundColor Green
    uvicorn main:app --reload --port 3001
"@

# --- 5. Start frontend in a new terminal ---
Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
    Set-Location '$rootDir\client\medscribe'
    Write-Host 'Starting MedScribe Frontend on port 3000...' -ForegroundColor Green
    npm start
"@

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  All services launched:" -ForegroundColor Cyan
Write-Host "    Database:  localhost:5432" -ForegroundColor White
Write-Host "    Backend:   http://localhost:3001" -ForegroundColor White
Write-Host "    Frontend:  http://localhost:3000" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Close the Backend/Frontend terminal windows to stop those services."
Write-Host "To stop the database: docker stop medicaltranscriptionapp-db-1"
Write-Host ""
