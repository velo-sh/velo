# DEF-13-005: ZygoteServer Not Implemented

**Priority:** P0 CRITICAL
**Status:** OPEN (Known Design Gap)
**Reporter:** QA Leader
**Assignee:** Developer

## Summary
The core ZygoteServer functionality is NOT IMPLEMENTED - just a placeholder.

## Reproduction
```python
# plugin.py line 181-183:
# TODO: Start ZygoteServer here
# For now, just mark as enabled
_zygote = True  # Placeholder
```

## Expected Behavior
When `--velo` is passed:
1. Start a real ZygoteServer
2. Preload specified modules
3. Use COW forking for test isolation

## Actual Behavior
- `_zygote` is set to `True` (a boolean)
- No actual Zygote server is started
- No preloading happens
- Just does direct `os.fork()` 

## Impact
- `--velo` flag does not provide advertised Zygote acceleration
- `--velo-preload` option is completely ignored
- No performance benefit over vanilla pytest

## Note
This may be intentional during development. Mark as tracked.

---
**QA Signature:** QA Leader
