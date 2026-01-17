# Known Issues (Phase 7.3 Stabilization)

**Date:** 2026-01-17
**Status:** Documented

## 🔴 Critical / Blocking
### DEF-72-ARCH-001: Orphan Storm (Regression)
*   **Status**: Failing (Environment Dependent)
*   **Symptom**: `test_DEF_72_ARCH_001_orphan_storm` fails with "No workers spawned" in Core Systems / CI environments.
*   **Root Cause**: While `Unified Python Environment Resolution` (SSOT) was implemented in `6c0553b`, specific high-security environments (Docker/Prod) may strip path resolution indicators needed by `PythonEnv::detect`.
*   **Action**: Transferred to **Core Systems Team** for infrastructure remediation.
*   **Workaround**: None (Requires fix).

## ⚠️ High / Flaky
### test_DESYNC_007: Shadow Handshake (Flakiness)
*   **Status**: Flaky (~10% Failure Rate)
*   **Symptom**: Automation failure in `tests/qa/phase_6_1_1/test_phase611_agent_d_desync.py`.
*   **Root Cause**: Race condition in test harness. Sending "Status" command before reading "Ready" relies on kernel socket buffering which varies by load/platform.
*   **Action**: Low priority. Test refactor required to strictly await "Ready" before sending commands.
