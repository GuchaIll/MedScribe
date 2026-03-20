@echo off
REM ============================================================================
REM MedScribe — Start All Services (Database, Backend, Frontend)
REM ============================================================================

echo ============================================
echo  MedScribe — Starting All Services
echo ============================================
echo.

REM --- 1. Start PostgreSQL Docker container ---
echo [1/3] Starting PostgreSQL (Docker)...
docker start medicaltranscriptionapp-db-1 >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Failed to start PostgreSQL container.
    echo  Make sure Docker Desktop is running and the container exists.
    echo  You can create it with: docker run -d --name medicaltranscriptionapp-db-1 -e POSTGRES_DB=medscribe -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 pgvector/pgvector:pg15
    pause
    exit /b 1
)
echo  PostgreSQL started on port 5432.
echo.

REM --- 2. Wait briefly for DB to accept connections ---
timeout /t 3 /nobreak >nul

REM --- 3. Run database migrations ---
echo [2/3] Running database migrations...
pushd server
call .venv\Scripts\activate.bat
alembic upgrade head
if %errorlevel% neq 0 (
    echo  WARNING: Migrations failed — the server may still start but could have issues.
)
echo.

REM --- 4. Start backend (new window) ---
echo [3/3] Starting backend and frontend...
start "MedScribe Backend" cmd /k "cd /d %~dp0server && .venv\Scripts\activate.bat && uvicorn main:app --reload --port 3001"
popd

REM --- 5. Start frontend (new window) ---
start "MedScribe Frontend" cmd /k "cd /d %~dp0client\medscribe && npm start"

echo.
echo ============================================
echo  All services launched:
echo    Database:  localhost:5432
echo    Backend:   http://localhost:3001
echo    Frontend:  http://localhost:3000
echo ============================================
echo.
echo Close the Backend and Frontend terminal windows to stop those services.
echo To stop the database: docker stop medicaltranscriptionapp-db-1
echo.
pause
