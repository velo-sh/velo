# RFC-0038 Requirements Traceability Matrix

> **Phase**: RFC-0038 AI-Native Diagnostics
> **Version**: v0.9.5
> **Date**: 2026-01-23
> **Reference**: [RFC-0038](../../../rfcs/0038-ai-native-diagnostics.md)

---

## 1. Requirement-to-Test Mapping

| Req ID | Requirement | RFC Section | Test ID(s) | Status |
|:---|:---|:---:|:---|:---:|
| **REQ-001** | `--prof-md` flag to `velo run` | §3.1, §4.1 | `L0_001`, `L0_002`, `L0_003` | ⬜ Pending |
| **REQ-002** | Secrets Sanitizer | §3.2 | `SEC_038_001` - `SEC_038_008` | ⬜ Pending |
| **REQ-003** | Top 20 Hot Functions table | §3.1 | `L1_003`, `L1_004`, `L1_005` | ⬜ Pending |
| **REQ-004** | Atomic file write | §4.3 | `L2_001`, `L2_007` | ⬜ Pending |
| **REQ-005** | Overhead < 5% | §10 | `PERF_038_001` - `PERF_038_003`, `GATE_C` | ⬜ Pending |
| **REQ-006** | Output to stderr or file | §3.1 | `L0_002`, `L0_003` | ⬜ Pending |
| **REQ-007** | GFM compliance | §3.2 | `L1_006`, `GATE_A` | ⬜ Pending |
| **REQ-008** | Summary placement | §3.2 | `L1_002` | ⬜ Pending |
| **REQ-009** | Snippet bounds (5 lines) | §3.2 | `L2_004` | ⬜ Pending |
| **REQ-010** | Version comment | §3.2 | `L1_001` | ⬜ Pending |
| **REQ-011** | Agent Hints from telemetry | §4.4 | `L2_*` (implicit) | ⬜ Pending |

---

## 2. Security Invariant Mapping

| Invariant ID | Description | RFC Section | Test ID(s) | Status |
|:---|:---|:---:|:---|:---:|
| **SEC-038-001** | KEY redaction | §3.2 | `SEC_038_001` | ⬜ Pending |
| **SEC-038-002** | SECRET redaction | §3.2 | `SEC_038_002` | ⬜ Pending |
| **SEC-038-003** | TOKEN redaction | §3.2 | `SEC_038_003` | ⬜ Pending |
| **SEC-038-004** | PASSWORD redaction | §3.2 | `SEC_038_004` | ⬜ Pending |
| **SEC-038-005** | Case-insensitive matching | §3.2 | `SEC_038_005` | ⬜ Pending |
| **SEC-038-006** | No ANSI codes | §4.2 | `L2_005` | ⬜ Pending |
| **SEC-038-007** | UTF-8 compatibility | §4.2 | `L2_003` | ⬜ Pending |

---

## 3. Quality Gate Mapping

| Gate | Description | RFC Section | Test ID | Status |
|:---|:---|:---:|:---|:---:|
| **Gate A** | `mdl` lint passes | §10 | `GATE_A_mdl_lint` | ⬜ Pending |
| **Gate B** | AI identifies bottleneck | §10 | `GATE_B_ai_bottleneck` | ⬜ Pending |
| **Gate C** | Overhead < 5% | §10 | `GATE_C_overhead` | ⬜ Pending |

---

## 4. Implementation File Mapping

| File | Requirements Covered | Status |
|:---|:---|:---:|
| `src/common/diagnostics.rs` | REQ-002, REQ-003, REQ-007, REQ-008, REQ-009, REQ-010 | 🔴 Not Started |
| `src/cmd/run.rs` | REQ-001, REQ-004, REQ-006 | 🔴 Not Started |
| `src/cli.rs` | REQ-001 | 🔴 Not Started |

---

## 5. Coverage Summary

| Category | Total | Covered | Percentage |
|:---|:---:|:---:|:---:|
| Requirements | 11 | 0 | 0% |
| Security Invariants | 7 | 0 | 0% |
| Quality Gates | 3 | 0 | 0% |
| **Overall** | **21** | **0** | **0%** |

---

## 6. Traceability Legend

| Symbol | Meaning |
|:---|:---|
| ⬜ | Pending (test not executed) |
| 🟡 | In Progress (test written, not run) |
| ✅ | Passed |
| ❌ | Failed |
| ⚠️ | XFAIL (expected failure, documented) |
| 🔴 | Not Started |
| 🟢 | Complete |

---

## 7. Gap Analysis

### 7.1 Covered Requirements
- All 11 requirements have mapped tests
- All 7 security invariants have mapped tests
- All 3 quality gates have mapped tests

### 7.2 Potential Gaps
| Gap | Description | Priority | Action |
|:---|:---|:---:|:---|
| None identified | Full coverage planned | - | - |

### 7.3 Deferred (Out of Scope)
| Item | Reason | Target Version |
|:---|:---|:---:|
| `--prof-json` | Deferred per Handoff | v1.1 |
| `velo diff` | Future RFC | TBD |
| OpenTelemetry Span IDs | Future | TBD |

---

## 8. Update Log

| Date | Author | Change |
|:---|:---|:---|
| 2026-01-23 | QA Working Group | Initial traceability matrix |

---

**QA Working Group** | Traceability Matrix v1.0 | 2026-01-23
