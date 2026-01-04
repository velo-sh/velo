# Phase 6.1: Requirement-to-Test Mapping (RTM)

**Status**: 🟢 DESIGN READY
**Leader**: Velo QA Working Group
**Reference**: [ARCH-ALIGNMENT-6.1.md](file:///Users/gjwang/eclipse-workspace/rust_source/velo_qa/docs/qa/PHASES/phase-6.1/reviews/ARCH-ALIGNMENT-6.1.md)

---

## 1. Technical Mandates Mapping

| Req ID | Category | Requirement | Test Case ID | Test Suite |
|:---|:---|:---|:---|:---|
| **ENG-P0-001** | Architecture | Managed Subprocess Model | `T-STAB-RS-001` | `test_phase6_1_stability_hardened.py` |
| **ENG-P0-002** | Stability | 300ms Watcher Debounce | `T-STAB-RS-002` | `test_phase6_1_stability_hardened.py` |
| **MAC-P0-001** | Platform | macOS FSEvents 100ms Latency | `T-PLAT-MAC-001` | `test_phase6_1_stability_hardened.py` |
| **MAC-P0-002** | Platform | macOS Signal Reset in Fork | `T-PLAT-MAC-002` | `test_phase6_1_stability_hardened.py` |
| **LNX-P0-001** | Platform | Linux inotify Limit Warning | `T-PLAT-LNX-001` | `test_phase6_1_stability_hardened.py` |
| **LNX-P0-002** | Platform | Container Polling Fallback | `T-PLAT-LNX-002` | `test_phase6_1_stability_hardened.py` |
| **CN-P0-001** | Cloud | Health `/healthz` & `/readyz` | `T-SEC-CN-001` | `test_phase6_1_security_hardened.py` |
| **CN-P0-002** | Cloud | SIGTERM Forwarding (30s) | `T-STAB-CN-002` | `test_phase6_1_stability_hardened.py` |
| **CN-P0-003** | Cloud | JSON Structured Logging | `T-DX-CN-003` | `test_phase6_1_dx_hardened.py` |
| **DO-P0-001** | DevOps | PID File Safety (O_EXCL) | `T-SEC-DO-001` | `test_phase6_1_security_hardened.py` |
| **PY-P0-001** | Python | ASGI Lifespan Shutdown | `T-STAB-PY-001` | `test_phase6_1_stability_hardened.py` |
| **PY-P0-004** | Python | Fresh Process Guarantee | `T-STAB-PY-004` | `test_phase6_1_stability_hardened.py` |
| **RS-P0-003** | Rust | RAII Child Cleanup (Drop) | `T-STAB-RS-003` | `test_phase6_1_stability_hardened.py` |

## 2. Security "Red Lines" Mapping

| Req ID | Category | Requirement | Test Case ID | Test Suite |
|:---|:---|:---|:---|:---|
| **SEC-P0-001** | Security | Command Injection Reject | `T-SEC-P0-001` | `test_phase6_1_security_hardened.py` |
| **SEC-P0-002** | Security | Path Traversal Protection | `T-SEC-P0-002` | `test_phase6_1_security_hardened.py` |
| **SEC-P0-003** | Security | safe PID File Creation | `T-SEC-P0-003` | `test_phase6_1_security_hardened.py` |
| **SEC-P0-004** | Security | Minimal Health Response | `T-SEC-P0-004` | `test_phase6_1_security_hardened.py` |
| **SEC-P0-005** | Security | Environment Sanitization | `T-SEC-P0-005` | `test_phase6_1_security_hardened.py` |
| **SEC-P0-006** | Security | Watcher Rate Limiting | `T-SEC-P0-006` | `test_phase6_1_security_hardened.py` |

## 3. Performance & DX Invariants

| Req ID | Category | Requirement | Test Case ID | Test Suite |
|:---|:---|:---|:---|:---|
| **PERF-01** | Perf | Hot Restart < 50ms | `T-PERF-01` | `test_phase6_1_performance_hardened.py` |
| **PERF-02** | Perf | Memory Overhead < 50MB | `T-PERF-02` | `test_phase6_1_performance_hardened.py` |
| **PERF-03** | Perf | FD Count Stability (no leaks) | `T-PERF-03` | `test_phase6_1_performance_hardened.py` |
| **DX-01** | DX | Source-Pointing Errors (`-->`) | `T-DX-01` | `test_phase6_1_dx_hardened.py` |
| **DX-02** | DX | Typo Suggestions (stsim) | `T-DX-02` | `test_phase6_1_dx_hardened.py` |

---
**QA Verdict**: 🟢 Design Complete. Proceeding to Implementation.
