# DEF-13-001: API Name Mismatch in Test File

**Priority:** P1
**Status:** VERIFIED
**Reporter:** QA Leader
**Assignee:** QA Leader (self-fix)

## Summary
Test file imports API functions with old names that don't exist in plugin.py.

## Reproduction
```bash
uv run pytest tests/qa/test_phase13_qa_gates.py -v
# ImportError: cannot import name 'pytest_velo_fork_reinit'
# ImportError: cannot import name 'validate_xdist_exclusivity'
```

## Expected Behavior
Tests should import and use correct API names.

## Actual Behavior
ImportError on 3 tests due to renamed functions.

## Root Cause Analysis
- `pytest_velo_fork_reinit` → renamed to `velo_fork_reinit`
- `validate_xdist_exclusivity` → renamed to `validate_xdist_compatibility`

## Fix
Commit `43cb1a5`: Updated test imports to use new API names.

---
**Verified By:** QA Leader
**Verified Commit:** 43cb1a5
**Date:** 2026-01-18
