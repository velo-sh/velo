# DEF-003: Zygote Prewarming Not Working

> **Priority**: Critical  
> **Reported by**: Architect  
> **Date**: 2026-01-02  
> **Status**: OPEN

---

## Summary

Zygote mode does not provide the expected 49x speedup. Every invocation restarts the Zygote process instead of reusing a pre-warmed daemon.

---

## Expected Behavior

```bash
$ time velo run --zygote fastapi_app.py   # First: ~500ms (cold start)
$ time velo run --zygote fastapi_app.py   # Second: ~15ms (warm fork) ✅
```

---

## Actual Behavior

```bash
$ time velo run --zygote fastapi_app.py   # First: 260ms
$ time velo run --zygote fastapi_app.py   # Second: 260ms (same!) ❌

# Log shows Zygote restarts each time:
🚀 Starting Zygote...
[velo-zygote] Starting Zygote (PID: 64853)   ← New PID each time
✅ Zygote ready
[velo-zygote] Received shutdown command      ← Shuts down immediately
```

---

## Root Cause Analysis

1. **Zygote shuts down after each script** - Should stay running as daemon
2. **No preload configuration** - Heavy modules (fastapi, numpy) not pre-imported
3. **Hybrid mode not working** - Each `--zygote` call starts fresh

---

## Requirements to Fix

### REQ-1: Zygote Daemon Persistence
- `velo run --zygote` should connect to existing Zygote if running
- Zygote should remain running until `idle_timeout` (default 5 min)

### REQ-2: Module Preloading
- Zygote should pre-import modules specified in `pyproject.toml [tool.velo]`:
  ```toml
  [tool.velo]
  preload = ["fastapi", "numpy", "pandas"]
  ```
- Or use `--profile` data automatically

### REQ-3: Benchmark Script
- Create working benchmark that shows before/after comparison
- Must demonstrate <50ms warm start

---

## Acceptance Criteria

| Metric | Target |
|--------|--------|
| Second+ run with `--zygote` | < 50ms |
| Speedup vs CPython cold start | > 10x |
| Zygote process reuse | Visible via same PID |

---

## Reproduction Steps

```bash
cd /path/to/velo
echo 'import fastapi, numpy; print("OK")' > /tmp/bench.py

# Run twice
time ./target/release/velo run --zygote /tmp/bench.py
time ./target/release/velo run --zygote /tmp/bench.py

# Observe: both runs take ~260ms (should be ~15ms for second)
```

---

**Please fix and re-submit for QA verification.**
