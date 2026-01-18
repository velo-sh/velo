# DEF-13-003: Silent Reinit Failure

**Priority:** P1
**Status:** OPEN
**Reporter:** QA Leader
**Assignee:** Developer

## Summary
`velo_fork_reinit()` silently swallows all exceptions from reinit callbacks.

## Reproduction
```python
from pytest_velo.plugin import register_fork_reinit, velo_fork_reinit

def failing_callback():
    raise RuntimeError("Database connection failed!")

register_fork_reinit(failing_callback)
velo_fork_reinit(None)  # No error raised, no log, completely silent
```

## Expected Behavior
Either:
1. Raise the exception so test fails visibly, OR
2. Log a WARNING so user knows reinit failed

## Actual Behavior
Exception is caught and passed (line 47-48):
```python
except Exception:
    pass  # Best-effort reinit
```

## Impact
- Database connections may silently fail to reconnect after fork
- Tests may pass with corrupted/disconnected resources
- Silent data corruption possible

## Suggested Fix
```python
except Exception as e:
    import warnings
    warnings.warn(f"velo_fork_reinit callback failed: {e}", RuntimeWarning)
```

---
**QA Signature:** QA Leader
