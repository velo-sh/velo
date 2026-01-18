# DEF-13-006: --velo Flag Not Registered as pytest Plugin

**Priority:** P0 CRITICAL
**Status:** OPEN
**Reporter:** QA Leader
**Assignee:** Developer

## Summary
The `--velo` command line option is not available when running `pytest --velo`.

## Reproduction
```bash
$ python -m pytest test_example.py --velo
ERROR: usage: __main__.py [options] [file_or_dir] [file_or_dir] [...]
__main__.py: error: unrecognized arguments: --velo
```

## Expected Behavior
Per RFC-0028 Section 5 Interface:
```bash
pytest tests/ --velo  # Should work as drop-in enhancement
```

## Actual Behavior
pytest does not recognize `--velo` because the plugin is not installed/registered.

## Root Cause
`pytest_velo` plugin is not registered as a pytest entry point.

**Missing in `pyproject.toml` or `setup.py`:**
```toml
[project.entry-points."pytest11"]
velo = "pytest_velo.plugin"
```

## Impact
- **CRITICAL**: Core feature of RFC-0028 is non-functional
- "Drop-in enhancement" claim is FALSE
- Users cannot use `--velo` flag

## RFC Reference
RFC-0028 Section 5:
> "pytest tests/ --velo"

---
**QA Signature:** QA Leader
