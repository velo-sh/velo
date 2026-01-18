# DEF-13-004: Test Result Not Communicated to pytest

**Priority:** P0 CRITICAL
**Status:** OPEN
**Reporter:** QA Leader
**Assignee:** Developer

## Summary
`pytest_runtest_protocol` runs tests in fork but doesn't report pass/fail to pytest.

## Reproduction
```python
# When --velo is enabled, pytest_runtest_protocol:
# 1. Runs test in fork
# 2. Gets pass/fail from exit code
# 3. Returns True
# 
# BUT: pytest expects a TestReport, not just True/False
# The test outcome is LOST.
```

## Expected Behavior
pytest should show:
- `PASSED` for successful tests
- `FAILED` for failed tests with proper tracebacks

## Actual Behavior
- `pytest_runtest_protocol` returns `True` 
- pytest sees this as "handled" but has no result
- Test appears to "pass" even when it fails internally

## Code Location
`plugin.py` lines 307-312:
```python
success = run_in_zygote_fork(item)
return True  # BUG: pytest doesn't know if passed or failed!
```

## Impact
- **CRITICAL**: All tests appear to pass regardless of actual outcome
- Test failures are hidden
- CI gives false confidence

## Suggested Fix
Use `pytest_runtest_call` hook instead and properly report results:
```python
from _pytest.runner import CallInfo, pytest_runtest_makereport

# Create proper TestReport with outcome
```

---
**QA Signature:** QA Leader
