# Medical Transcription App - Test Suite

Comprehensive test suite for the Medical Transcription App MVP Week 2 implementation.

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── unit/                    # Unit tests
│   ├── test_normalize_transcript.py
│   ├── test_segment_and_chunk.py
│   ├── test_retrieve_evidence.py
│   ├── test_human_review_gate.py
│   ├── test_workflow_engine.py
│   └── test_patient_service.py
└── integration/             # Integration tests (future)
```

## Running Tests

### Quick Start

**Windows:**
```bash
# Run all tests
test all

# Quick test run (no coverage, skip slow tests)
test quick

# Run unit tests only
test unit

# Run tests and open coverage report
test cov

# Re-run only failed tests
test failed
```

**Cross-platform:**
```bash
# Run all tests with coverage
python run_tests.py

# Quick test run
python run_tests.py --quick

# Run specific test file
python run_tests.py tests/unit/test_normalize_transcript.py

# Run tests with specific marker
python run_tests.py -m unit

# Run with high verbosity
python run_tests.py -vv
```

### Advanced Usage

**Run specific test class:**
```bash
python run_tests.py tests/unit/test_normalize_transcript.py::TestNormalizeTimestamp
```

**Run specific test:**
```bash
python run_tests.py tests/unit/test_normalize_transcript.py::TestNormalizeTimestamp::test_normalize_float_timestamp
```

**Run tests matching keyword:**
```bash
python run_tests.py -k "normalize"
```

**Run in parallel:**
```bash
python run_tests.py --parallel
```

**Drop into debugger on failure:**
```bash
python run_tests.py --pdb
```

**Show slowest tests:**
```bash
python run_tests.py --duration=10
```

## Test Markers

Tests are organized with markers for selective execution:

- `@pytest.mark.unit` - Unit tests (fast, isolated)
- `@pytest.mark.integration` - Integration tests (slower, multi-component)
- `@pytest.mark.slow` - Slow-running tests
- `@pytest.mark.db` - Tests requiring database
- `@pytest.mark.llm` - Tests calling LLM APIs (may incur costs)

**Examples:**
```bash
# Run only unit tests
python run_tests.py -m unit

# Run only database tests
python run_tests.py -m db

# Run all except slow tests
python run_tests.py -m "not slow"

# Run unit tests excluding database tests
python run_tests.py -m "unit and not db"
```

## Coverage Reports

After running tests with coverage (default), reports are generated in multiple formats:

- **Terminal:** Summary printed after test run
- **HTML:** `htmlcov/index.html` - Open in browser for interactive report
- **XML:** `coverage.xml` - For CI/CD integration

**View HTML coverage:**
```bash
# Windows
start htmlcov\index.html

# Linux/Mac
open htmlcov/index.html
```

## Test Fixtures

Common fixtures are available in `conftest.py`:

### Database Fixtures
- `test_engine` - In-memory SQLite engine
- `db_session` - Database session (auto-rollback)
- `sample_patient` - Sample patient record
- `sample_user` - Sample user record
- `sample_medical_record` - Sample medical record

### State Fixtures
- `minimal_graph_state` - Minimal LangGraph state
- `complete_graph_state` - Fully populated state
- `sample_transcript_segment` - Single transcript segment
- `sample_transcript_segments` - Multiple segments
- `sample_chunk_artifact` - Single chunk
- `sample_chunks` - Multiple chunks
- `sample_candidate_fact` - Single candidate fact
- `sample_candidate_facts` - Multiple facts

### Report Fixtures
- `validation_report_with_errors` - Report with validation errors
- `validation_report_clean` - Clean validation report
- `conflict_report_with_conflicts` - Report with conflicts
- `conflict_report_clean` - Clean conflict report

## Writing New Tests

### Test File Structure

```python
"""
Unit tests for <module_name>.py
"""

import pytest
from app.agents.<module_name> import function_to_test


class TestFunctionName:
    """Tests for function_name."""

    def test_basic_case(self):
        """Test basic functionality."""
        result = function_to_test(input_data)
        assert result == expected_output

    def test_edge_case(self):
        """Test edge case handling."""
        # Test implementation
        pass


@pytest.mark.unit
class TestNodeFunction:
    """Tests for <module_name>_node function."""

    def test_with_minimal_state(self, minimal_graph_state):
        """Test with minimal state."""
        state = minimal_graph_state.copy()
        result = node_function(state)
        assert "expected_field" in result

    def test_updates_trace_log(self, minimal_graph_state):
        """Test that trace log is updated."""
        state = minimal_graph_state.copy()
        result = node_function(state)

        assert len(result["controls"]["trace_log"]) > 0
        assert result["controls"]["trace_log"][-1]["node"] == "node_name"
```

### Best Practices

1. **Use descriptive test names:** Test names should clearly state what is being tested
2. **One assertion per test:** Each test should verify one specific behavior
3. **Use fixtures:** Leverage shared fixtures instead of duplicating setup code
4. **Test edge cases:** Don't just test happy paths
5. **Mock external dependencies:** Use mocks for LLM calls, API calls, etc.
6. **Add docstrings:** Document what each test verifies
7. **Use markers:** Tag tests appropriately for selective execution

## Continuous Integration

For CI/CD integration, use:

```bash
# Run tests with XML coverage for CI tools
python run_tests.py --cov-report=xml

# Fail if coverage below 70%
python run_tests.py --cov-fail-under=70
```

## Troubleshooting

### Tests not found
```bash
# Ensure you're in the server directory
cd server

# Check PYTHONPATH
set PYTHONPATH=.
python run_tests.py
```

### Import errors
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov pytest-mock faker
```

### Database errors
```bash
# Tests use in-memory SQLite, no setup needed
# If PostgreSQL tests fail, check DATABASE_URL in .env
```

### Slow test runs
```bash
# Skip slow tests
python run_tests.py -m "not slow"

# Run in parallel
pip install pytest-xdist
python run_tests.py --parallel
```

## Test Coverage Goals

| Component | Current Coverage | Target |
|-----------|-----------------|--------|
| normalize_transcript | ✓ | 90%+ |
| segment_and_chunk | ✓ | 90%+ |
| retrieve_evidence | ✓ | 90%+ |
| human_review_gate | ✓ | 90%+ |
| workflow_engine | ✓ | 80%+ |
| patient_service | ✓ | 90%+ |
| **Overall** | **-** | **70%+** |

## Next Steps

After MVP Week 2 testing:

1. Add integration tests for end-to-end workflows
2. Add tests for clinical suggestions (MVP Week 3)
3. Add tests for record generation templates
4. Add performance/load tests
5. Add API endpoint tests

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [Testing best practices](https://docs.python-guide.org/writing/tests/)
