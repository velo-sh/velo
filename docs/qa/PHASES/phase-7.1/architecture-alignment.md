# Phase 7.1 Architecture Alignment (RFC-0018: Integrated Custody)

> **QA Phase**: Phase 0 - Pre-Work & Architecture Alignment
> **QA-SOP Reference**: §3
> **Date**: 2026-01-12
> **QA Engineer**: QA Agent (TITANIUM-LOCK)

---

## 1. Architecture Alignment Checklist (QA-SOP §3.2)

- [x] RFC document read and understood
- [x] All MUST requirements extracted (count: **6** core requirements)
- [x] All security invariants identified (SEC-07-001, SEC-ENV-001, SEC-FS-001)
- [x] Performance thresholds documented (Gate C: shadow sync <100ms)
- [x] Edge cases identified from design
- [x] Known limitations documented
- [x] Test matrix created (Tier × Security × Performance)

---

## 2. RFC-0018 Requirement Extraction

### 2.1 MUST Requirements (from RFC)

| ID | Requirement | RFC Section | Priority | Test ID |
|:---|:---|:---:|:---:|:---|
| R-01 | Embedded uv MUST pass BLAKE3 verification post-extraction | §5 (Gate A) | P0 | CUSTODY-001 |
| R-02 | Autopilot MUST never pollute global socket namespace | §5 (Gate B) | P0 | SEC-07-001 |
| R-03 | Shadow sync overhead MUST be <100ms for no-op | §5 (Gate C) | P1 | CUSTODY-003 |
| R-04 | Extraction paths MUST incorporate Velo build hash | §6 | P0 | CUSTODY-002 |
| R-05 | Shadow uv calls MUST preserve Mandatory Whitelist | §6 | P0 | CUSTODY-004 |
| R-06 | Extraction uses FD-based operations (openat) | §6 (SEC-FS-001) | P0 | CUSTODY-002 |

### 2.2 SHOULD Requirements

| ID | Requirement | RFC Section |
|:---|:---|:---:|
| S-01 | Should fallback gracefully if uv extraction fails | §3.1 |
| S-02 | Should log structured telemetry for Autopilot | §3.3 |

---

## 3. Security Invariant Matrix (TITANIUM FORENSIC AUDIT)

| ID | Invariant Name | Type | Test ID | Status |
|:---|:---|:---:|:---|:---:|
| **SEC-ENV-001** | Provenance Guard | **CRITICAL** | CUSTODY-001 | 🔲 |
| **SEC-FS-001** | Path Sanitization (TOCTOU) | **CRITICAL** | CUSTODY-002 | 🔲 |
| **SEC-07-001** | IPC Atomic Isolation | **CRITICAL** | SEC-07-001 | 🔲 |
| **P0-1** | Peer Auth (SO_PEERCRED) | **CRITICAL** | – | 🔲 |

### 3.1 Remediation Status (from Council Review)

| Issue | Status | Reference |
|:---|:---:|:---|
| SEC-07-001 (Socket Race) | ✅ REMEDIATED | `0018-details-autopilot.md` §3.1 |
| OPS-07-001 (Toolchain Drift) | ✅ REMEDIATED | `0018-details-autopilot.md` §2.2 |

---

## 4. Test Coverage Matrix (RFC-0018 → Tests)

### 4.1 Existing Tests (in `tests/qa/phase_7_1/test_custody.py`)

| Test Class | Coverage | Status |
|:---|:---|:---:|
| `TestCustody001ToolchainIntegrity` | CUSTODY-001 | ✅ Implemented |
| `TestCustody002AtomicExtraction` | CUSTODY-002 | ✅ Implemented |
| `TestCustody003FingerprintDrift` | CUSTODY-003 | ✅ Implemented |
| `TestCustody004ShadowCommands` | CUSTODY-004 | ✅ Implemented |
| `TestAutopilotHeuristics` | Autopilot | ✅ Implemented |

### 4.2 Missing Tests (from QA Handoff Document)

| Test ID | Description | Priority | Status |
|:---|:---|:---:|:---:|
| **RSGI-001** | Handshake & Lifecycle (malformed READY, AUTH_OK) | P0 | ❌ NOT IMPLEMENTED |
| **SEC-07-001** | IPC Atomic Isolation (Abstract Namespace, mkdtemp) | P0 | ❌ NOT IMPLEMENTED |
| **TAINT-001** | Entropy Re-randomization (secrets.token_hex) | P1 | ❌ NOT IMPLEMENTED |

> [!WARNING]
> **3 P0/P1 tests from the QA Handoff document are NOT yet implemented.**
> These are required for Phase 7.1 verification.

---

## 5. Test Tier Definition (QA-SOP §3.3)

| Tier | Focus | Test Files |
|:---:|:---|:---|
| **L0** | Core Smoke | `test_e2e_golden_path.py` |
| **L1** | Feature Tests | `test_custody.py` (CUSTODY-001 to 004) |
| **L2** | Edge Cases | `test_custody.py::TestAutopilotHeuristics` |
| **L3** | Security | SEC-07-001, TAINT-001 (**MISSING**) |
| **L4** | IPC Protocol | RSGI-001 (**MISSING**) |

---

## 6. Gap Analysis Summary

### 6.1 Critical Gaps

1. **RSGI-001**: No test for MessagePack handshake validation
2. **SEC-07-001**: No test for Abstract Namespace Sockets (Linux) / mkdtemp isolation (macOS)
3. **TAINT-001**: No test for entropy re-randomization post-fork

### 6.2 Recommended Action

**Option A**: Implement missing tests before proceeding with Phase 7.1 execution
**Option B**: Mark as BLOCKED pending architecture implementation (defer to Phase 7.2)

---

## 7. QA-SOP Compliance Status

| SOP Section | Requirement | Status |
|:---|:---|:---:|
| §3.1 | RFC/Architecture Review | ✅ Complete |
| §3.2 | Architecture Alignment Checklist | ✅ Complete |
| §3.3 | Tier Definition | ✅ Complete |
| §3.4 | Fail-Fast Rule | ✅ Acknowledged |
| §3.5 | First Principles Pyramid | ✅ Applied |
| §3.6 | Coverage Targets (85%) | ⚠️ Pending test run |

---

**Phase 0 Status**: ✅ **COMPLETE**
**Next Phase**: Phase 1 (Test Design & Implementation) - Implement missing tests

---

**QA Signature**: Velo QA Working Group (TITANIUM-LOCK)
**Date**: 2026-01-12
