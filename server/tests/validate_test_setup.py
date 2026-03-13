#!/usr/bin/env python
"""
Validate Test Setup

Checks that the test environment is properly configured.
Run before running tests to ensure everything is set up correctly.

Usage (from server/ directory):
    python tests/validate_test_setup.py
"""

import sys
import os
from pathlib import Path

# All path checks are resolved relative to the server/ directory,
# regardless of where this script is invoked from.
SERVER_DIR = Path(__file__).parent.parent


def check_python_version():
    """Check Python version."""
    print("Checking Python version...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"  [ERROR] Python 3.8+ required, found {version.major}.{version.minor}")
        return False
    print(f"  [OK] Python {version.major}.{version.minor}.{version.micro}")
    return True


def check_dependencies():
    """Check required test dependencies."""
    print("\nChecking test dependencies...")
    required = [
        ("pytest", "pytest"),
        ("pytest-asyncio", "pytest_asyncio"),
        ("pytest-cov", "pytest_cov"),
        ("pytest-mock", "pytest_mock"),
        ("faker", "faker"),
        ("sqlalchemy", "sqlalchemy"),
    ]

    all_installed = True
    for package_name, import_name in required:
        try:
            __import__(import_name)
            print(f"  [OK] {package_name}")
        except ImportError:
            print(f"  [ERROR] {package_name} not installed")
            all_installed = False

    return all_installed


def check_project_structure():
    """Check project structure."""
    print("\nChecking project structure...")
    required_paths = [
        "app/",
        "app/agents/",
        "app/core/",
        "app/database/",
        "tests/",
        "tests/unit/",
        "tests/conftest.py",
        "pytest.ini",
    ]

    all_exist = True
    for path in required_paths:
        full = SERVER_DIR / path
        if full.exists():
            print(f"  [OK] {path}")
        else:
            print(f"  [ERROR] {path} not found")
            all_exist = False

    return all_exist


def check_test_files():
    """Check test files."""
    print("\nChecking test files...")
    test_files = [
        "tests/unit/test_normalize_transcript.py",
        "tests/unit/test_segment_and_chunk.py",
        "tests/unit/test_retrieve_evidence.py",
        "tests/unit/test_human_review_gate.py",
        "tests/unit/test_workflow_engine.py",
        "tests/unit/test_patient_service.py",
        "tests/smoke_test.py",
    ]

    all_exist = True
    for test_file in test_files:
        full = SERVER_DIR / test_file
        if full.exists():
            print(f"  [OK] {test_file}")
        else:
            print(f"  [ERROR] {test_file} not found")
            all_exist = False

    return all_exist


def check_source_modules():
    """Check that source modules can be imported."""
    print("\nChecking source modules...")
    modules = [
        ("app.agents.normalize_transcript", "normalize_transcript_node"),
        ("app.agents.segment_and_chunk", "segment_and_chunk_node"),
        ("app.agents.retrieve_evidence", "retrieve_evidence_node"),
        ("app.agents.human_review_gate", "human_review_gate_node"),
        ("app.core.workflow_engine", "WorkflowEngine"),
        ("app.core.patient_service", "PatientService"),
    ]

    all_importable = True
    for module_name, function_name in modules:
        try:
            module = __import__(module_name, fromlist=[function_name])
            getattr(module, function_name)
            print(f"  [OK] {module_name}.{function_name}")
        except ImportError as e:
            print(f"  [ERROR] Cannot import {module_name}: {e}")
            all_importable = False
        except AttributeError as e:
            print(f"  [ERROR] {module_name} missing {function_name}: {e}")
            all_importable = False

    return all_importable


def check_pytest_config():
    """Check pytest configuration."""
    print("\nChecking pytest configuration...")
    ini = SERVER_DIR / "pytest.ini"
    if not ini.exists():
        print("  [ERROR] pytest.ini not found")
        return False

    print("  [OK] pytest.ini exists")

    try:
        import pytest
        # Collect from the tests/ directory (sibling of this file)
        tests_dir = str(Path(__file__).parent)
        exit_code = pytest.main(["--collect-only", "-q", tests_dir])
        if exit_code == 0:
            print("  [OK] Test collection successful")
            return True
        elif exit_code == 5:
            print("  [WARNING] No tests collected (this might be OK if tests haven't been created yet)")
            return True
        else:
            print(f"  [ERROR] Test collection failed with exit code {exit_code}")
            return False
    except Exception as e:
        print(f"  [ERROR] Cannot run pytest: {e}")
        return False


def main():
    """Run all validation checks."""
    print("=" * 70)
    print("MEDICAL TRANSCRIPTION APP - TEST SETUP VALIDATION")
    print("=" * 70)

    checks = [
        ("Python Version", check_python_version),
        ("Dependencies", check_dependencies),
        ("Project Structure", check_project_structure),
        ("Test Files", check_test_files),
        ("Source Modules", check_source_modules),
        ("Pytest Configuration", check_pytest_config),
    ]

    results = []
    for check_name, check_func in checks:
        try:
            result = check_func()
            results.append((check_name, result))
        except Exception as e:
            print(f"\n[EXCEPTION] Error during {check_name}: {e}")
            results.append((check_name, False))

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    all_passed = True
    for check_name, result in results:
        status = "[OK]" if result else "[FAILED]"
        print(f"{status:10} {check_name}")
        if not result:
            all_passed = False

    print("=" * 70)

    if all_passed:
        print("\n[SUCCESS] Test environment is properly configured!")
        print("\nYou can now run tests:")
        print("  python run_tests.py")
        print("  test all")
        return 0
    else:
        print("\n[FAILED] Test environment has issues!")
        print("\nTo fix:")
        print("  1. Install dependencies: pip install -r requirements.txt")
        print("  2. Ensure you're in the server directory")
        print("  3. Check that all source files are present")
        return 1


if __name__ == "__main__":
    sys.exit(main())
