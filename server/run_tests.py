#!/usr/bin/env python
"""
Test Runner Script for Medical Transcription App

This script provides a systematic way to run the test suite with various options.
It supports:
- Running all tests or specific test modules
- Coverage reporting
- Different verbosity levels
- Test result summaries
- Parallel execution

Usage:
    # Run all tests with coverage
    python run_tests.py

    # Run specific test module
    python run_tests.py tests/unit/test_normalize_transcript.py

    # Run tests with specific marker
    python run_tests.py -m unit

    # Run with high verbosity
    python run_tests.py -v

    # Run without coverage
    python run_tests.py --no-cov

    # Run tests in parallel (requires pytest-xdist)
    python run_tests.py --parallel
"""

import sys
import os
import argparse
from pathlib import Path


def main():
    """Main test runner function."""
    parser = argparse.ArgumentParser(
        description="Run Medical Transcription App test suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "tests",
        nargs="*",
        help="Specific test files or directories to run (default: all tests)"
    )

    parser.add_argument(
        "-m", "--marker",
        help="Run tests with specific marker (unit, integration, slow, db, llm)"
    )

    parser.add_argument(
        "-k", "--keyword",
        help="Run tests matching keyword expression"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (can be used multiple times: -v, -vv, -vvv)"
    )

    parser.add_argument(
        "--no-cov",
        action="store_true",
        help="Disable coverage reporting"
    )

    parser.add_argument(
        "--cov-report",
        choices=["html", "term", "xml", "all"],
        default="all",
        help="Coverage report format (default: all)"
    )

    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run tests in parallel (requires pytest-xdist)"
    )

    parser.add_argument(
        "--failfast",
        action="store_true",
        help="Stop on first test failure"
    )

    parser.add_argument(
        "--pdb",
        action="store_true",
        help="Drop into debugger on test failure"
    )

    parser.add_argument(
        "--lf", "--last-failed",
        action="store_true",
        dest="last_failed",
        help="Run only tests that failed last time"
    )

    parser.add_argument(
        "--ff", "--failed-first",
        action="store_true",
        dest="failed_first",
        help="Run failed tests first, then others"
    )

    parser.add_argument(
        "--duration",
        type=int,
        metavar="N",
        help="Show N slowest test durations"
    )

    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick test run (skip slow tests, no coverage)"
    )

    args = parser.parse_args()

    # Build pytest command
    pytest_args = []

    # Add test paths or default to tests directory
    if args.tests:
        pytest_args.extend(args.tests)
    else:
        pytest_args.append("tests/")

    # Verbosity
    if args.verbose:
        pytest_args.append("-" + "v" * min(args.verbose, 3))

    # Marker
    if args.marker:
        pytest_args.extend(["-m", args.marker])

    # Keyword
    if args.keyword:
        pytest_args.extend(["-k", args.keyword])

    # Coverage
    if not args.no_cov and not args.quick:
        pytest_args.append("--cov=app")
        pytest_args.append("--cov-report=term-missing")

        if args.cov_report in ["html", "all"]:
            pytest_args.append("--cov-report=html")
        if args.cov_report in ["xml", "all"]:
            pytest_args.append("--cov-report=xml")

    # Parallel execution
    if args.parallel:
        try:
            import xdist
            pytest_args.extend(["-n", "auto"])
        except ImportError:
            print("[WARNING] pytest-xdist not installed, running serially")
            print("[INFO] Install with: pip install pytest-xdist")

    # Fail fast
    if args.failfast:
        pytest_args.append("-x")

    # Debugger
    if args.pdb:
        pytest_args.append("--pdb")

    # Last failed / failed first
    if args.last_failed:
        pytest_args.append("--lf")
    if args.failed_first:
        pytest_args.append("--ff")

    # Duration reporting
    if args.duration:
        pytest_args.extend(["--durations", str(args.duration)])

    # Quick mode
    if args.quick:
        pytest_args.extend(["-m", "not slow"])
        print("[INFO] Quick mode: skipping slow tests and coverage")

    # Print test configuration
    print("=" * 70)
    print("MEDICAL TRANSCRIPTION APP - TEST RUNNER")
    print("=" * 70)
    print(f"Working directory: {os.getcwd()}")
    print(f"Python version: {sys.version.split()[0]}")
    print(f"Test path: {args.tests if args.tests else 'tests/'}")
    if args.marker:
        print(f"Marker filter: {args.marker}")
    if args.keyword:
        print(f"Keyword filter: {args.keyword}")
    print(f"Coverage: {'disabled' if args.no_cov or args.quick else 'enabled'}")
    print(f"Parallel: {'enabled' if args.parallel else 'disabled'}")
    print("-" * 70)

    # Import and run pytest
    try:
        import pytest
    except ImportError:
        print("[ERROR] pytest not installed!")
        print("[INFO] Install test dependencies with: pip install -r requirements.txt")
        return 1

    # Run pytest with constructed arguments
    exit_code = pytest.main(pytest_args)

    # Print summary
    print("\n" + "=" * 70)
    if exit_code == 0:
        print("[OK] All tests passed!")
        if not args.no_cov and not args.quick:
            print("[INFO] Coverage report available at: htmlcov/index.html")
    elif exit_code == 1:
        print("[FAILED] Some tests failed")
    elif exit_code == 2:
        print("[ERROR] Test execution interrupted")
    elif exit_code == 3:
        print("[ERROR] Internal error during test execution")
    elif exit_code == 4:
        print("[ERROR] pytest command line usage error")
    elif exit_code == 5:
        print("[INFO] No tests collected")

    print("=" * 70)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
