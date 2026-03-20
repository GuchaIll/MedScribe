@echo off
REM Quick test runner for Windows
REM Usage: test.bat [options]

echo ====================================================================
echo MEDICAL TRANSCRIPTION APP - QUICK TEST RUNNER
echo ====================================================================

if "%1"=="all" (
    echo Running all tests with coverage...
    python run_tests.py
    goto :end
)

if "%1"=="quick" (
    echo Running quick tests (no coverage, skip slow)...
    python run_tests.py --quick
    goto :end
)

if "%1"=="unit" (
    echo Running unit tests only...
    python run_tests.py -m unit
    goto :end
)

if "%1"=="cov" (
    echo Running tests with coverage report...
    python run_tests.py --cov-report=html
    start htmlcov\index.html
    goto :end
)

if "%1"=="failed" (
    echo Re-running failed tests...
    python run_tests.py --lf
    goto :end
)

if "%1"=="help" (
    echo Available commands:
    echo   test all      - Run all tests with coverage
    echo   test quick    - Quick test run (no coverage, skip slow tests)
    echo   test unit     - Run unit tests only
    echo   test cov      - Run tests and open coverage report
    echo   test failed   - Re-run only failed tests
    echo   test help     - Show this help message
    echo.
    echo For more options, use: python run_tests.py --help
    goto :end
)

REM Default: run all tests
echo Running all tests with coverage...
python run_tests.py

:end
