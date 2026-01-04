# OPT-0010-001 MessagePack IPC - QA Implementation Plan

> **Status**: SOP Phase 0 Complete → Awaiting User Approval
> **Date**: 2026-01-04

---

## Phase 0 Findings

| Aspect | Current State | Target State |
|:---|:---|:---|
| **IPC Protocol** | JSON (`serde_json`) | MessagePack (`rmp-serde`) |
| **Rust Dependency** | Not added | `rmp-serde = "1.1"` |
| **Python Dependency** | Not added | `msgpack` |
| **RFC Status** | PROPOSED (v0.7.0+) | In Development |

### Key Files Identified

- `src/zygote/ipc.rs` - Rust IPC implementation (JSON currently)
- `velo_zygote/main.py` - Python Zygote (JSON currently)

---

## Proposed QA Test Implementation

### Phase 1: Test Design & Implementation

#### Directory Structure
```
tests/qa/
└── opt_0010_001/
    ├── test_msgpack_edge.py      # Agent A: Edge Cases
    ├── test_msgpack_stability.py # Agent B: Stability
    ├── test_msgpack_security.py  # Agent C: Security
    └── test_msgpack_perf.py      # Agent D: Performance
```

### Phase 2-3: Review (Per SOP)

- Agent cross-review after implementation
- Leader gap analysis
- External expert audit if P0 issues found

### Phase 4-6: Verification & Delivery

- Run all test suites
- Capture performance baselines
- Final sign-off

---

## User Review Required

> [!IMPORTANT]
> This RFC is **PROPOSED** status for **v0.7.0+**. Implementation has NOT started.

### Questions for User:

1. **Should QA create test scaffolding NOW (before implementation)?**
   - PRO: Tests ready when Developer starts
   - CON: May need adjustment after implementation

2. **Which baseline benchmarks should be captured?**
   - Current Zygote cold start time
   - Current message size (typical Fork command)
   - Current IPC roundtrip latency

3. **Should QA proceed with Phase 1 (Test Design)?**

---

**QA Signature**: QA Working Group
**Date**: 2026-01-04
