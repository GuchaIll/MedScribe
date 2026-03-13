# Testing Guide - Medical Transcription App

## Quick Start

### 1. Install Test Dependencies

```bash
cd server
pip install pytest pytest-asyncio pytest-cov pytest-mock faker
```

Or install all dependencies from requirements.txt:
```bash
pip install -r requirements.txt
```

### 2. Validate Test Setup

Run the validation script to ensure everything is configured correctly:

```bash
python validate_test_setup.py
```

This will check:
- ✓ Python version (3.8+)
- ✓ Required test dependencies
- ✓ Project structure
- ✓ Test files
- ✓ Source modules
- ✓ Pytest configuration

### 3. Run Tests

**Windows (Quick):**
```bash
test all           # Run all tests with coverage
test quick         # Fast run, no coverage
test unit          # Unit tests only
test cov           # Run tests and open coverage report
```

**Cross-platform:**
```bash
python run_tests.py              # Run all tests
python run_tests.py --quick      # Quick run
python run_tests.py -m unit      # Unit tests only
python run_tests.py -vv          # Verbose output
```

## Test Suite Overview

### What's Included

The test suite includes comprehensive unit tests for all MVP Week 2 components:

| Module | Test File | Test Classes | Coverage Target |
|--------|-----------|--------------|-----------------|
| normalize_transcript.py | test_normalize_transcript.py | 5 classes, 31 tests | 90%+ |
| segment_and_chunk.py | test_segment_and_chunk.py | 3 classes, 18 tests | 90%+ |
| retrieve_evidence.py | test_retrieve_evidence.py | 5 classes, 26 tests | 90%+ |
| human_review_gate.py | test_human_review_gate.py | 4 classes, 23 tests | 90%+ |
| workflow_engine.py | test_workflow_engine.py | 2 classes, 28 tests | 80%+ |
| patient_service.py | test_patient_service.py | 2 classes, 26 tests | 90%+ |
| **Total** | **6 test files** | **21 test classes** | **70%+ overall** |

### Test Features

✓ **152 comprehensive unit tests**
✓ **Shared fixtures for consistent test data**
✓ **Coverage reporting (HTML, XML, terminal)**
✓ **Parallel execution support**
✓ **Test markers for selective execution**
✓ **Database tests with in-memory SQLite**
✓ **Async test support**
✓ **Mock support for external dependencies**

## Test Structure

```
server/
├── tests/
│   ├── conftest.py                    # 300+ lines of shared fixtures
│   ├── README.md                      # Detailed test documentation
│   ├── unit/
│   │   ├── test_normalize_transcript.py    (285 lines, 31 tests)
│   │   ├── test_segment_and_chunk.py       (252 lines, 18 tests)
│   │   ├── test_retrieve_evidence.py       (305 lines, 26 tests)
│   │   ├── test_human_review_gate.py       (281 lines, 23 tests)
│   │   ├── test_workflow_engine.py         (329 lines, 28 tests)
│   │   └── test_patient_service.py         (377 lines, 26 tests)
│   └── integration/                   # Future integration tests
├── pytest.ini                         # Pytest configuration
├── run_tests.py                       # Main test runner (250 lines)
├── test.bat                           # Windows quick runner
├── validate_test_setup.py             # Setup validation script
└── TESTING_GUIDE.md                   # This file
```

## Common Test Commands

### Basic Testing

```bash
# Run all tests
python run_tests.py

# Run specific test file
python run_tests.py tests/unit/test_normalize_transcript.py

# Run specific test class
python run_tests.py tests/unit/test_normalize_transcript.py::TestNormalizeTimestamp

# Run specific test
python run_tests.py tests/unit/test_normalize_transcript.py::TestNormalizeTimestamp::test_normalize_float_timestamp
```

### Filtering Tests

```bash
# Run tests by marker
python run_tests.py -m unit
python run_tests.py -m db
python run_tests.py -m "unit and not db"

# Run tests matching keyword
python run_tests.py -k "normalize"
python run_tests.py -k "timestamp or speaker"

# Skip slow tests
python run_tests.py -m "not slow"
```

### Debugging Tests

```bash
# High verbosity
python run_tests.py -vvv

# Stop on first failure
python run_tests.py --failfast

# Drop into debugger on failure
python run_tests.py --pdb

# Re-run only failed tests
python run_tests.py --lf

# Run failed tests first, then others
python run_tests.py --ff

# Show 10 slowest tests
python run_tests.py --duration=10
```

### Coverage Reports

```bash
# Run with HTML coverage report
python run_tests.py --cov-report=html

# Open coverage report
start htmlcov\index.html         # Windows
open htmlcov/index.html          # Mac/Linux

# XML coverage for CI
python run_tests.py --cov-report=xml

# Terminal-only coverage
python run_tests.py --cov-report=term
```

### Performance

```bash
# Run in parallel (requires pytest-xdist)
pip install pytest-xdist
python run_tests.py --parallel

# Quick run (no coverage, skip slow tests)
python run_tests.py --quick
```

## Test Fixtures

The test suite provides comprehensive fixtures in `conftest.py`:

### Database Fixtures

```python
def test_with_database(db_session, sample_patient):
    """Example using database fixtures."""
    # db_session is an in-memory SQLite session
    # sample_patient is a pre-created patient record
    patient = db_session.query(Patient).filter_by(id=sample_patient.id).first()
    assert patient is not None
```

