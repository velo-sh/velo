# Phase 4.0 Defect Report

> **Date**: 2026-01-02  
> **Status**: QA In Progress  
> **Branch**: `phase-4.0/velo-analyze`

---

## Summary

| Total | Passed | Failed | Skipped |
|-------|--------|--------|---------|
| 43 | 37 | 5 | 1 |

---

## Defects

### DEF-4.0-001: CLI Option Syntax Issue 🟠 HIGH

**Test**: B3-2, B3-3  
**Issue**: `--slow-threshold-ms=50` treated as unknown option

```
Error: Unknown option: --slow-threshold-ms=50
```

**Expected**: Accept `--slow-threshold-ms=VALUE` syntax  
**Root Cause**: CLI parser may expect `--slow-threshold-ms 50` (space not `=`)

---

### DEF-4.0-002: /dev/null Accepted as Valid File 🟡 MEDIUM

**Test**: A1-2  
**Issue**: `velo analyze /dev/null` succeeds instead of erroring

**Expected**: Error on special files outside project  
**Actual**: Returns success with empty import table

---

### DEF-4.0-003: Null Byte Causes Python ValueError 🟡 MEDIUM

**Test**: A1-5  
**Issue**: Null byte in filename causes unhandled exception

```
ValueError: embedded null byte
```

**Expected**: Reject with user-friendly error  
**Actual**: Python exception bubbles up

---

### DEF-4.0-004: os.system() Escapes Sandbox 🔴 CRITICAL

**Test**: C2-3  
**Issue**: Analyzed code with `os.system()` actually executes

**Evidence**: `/tmp/velo_executed_marker` file was created  
**Expected**: Static analysis only, no code execution  
**Security Impact**: Arbitrary command execution

---

## Passed Tests (37)

| Category | Count | %|
|----------|-------|--|
| Core scenarios | 6 | 100% |
| Path attacks | 3/5 | 60% |
| Malformed input | 5/5 | 100% |
| Race conditions | 2/2 | 100% |
| Happy path | 4/4 | 100% |
| Output format | 3/3 | 100% |
| CLI params | 4/6 | 67% |
| Regression | 2/2 | 100% |
| File system security | 3/3 | 100% |
| Code exec safety | 1/2 | 50% |
| Info disclosure | 3/3 | 100% |
| Input validation | 2/2 | 100% |

---

## Action Items

1. [ ] **DEF-4.0-001**: Support `=` syntax for CLI args
2. [ ] **DEF-4.0-002**: Validate file is regular file in project
3. [ ] **DEF-4.0-003**: Catch null byte in filename
4. [ ] **DEF-4.0-004**: 🔴 CRITICAL - Ensure no code execution during analysis
