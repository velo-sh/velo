# Forensic Indictment Master: Native RSGI Defects

This document acts as the official registry of architectural deficiencies and regressions identified during the Phase 7.2 Native Sovereignty QA audit.

## 🔴 ACTIVE INDICTMENTS

### INDICTMENT-08: Mixed Protocol Starvation
- **Status:** OPEN (Found 2026-01-15)
- **Finding:** Concurrent WebSocket handshake storms can starve standard HTTP requests.
- **Test:** `tests/qa/phase_7_2/test_insane_chaos.py::TestConcurrencyChaos::test_mixed_ws_http_concurrency`
- **Mitigation:** Protocol-level isolation or fair-queueing in the RSGI bridge.

### INDICTMENT-09: WSGI Native Bridge Absence
- **Status:** PENDING PHASE 8.0
- **Finding:** Legacy Flask/Django (WSGI) apps cannot run in Native mode due to lack of a synchronous thread-pool bridge.
- **Test:** `tests/qa/phase_7_2/test_framework_matrix.py::TestWSGIFrameworks`
- **Impact:** Blocks migration for ~60% of legacy Python web applications.

---

## ✅ REMEDIATED INDICTMENTS

### INDICTMENT-01: Severe FD Leakage (SEC-FS-002)
- **Remediation:** Implementation of `close_range_except` in `worker_entry.rs`.
- **Verified:** 2026-01-14.

### INDICTMENT-02: Hard Exit Runtime Panic
- **Remediation:** Removed top-level `unwrap()` in `runtime.rs`.
- **Verified:** 2026-01-14.

### INDICTMENT-07: POST Body Parsing Gap
- **Remediation:** Corrected `receive()` polling logic in the unified ASGI bridge.
- **Verified:** 2026-01-15.

### INDICTMENT-10: Header Truncation Regression
- **Remediation:** Switched to raw byte header extraction in `vendor/granian/src/rsgi/types.rs`.
- **Verified:** 2026-01-15.

---
**Custodian:** Velo QA Team
**Protocol:** Forensic Prosecution (RFC-0024)
