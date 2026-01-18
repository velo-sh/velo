# DEF-13-002: Artifact Bundling Scope

**Priority:** P1
**Status:** VERIFIED
**Reporter:** QA Leader
**Assignee:** QA Leader (self-fix)

## Summary
Artifact bundling collects entire 26GB state directory instead of current session logs.

## Reproduction
```bash
# State dir accumulated 26GB of logs
du -sh ~/.local/state/velo/
# 26G

# Any test failure triggers tar of entire dir
# tar -czf failure-bundle-*.tar.gz -C ~/.local/state/velo .
# Hangs at 86%+ CPU
```

## Expected Behavior
Bundle only logs from current test session.

## Actual Behavior
Bundles entire state directory including historical logs.

## Root Cause Analysis
`conftest.py` line 242-254 bundles `env.home / ".local/state/velo"` entirely without session scoping.

## Fix
Commit `7c880c9`: Added `session_log_directory` fixture that creates unique session dir (`session-{ts}-{uuid[:8]}`).

---
**Verified By:** QA Leader
**Verified Commit:** 7c880c9
**Date:** 2026-01-18
