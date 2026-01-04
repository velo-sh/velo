# Phase 6.1 Test Matrix: Velo Serve & Analyze

> **Status**: DRAFT
> **Owner**: QA Working Group
> **Date**: 2026-01-04

---

## 1. Testing Strategy (First Principles)

### 1.1 The "Hook" (Core Value)
Phase 6.1 is about **Developer Experience (DX)** and **Process Safety**.
- **Serve**: Must be "Zero Config" (AST Detection) and "Zombie Free" (RAII).
- **Analyze**: Must be "Actionable" (Savings Report).

### 1.2 Risk Assessment

| Risk | Impact | Mitigation |
|:---|:---|:---|
| **Zombie Processes** | High (Resource Leaks) | **L2-RAII**: Brutal kill tests (SIGKILL/panic). |
| **Logic Bombs** | Medium (User Frustration) | **L1-AST**: Compliance suite for App Detection. |
| **Security Bypass** | Critical (RCE) | **L4-SEC**: P0 Invariants (TOCTOU, Injection). |

---

## 2. Tiered Test Coverage (L0 - L5)

### L0: Smoke (Binary Health)
- **L0-1**: `velo serve --help` returns 0.
- **L0-2**: `velo analyze --help` returns 0.
- **L0-3**: `velo serve` without args hints at missing app (does not crash).

### L1: Feature (Functional Correctness)
- **L1-AST**: `detect_app.py` correctly identifies Flask/Django/FastAPI.
- **L1-BIND**: `--bind` and `--timeout` flags are respected.
- **L1-LOG**: `--log-level` changes output verbosity.

### L2: Stability (Edge Cases)
- **L2-RAII**: Worker process dies when Parent is `kill -9`'d (Orphan check).
- **L2-RELOAD**: Debouncer ignores rapid bursts (300ms window).
- **L2-ZOMBIE**: 100 fast restarts do not leave zombie processes.

### L3: Stress (Resilience)
- **L3-FLOOD**: 10k connections/sec doesn't crash the supervisor.
- **L3-LONG**: 24h stability run (simulated).

### L4: Security (Invariants)
- **SEC-P0-001**: Command Injection Prevention (via `validate_app_target`).
- **SEC-P0-002**: Path Traversal Protection (via `validate_scan_path`).
- **SEC-P0-003**: Safe PID File Creation (O_EXCL).
- **SEC-P0-004**: Minimal Health Response (No Metadata).
- **SEC-P0-005**: Environment Sanitization (Strip PYTHONPATH).
- **SEC-P0-006**: Watcher Rate Limiting (DOS Prevention).

### L5: Integration (Platform Matrix)
- **MAC-P0-001**: MacOS FSEvents Latency Config.
- **MAC-P0-002**: Signal Handler Reset (Zombie Prev).
- **LNX-P0-001**: Inotify Watch Limit Check.
- **LNX-P0-002**: Container Detection (Poll Fallback).
- **CN-P0-001**: Health Check Endpoint (`/healthz`).


---

## 3. Agent Assignments

- **Agent A (Edge)**: L2-RELOAD, L3-FLOOD, L1-AST (Complex factories).
- **Agent B (Stability)**: L2-RAII, L2-ZOMBIE, L5-E2E.
- **Agent C (Security)**: L4-SEC (All P0 invariants).

---
