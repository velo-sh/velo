# Phase 7.2 Native Sovereignty - Prosecutor Suite Report

> **Generated**: 2026-01-14 12:12 CST  
> **Environment**: macOS (Apple Silicon), Velo v1.0 (Phase 7.2)  
> **Commit**: `998d6e5` (origin/phase-7.2/native-sovereignty)  
> **QA Agent**: Forensic AI (ID-LOCK-GLOBAL Compliant)

---

## 📊 Executive Summary

| Metric | Value |
|:---|:---|
| **Total Tests** | 19 |
| **Passed** | 14 ✅ |
| **Failed** | 5 ❌ |
| **Pass Rate** | 73.7% |

---

## 🚀 Reproduction Commands

```bash
# Full Suite (19 tests, ~7 minutes)
uv run pytest tests/qa/phase_7_2/test_framework_compatibility.py tests/qa/phase_7_2/test_rsgi_remediation.py -v -s

# Quick Smoke Test (Core P0 only)
uv run pytest tests/qa/phase_7_2/test_rsgi_remediation.py -v -s -k "query_string or shadowing"

# Run ONLY failing tests
uv run pytest tests/qa/phase_7_2/test_framework_compatibility.py tests/qa/phase_7_2/test_rsgi_remediation.py -v -s -k "sovereignty or websocket or signal or zombie"
```

---

## ✅ Passing Tests (14)

| Test | Category | Status |
|:---|:---|:---|
| `test_query_string_preservation` | Protocol | ✅ PASS |
| `test_dependency_shadowing_protection` | Security | ✅ PASS |
| `test_wsgi_expected_failure` | Compatibility | ✅ PASS |
| `test_streaming_basic` | Protocol | ✅ PASS |
| `test_explicit_uvicorn_lockdown` | Security | ✅ PASS |
| `test_hostile_blocking_app` | Robustness | ✅ PASS |
| `test_starlette_scope_integrity` | Protocol | ✅ PASS |
| `test_hard_exit_recovery` | Robustness | ✅ PASS |
| `test_internal_shadowing_defense` | Security | ✅ PASS |
| `test_infinite_hang_isolation` | Robustness | ✅ PASS |
| `test_sse_streaming_sovereignty` | Protocol | ✅ PASS |
| `test_global_state_isolation` | Isolation | ✅ PASS |
| `test_middleware_scope_interceptor` | Protocol | ✅ PASS |
| `test_websocket_501_unsupported` | Protocol | ✅ PASS |

---

## ❌ Failing Tests (5)

### 1. `test_fastapi_asgi_sovereignty` (DEF-72-REG)

**File**: `tests/qa/phase_7_2/test_framework_compatibility.py`  
**Category**: Architectural Sovereignty  
**Priority**: P0

**Error**:
```
AssertionError: ARCHITECTURAL FAILURE: Uvicorn was imported by the worker!
assert True is False
```

**Root Cause**:  
`worker_launcher.py` 强制预加载 `uvicorn` 以防止 Shadowing，违反了 Native Sovereignty 原则。

**Verification Logic**:
```python
# The test checks if 'uvicorn' is in sys.modules
data = response.json()
assert data["uvicorn_shadow"] is False, "ARCHITECTURAL FAILURE: Uvicorn was imported by the worker!"
```

---

### 2. `test_websocket_echo_sovereignty` (DEF-72-C04)

**File**: `tests/qa/phase_7_2/test_framework_compatibility.py`  
**Category**: Protocol  
**Priority**: P1

**Error**:
```
websocket._exceptions.WebSocketBadStatusException: Handshake status 501 Not Implemented
```

**Root Cause**:  
RSGI Host 目前主动拒绝 WebSocket 握手（返回 501），但测试期望完整的 WS Echo 功能。

**Note**: 这是一个预期行为 vs 期望差异。如果 RSGI 路线图明确不支持 WS，此测试应改为期望 501。

---

### 3. `test_signal_hijacking_resilience` (DEF-72-C06)

**File**: `tests/qa/phase_7_2/test_framework_compatibility.py`  
**Category**: Process Lifecycle  
**Priority**: P1

**Error**:
```
subprocess.TimeoutExpired: Command '[...velo serve...--port 49214]' timed out after 10 seconds
```

**Root Cause**:  
当用户 App 劫持 `SIGINT`/`SIGTERM` 时，Host 无法通过正常信号终止 Worker。需要 `SIGKILL` 回退机制。

---

### 4. `test_native_sovereignty_uvicorn_absence` (DEF-72-REG)

**File**: `tests/qa/phase_7_2/test_rsgi_remediation.py`  
**Category**: Architectural Sovereignty  
**Priority**: P0

**Error**:
```
AssertionError: SOVEREIGNTY VIOLATION: uvicorn pre-loaded in RSGI mode! Response: UVICORN_LOADED:True
```

**Root Cause**:  
与 `test_fastapi_asgi_sovereignty` 相同。`worker_launcher.py` 中的预导入逻辑。

---

### 5. `test_signal_zombie_cleanup` (DEF-72-C06)

**File**: `tests/qa/phase_7_2/test_rsgi_remediation.py`  
**Category**: Process Lifecycle  
**Priority**: P1

**Error**:
```
AssertionError: ZOMBIE PERSISTENCE (C06): Workers [{'pid': 92904, 'status': 'running', 'ppid': 1, ...}] still alive after Host shutdown!
```

**Root Cause**:  
Host 关闭后，Worker 进程变为孤儿进程 (`ppid=1`)。需要进程组级 `SIGKILL` 清理。

**Forensic Evidence**:
```python
survivors = [
    {'pid': 92904, 'status': 'running', 'ppid': 1, 'name': 'python3.11', ...}
]
```

---

## 🔧 Recommended Fixes

| Defect | Fix Strategy |
|:---|:---|
| **DEF-72-REG** (Uvicorn Shadow) | 重构 `worker_launcher.py`：使用 `importlib` 延迟加载或隔离 `msgpack` 防护逻辑，避免预导入 `uvicorn`。 |
| **DEF-72-C04** (WebSocket) | 要么：1) 实现 WS RSGI 桥接；或 2) 更新测试为期望 501。 |
| **DEF-72-C06** (Zombie) | 在 `src/serve/runner.rs` 或 Python Zygote 中实现 `kill(-pgid, SIGKILL)` 回退。 |

---

## 📁 Test Files Location

```
tests/qa/phase_7_2/
├── test_framework_compatibility.py  # 14 scenarios (Prosecutor Suite)
├── test_rsgi_remediation.py         # 5 scenarios (Remediation Verification)
└── test_sovereignty_forensics.py    # 4 scenarios (White-box Forensics)
```

---

## 📞 Contact

For questions about this report, refer to the QA walkthrough:  
`docs/qa/walkthrough.md` (or Gemini artifact at `brain/<conversation-id>/walkthrough.md`)
