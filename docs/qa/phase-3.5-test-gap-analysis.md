# Phase 3.5 Test Gap Analysis

> Audit based on QA First Principles
> Date: 2026-01-02

---

## Feature Inventory: What `velo serve` Should Do

| Category | Feature | Level | Tested? | Gap? |
|----------|---------|-------|---------|------|
| **Core** | Server starts | L0 | ❌ | **CRITICAL GAP** |
| **Core** | Server binds to port | L0 | ❌ | **CRITICAL GAP** |
| **Core** | Server responds to HTTP | L1 | ❌ | **CRITICAL GAP** |
| **Core** | Server handles multiple requests | L1 | ❌ | GAP |
| **Core** | Graceful shutdown | L1 | ❌ | GAP |
| **Config** | --port option | L2 | Partial | CLI tested, actual port binding NOT tested |
| **Config** | --workers option | L2 | Partial | CLI tested, actual workers NOT tested |
| **Config** | --host option | L2 | ❌ | GAP |
| **Config** | --reload option | L2 | ❌ | GAP (if exists) |
| **Error** | Module not found | L2 | ✅ | OK |
| **Error** | App not found | L2 | ✅ | OK |
| **Error** | Syntax error in app | L2 | ❌ | GAP |
| **Error** | App crashes on import | L2 | ❌ | GAP |
| **Error** | Port already in use | L2 | ❌ | GAP |
| **Error** | Permission denied (port < 1024) | L2 | ✅ | Partial |
| **Lifecycle** | SIGTERM -> graceful shutdown | L3 | ❌ | GAP |
| **Lifecycle** | SIGINT -> graceful shutdown | L3 | ❌ | GAP |
| **Lifecycle** | Worker auto-restart on crash | L3 | ❌ | GAP |
| **Lifecycle** | No zombie processes | L3 | ❌ | GAP |
| **Lifecycle** | No orphan workers | L3 | ❌ | GAP |
| **Integration** | Zygote used for fast start | L3 | ❌ | GAP |
| **Integration** | Framework detection correct | L3 | ❌ | GAP |
| **Performance** | Startup time < N seconds | L4 | ❌ | GAP |
| **Performance** | Memory usage reasonable | L4 | ❌ | GAP |
| **Performance** | Request latency vs uvicorn | L4 | ❌ | GAP |

---

## Analysis by Agent

### Agent A (Edge Cases)
**Problem**: Tested edge cases before verifying happy path exists
**Missing**:
- Edge cases on OPTIONS that don't work yet (--workers, --host)
- Edge cases on FEATURES that don't work yet (reload, multiple workers)

### Agent B (Stability)
**Problem**: Tested CLI parsing, not actual functionality
**Fixed**: Rewrote with L0-L3 hierarchy
**Still Missing**:
- Concurrent request handling stability
- Long-running server stability
- Memory leak detection over time

### Agent C (Security) 
**Problem**: Security tests assume server runs - it doesn't!
**Missing**:
- These tests are BLOCKED until L0 passes
- Network security tests need actual running server

### Agent D (Destroyer)
**Problem**: Only agent that tested real functionality
**Missing**:
- More destructive tests on request handling
- Stress tests under load

---

## Priority Test Additions

### P0 (Must Have - Blocked on Dev Fix)

These tests define "done" for Phase 3.5:

```python
# L0 Smoke (blocking)
def test_server_actually_starts():
    """Server binds to port and accepts connections"""

def test_server_responds_to_http():
    """GET / returns 200"""

# L1 Happy Path (blocking)
def test_start_request_stop_cycle():
    """Complete user journey"""

def test_100_requests_no_error():
    """Basic load handling"""

def test_graceful_shutdown():
    """SIGTERM -> connections drained -> exit 0"""
```

### P1 (Should Have)

```python
# L2 Config validation
def test_port_option_actually_changes_port():
    """Not just parsing, actual binding"""

def test_workers_option_spawns_multiple():
    """N workers = N processes"""

# L2 Error handling
def test_app_syntax_error_clear_message():
    """Python syntax error -> helpful error"""

def test_port_in_use_clear_message():
    """Second server -> port conflict error"""
```

### P2 (Nice to Have)

```python
# L3 Integration
def test_zygote_provides_speedup():
    """Second start faster than first"""

def test_framework_detected_correctly():
    """FastAPI -> Framework: FastAPI"""

# L4 Performance
def test_startup_under_3_seconds():
    """Not blocking, but should be fast"""
```

---

## Root Cause of Missing Tests

| Cause | Description |
|-------|-------------|
| **Assumption** | Assumed CLI tests = functionality tests |
| **Dev pressure** | "Tests pass" pressure led to testing easiest things |
| **Wrong pyramid** | Started from edge cases, not happy path |
| **Mocking trap** | Tested isolated units, not integration |

---

## Action Items

1. [ ] Create comprehensive L0/L1 tests (this file defines them)
2. [ ] Re-run Agent C/D only AFTER L0 passes
3. [ ] Add performance baseline tests
4. [ ] Add lifecycle tests (signals, workers, zombies)
5. [ ] Update defect report with full gap analysis
