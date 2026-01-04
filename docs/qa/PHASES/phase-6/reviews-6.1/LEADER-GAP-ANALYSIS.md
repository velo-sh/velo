# Phase 6.1 QA Leader Critique Report

> **Reviewer**: QA Leader  
> **Date**: 2026-01-04  
> **Subject**: Gap Analysis - Multi-Agent Test Design vs RFC-0010 Spec

---

## Executive Summary

After cross-referencing the multi-agent test design against RFC-0010's 15 expert review findings, I've identified **12 missing test areas**. These gaps must be addressed before approving the test design.

**Current Status**: ⚠️ **REQUIRES REVISION**

---

## Gap Analysis

### 🔴 P0 - Critical Gaps (Missing Security/Core Tests)

| Gap ID | RFC Section | Missing Test | Agent |
|--------|-------------|--------------|-------|
| **GAP-01** | §3.3 Expert Review | ASGI Lifespan protocol (`shutdown` event) | B |
| **GAP-02** | §3.3 Config Precedence | Gunicorn `--config` override via CLI | B |
| **GAP-03** | §3.3 RAII Safety | `ManagedChild::Drop` during panic | C/Leader |
| **GAP-04** | §3.3 Environment | LD_LIBRARY_PATH sanitization | C |

### 🟡 P1 - High Priority Gaps (Missing Platform/UX Tests)

| Gap ID | RFC Section | Missing Test | Agent |
|--------|-------------|--------------|-------|
| **GAP-05** | §3.3 Platform | macOS FSEvents low-latency (0.1s) | B |
| **GAP-06** | §3.3 Platform | Linux inotify `max_user_watches` warning | B |
| **GAP-07** | §3.3 Platform | Docker container polling fallback | B |
| **GAP-08** | §3.3 Graceful | 30s drain timeout before force-kill | B |

### 🔵 P2 - Medium Priority Gaps (Missing DX/Polish Tests)

| Gap ID | RFC Section | Missing Test | Agent |
|--------|-------------|--------------|-------|
| **GAP-09** | §3.3 DX | Source-pointing diagnostics (line:col) | A |
| **GAP-10** | §3.3 DX | Typo suggestions (`--relod` → `--reload`) | A |
| **GAP-11** | §3.3 A11y | `NO_COLOR` environment variable | A/B |
| **GAP-12** | §3.3 A11y | ASCII fallback for non-unicode terminals | A/B |

---

## Detailed Findings

### GAP-01: ASGI Lifespan Protocol
> **RFC Reference**: "Mandated **ASGI Lifespan protocol** support (waiting for shutdown events)"

**Current**: No test for `lifespan` startup/shutdown hooks.  
**Required**: Verify `velo serve` properly waits for `shutdown` lifespan event.

```python
# Missing test case
def test_CORE_61_011_asgi_lifespan_shutdown():
    """Verify shutdown waits for lifespan event."""
    app_code = '''
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app):
    print("STARTUP")
    yield
    print("SHUTDOWN")  # This MUST be reached on graceful shutdown

app = FastAPI(lifespan=lifespan)
'''
```

### GAP-02: Gunicorn Config Override
> **RFC Reference**: "CLI flags MUST explicitly override settings in `gunicorn.conf.py`"

**Current**: No test for config precedence.  
**Required**: Verify `--workers 2` overrides `workers = 4` in gunicorn.conf.py.

### GAP-03: RAII Panic Safety
> **RFC Reference**: "Verified that `ManagedChild` (RAII) correctly kills subprocesses during Rust panic stack unwinding"

**Current**: MEGA-61-003 exists but not explicit about panic path.  
**Required**: Explicit test using `panic!()` trigger and verifying port is freed.

### GAP-05/06/07: Platform-Specific Tests
> **RFC Reference**: "macOS low-latency FSEvents, Linux inotify limit detection, and Docker polling fallback"

**Current**: No platform-specific tests.  
**Required**: Conditional tests marked with `@pytest.mark.skipif(sys.platform != ...)`

### GAP-09/10: DX Excellence
> **RFC Reference**: "source-pointing diagnostics", "Level 2 typo suggestions"

**Current**: No tests for error message quality.  
**Required**: Verify error messages contain line:column and actionable suggestions.

### GAP-11/12: Accessibility
> **RFC Reference**: "Multi-modal Status Indicators (text + color) and ASCII fallbacks"

**Current**: No accessibility tests.  
**Required**: Tests with `NO_COLOR=1` and `TERM=dumb`.

---

## Recommended Test Additions

### Agent A (Edge) - Add 3 Tests

| ID | Test Case | Description |
|----|-----------|-------------|
| EDGE-61-DX-001 | Typo suggestions | `--relod` → "Did you mean `--reload`?" |
| EDGE-61-DX-002 | Source-pointing error | Error shows `main.py:42:10` |
| EDGE-61-A11Y-001 | ASCII-only terminal | `TERM=dumb` produces valid output |

### Agent B (Stability) - Add 6 Tests

| ID | Test Case | Description |
|----|-----------|-------------|
| CORE-61-011 | ASGI lifespan shutdown | Shutdown waits for lifespan |
| CORE-61-012 | Gunicorn config override | CLI > gunicorn.conf.py |
| CORE-61-013 | 30s drain timeout | Graceful shutdown timer |
| PLAT-61-001 | macOS FSEvents latency | <0.1s detection verified |
| PLAT-61-002 | Linux inotify warning | Low `max_user_watches` warning |
| PLAT-61-003 | Docker polling fallback | inotify fails → polling mode |

### Agent C (Security) - Add 1 Test

| ID | Test Case | Description |
|----|-----------|-------------|
| SEC-61-ENV-004 | LD_LIBRARY_PATH sanitized | No library injection |

### Leader (Brutal) - Add 2 Tests

| ID | Test Case | Description |
|----|-----------|-------------|
| A11Y-61-001 | NO_COLOR support | No ANSI escapes when set |
| A11Y-61-002 | Text+icon multimodal | Success uses both icon and text |

---

## Revised Test Count

| Agent | Current | Added | New Total |
|-------|---------|-------|-----------|
| Agent A (Edge) | 18 | +3 | **21** |
| Agent B (Stability) | 17 | +6 | **23** |
| Agent C (Security) | 17 | +1 | **18** |
| Leader (Brutal) | 8 | +2 | **10** |
| **Total** | 60 | +12 | **72** |

---

## Cross-Review Assignments

Per RFC-0006/RFC-0009 protocol:

| Gap | Primary Agent | Cross-Review By |
|-----|---------------|-----------------|
| GAP-01~04 (P0) | B+C | A + Leader |
| GAP-05~08 (P1) | B | A + C |
| GAP-09~12 (P2) | A | B + C |

---

## Leader Decision

**Status**: ⏳ **PENDING UPDATE**

The multi-agent test design requires updating with the 12 missing tests before final approval. After update:
- [ ] Agent A acknowledges DX/A11y additions
- [ ] Agent B acknowledges Platform/Lifespan additions
- [ ] Agent C acknowledges ENV sanitization addition
- [ ] Leader signs off on Brutal additions

---

**Signed**: QA Leader  
**Date**: 2026-01-04