Available database fixtures:
- `test_engine` - In-memory SQLite engine
- `db_session` - Auto-rollback database session
- `sample_patient` - Sample patient (id=PAT001, mrn=MRN123456)
- `sample_user` - Sample doctor user
- `sample_medical_record` - Sample medical record

### State Fixtures

```python
def test_with_state(minimal_graph_state, sample_chunks):
    """Example using state fixtures."""
    state = minimal_graph_state.copy()
    state["chunks"] = sample_chunks
    # Test your node function
    result = my_node_function(state)
    assert "expected_field" in result
```

Available state fixtures:
- `minimal_graph_state` - Minimal LangGraph state
- `complete_graph_state` - Fully populated state
- `sample_transcript_segment` - Single segment
- `sample_transcript_segments` - Multiple segments
- `sample_chunk_artifact` - Single chunk
- `sample_chunks` - Multiple chunks
- `sample_candidate_fact` - Single fact
- `sample_candidate_facts` - Multiple facts

### Report Fixtures

```python
def test_validation(validation_report_with_errors):
    """Example using report fixtures."""
    # Pre-configured validation report with errors
    needs_review, reasons = check_validation_issues(validation_report_with_errors)
    assert needs_review is True
```

Available report fixtures:
- `validation_report_with_errors` - Report with schema errors, missing fields
- `validation_report_clean` - Clean report, no issues
- `conflict_report_with_conflicts` - Report with unresolved conflicts
- `conflict_report_clean` - Clean conflict report

## Writing New Tests

### Basic Test Template

```python
"""
Unit tests for my_module.py
"""

import pytest
from app.agents.my_module import my_function


class TestMyFunction:
    """Tests for my_function."""

    def test_basic_functionality(self):
        """Test basic case."""
        result = my_function("input")
        assert result == "expected"

    def test_edge_case(self):
        """Test edge case."""
        result = my_function("")
        assert result is not None


@pytest.mark.unit
class TestMyNode:
    """Tests for my_module_node."""

    def test_with_state(self, minimal_graph_state):
        """Test node with minimal state."""
        state = minimal_graph_state.copy()
        result = my_node_function(state)

        assert "new_field" in result
        assert result["controls"]["trace_log"][-1]["node"] == "my_node"
```

### Best Practices

1. **One test, one assertion**: Each test should verify one specific behavior
2. **Descriptive names**: `test_merge_removes_duplicates` not `test_merge`
3. **Use fixtures**: Leverage shared fixtures instead of duplicating setup
4. **Test edge cases**: Empty inputs, None values, boundary conditions
5. **Add docstrings**: Document what each test verifies
6. **Mock externals**: Mock LLM calls, API calls, file I/O
7. **Mark appropriately**: Use `@pytest.mark.unit`, `@pytest.mark.db`, etc.

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: |
          cd server
          pip install -r requirements.txt
      - name: Validate setup
        run: python validate_test_setup.py
      - name: Run tests
        run: python run_tests.py --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

### Local Pre-commit Hook

Add to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
cd server
python run_tests.py --quick
if [ $? -ne 0 ]; then
    echo "Tests failed. Commit aborted."
    exit 1
fi
```

## Troubleshooting

### Issue: Tests not found

**Solution:**
```bash
# Ensure you're in server directory
cd server

# Check pytest can collect tests
pytest --collect-only tests/

# Set PYTHONPATH if needed
set PYTHONPATH=.    # Windows
export PYTHONPATH=. # Linux/Mac
```

### Issue: Import errors

**Solution:**
```bash
# Install all test dependencies
pip install pytest pytest-asyncio pytest-cov pytest-mock faker

# Or install from requirements
pip install -r requirements.txt
```

### Issue: Database connection errors

**Solution:**
Tests use in-memory SQLite by default. If you see PostgreSQL errors, check that your `.env` file is not being loaded during tests, or update the database URL for testing.

### Issue: Slow test execution

**Solution:**
```bash
# Skip slow tests
python run_tests.py -m "not slow"

# Run in parallel
pip install pytest-xdist
python run_tests.py --parallel

# Use quick mode
python run_tests.py --quick
```

### Issue: Coverage too low

**Solution:**
```bash
# See which files need more tests
python run_tests.py --cov-report=term-missing

# Open HTML report to see line-by-line coverage
python run_tests.py --cov-report=html
start htmlcov\index.html
```

## Next Steps

After MVP Week 2 testing:

- [ ] Add integration tests for end-to-end workflow execution
- [ ] Add tests for clinical suggestions (MVP Week 3)
- [ ] Add tests for record generation templates
- [ ] Add API endpoint tests
- [ ] Add performance/load tests
- [ ] Set up CI/CD with automated testing
- [ ] Achieve 80%+ overall code coverage

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest Coverage Plugin](https://pytest-cov.readthedocs.io/)
- [Python Testing Best Practices](https://docs.python-guide.org/writing/tests/)
- [Test Fixtures Guide](https://docs.pytest.org/en/stable/fixture.html)
- [Mocking in Python](https://docs.python.org/3/library/unittest.mock.html)

## Getting Help

If you encounter issues:

1. Run validation: `python validate_test_setup.py`
2. Check test output with high verbosity: `python run_tests.py -vvv`
3. Review test documentation: `tests/README.md`
4. Check individual test file docstrings for examples
