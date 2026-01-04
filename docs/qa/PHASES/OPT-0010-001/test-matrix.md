# OPT-0010-001 MessagePack IPC - Test Matrix

> **RFC**: OPT-0010-001-msgpack-ipc.md
> **Status**: PROPOSED → QA Planning
> **Phase**: SOP Phase 0 (Pre-Work & Architecture Alignment)
> **Date**: 2026-01-04

---

## 1. Architecture Analysis

### 1.1 RFC Scope

| Aspect | Details |
|:---|:---|
| **Optimization** | Rust ↔ Python IPC: JSON → MessagePack |
| **Target** | Zygote IPC only (incremental migration) |
| **Dependencies (Rust)** | `rmp-serde = "1.1"` |
| **Dependencies (Python)** | `msgpack` package |

### 1.2 Acceptance Criteria (from RFC)

| ID | Criterion | Verification |
|:---|:---|:---|
| **AC-1** | Zygote cold start improved by >20% | Performance benchmark |
| **AC-2** | Message size reduced by >40% | Size comparison test |
| **AC-3** | Backward compatible with JSON fallback | Compatibility test |

---

## 2. Test Design

### 2.1 Agent Assignment (Per SOP §4.4)

| Agent | Focus | Test Count |
|:---|:---|:---:|
| Agent A (Edge) | Protocol edge cases | 3 |
| Agent B (Stability) | IPC reliability under load | 3 |
| Agent C (Security) | Message tampering, injection | 3 |
| Agent D (Performance) | Benchmark AC-1, AC-2 | 3 |

### 2.2 Test Cases

#### Agent A: Edge Cases
| ID | Test | Requirement |
|:---|:---|:---|
| EDGE-OPT-001 | Large message handling (>1MB) | Protocol robustness |
| EDGE-OPT-002 | Empty message handling | Edge case |
| EDGE-OPT-003 | Nested structure depth limit | Protocol limits |

#### Agent B: Stability
| ID | Test | Requirement |
|:---|:---|:---|
| STAB-OPT-001 | 1000 sequential IPC calls | No memory leaks |
| STAB-OPT-002 | Concurrent IPC calls (10 workers) | Thread safety |
| STAB-OPT-003 | IPC under memory pressure | Graceful degradation |

#### Agent C: Security
| ID | Test | Requirement |
|:---|:---|:---|
| SEC-OPT-001 | Malformed MessagePack payload | SEC-P0-005 |
| SEC-OPT-002 | Version byte tampering | Protocol integrity |
| SEC-OPT-003 | Length-prefix mismatch (DoS) | Buffer overflow prevention |

#### Agent D: Performance
| ID | Test | Requirement |
|:---|:---|:---|
| PERF-OPT-001 | Cold start latency (AC-1) | >20% improvement |
| PERF-OPT-002 | Message size comparison (AC-2) | >20% reduction (revised) |
| PERF-OPT-003 | JSON fallback latency | Acceptable overhead |

#### Agent E: Fallback (ADV-3)
| ID | Test | Requirement |
|:---|:---|:---|
| FALL-001 | Mock ImportError triggers fallback | Vendor path works |
| FALL-002 | IPC works with Pure Python packer | Data integrity |
| FALL-003 | Stderr warning output correct | RFC warning format |

---

## 3. Pre-Implementation Verification

### 3.1 Current State (Baseline)

Before implementation, establish baseline:

```bash
# Current Zygote IPC uses JSON
# Baseline measurements needed:
# 1. Cold start time with JSON IPC
# 2. Typical message size (JSON)
# 3. IPC roundtrip latency
```

### 3.2 Dependencies Check

| Dependency | Status | Action |
|:---|:---:|:---|
| `rmp-serde` (Rust) | ⏳ | Check Cargo.toml |
| `msgpack` (Python) | ⏳ | Check pyproject.toml |

---

## 4. QA Recommendations

> [!IMPORTANT]
> **This RFC is PROPOSED status (v0.7.0+)**. QA has prepared the test matrix but implementation is NOT started.

### 4.1 When Implementation Begins

1. Developer must notify QA of implementation start
2. QA will create test scaffolding (`tests/qa/test_opt_0010_001_*.py`)
3. Baseline benchmarks must be captured BEFORE any changes

### 4.2 Blockers for QA

- [ ] Implementation branch created
- [ ] Baseline benchmarks captured
- [ ] Dependencies added to project

---

**QA Leader Signature**: QA Working Group
**Date**: 2026-01-04
