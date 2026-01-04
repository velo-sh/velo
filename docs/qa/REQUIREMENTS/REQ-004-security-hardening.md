# QA-REQ-004: Security Hardening (P0 Audit Baseline)

## 1. Overview
This requirement defines the validation criteria for the hard invariants specified in Phase 5.3 (Audit P0s). These tests MUST be implemented in the integration layer (`tests/qa/`) to satisfy the Phase 5 final audit.

## 2. P0 Verification Matrix

### 2.1 Global Hash Integrity (SEC-AUD-001)
Verify that tampering with *any* part of the bundle (including the previously unprotected header) triggers a verification failure.

| Test Case Path | Tamper Target | Range | Expected Result |
|----------------|---------------|-------|-----------------|
| `SEC-AUD-001-A` | Bundle Version | `[4..8]` | `LoaderError::HashMismatch` |
| `SEC-AUD-001-B` | Index Offset | `[12..20]` | `LoaderError::HashMismatch` |
| `SEC-AUD-001-C` | Data Section | `[128..]` | `LoaderError::HashMismatch` |
| `SEC-AUD-001-D` | Trailing Nulls | `[EOF-100..]`| `LoaderError::HashMismatch` |

### 2.2 Atomic Read / TOCTOU (SEC-AUD-002)
Verify that the loader maintains a shared lock and rejects/fails if the file is swapped during the verification window.

| Test ID | Scenario | Verification Method |
|---------|----------|---------------------|
| `SEC-AUD-002-A` | Attempt to write to `.veloc` | `flock` check: `open(O_RDWR)` should fail or block |
| `SEC-AUD-002-B` | Simulated File Swap | Verify that the file descriptor remains locked throughout `load_and_verify` |

### 2.3 Recursive Marshal Guard (SEC-AUD-003)
Verify protection against deeply nested bytecode structures (Marshal Bombs).

| Test ID | Depth | Expected Result |
|---------|-------|-----------------|
| `MARSHAL-SAFE-01` | 100 | Success (Valid execution) |
| `MARSHAL-BOMB-02` | 1000 | `RecursionError` or Controlled Failure |

## 3. Implementation Guidelines for QA
1. **Tooling**: Use `blake3` python wrapper for manual hash manipulation in tests.
2. **Lock-Check**: Use `fcntl.flock` in test suite to verify that `velo` has successfully acquired a shared lock.
3. **Traceability**: All failures MUST result in a non-zero exit code and a clear error message in `stdout/stderr`.

---
*Date: 2026-01-03*  
*Author: 🏛️ Architect (ID-LOCK-001)*
