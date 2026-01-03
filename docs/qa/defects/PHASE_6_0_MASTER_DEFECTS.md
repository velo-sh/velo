# Master Defect Report: Phase 6.0 Static Graph (RFC-0009)

**QA Verdict**: **REJECTED** (Critical Logic & Observability Gaps)
**Build Hash reviewed**: `2b635e9`

## 🛑 P1 - Critical Logic Defects

### 1. DEF-60-002: AST Classification Failure (Agent A)
*   **Test**: `test_L0_1_ast_dependency_classification`
*   **Reproduction**: `uv run pytest tests/qa/test_phase6_agent_a_edge.py::TestAgentAEdge::test_L0_1_ast_dependency_classification`
*   **Issue**: `DependencyScanner` fails to distinguish "Hard" vs "Soft" imports. Imports inside `def`, `if False`, or `try/except` are incorrectly treated as hard dependencies.
*   **Root Cause**: Incorrect AST visiting logic or failure to propagate "soft" flags to the Graph Builder.

### 2. DEF-60-003: Lazy Import Semantic Violation (Agent B)
*   **Test**: `test_FUNC_603_lazy_import_compliance`
*   **Reproduction**: `uv run pytest tests/qa/test_phase6_agent_b_stability.py::TestAgentBStability::test_FUNC_603_lazy_import_compliance`
*   **Issue**: Load order indices are non-compliant. The binary loads modules in eager order even when `is_lazy` flags are active.
*   **Impact**: Violates RFC-0009 Startup requirements.

## ⚠️ P2 - Performance & Observability Gaps

### 3. DEF-60-004: Missing Metrics JSON (Integration)
*   **Test**: `test_L5_metrics_json_exhaustive`
*   **Issue**: `velo bundle build` does not emit predictable Metrics JSON to stderr/stdout.
*   **Impact**: Blocks automated P2 Performance SLA verification and post-build telemetry.

### 4. DEF-60-005: Build Scale Timeouts
*   **Test**: `test_EDGE_604_hard_limit_gating`
*   **Issue**: Building bundles with ~100 modules exceeds the 30s timeout on M1/M2/M3 hardware.
*   **Analysis**: Likely caused by individual `python3 -c` spawning for every module. Need a persistent worker or single-process compilation strategy.

---
**QA Signature**: Velo QA Working Group (Strict Leader)
**Action Required**: Fix P1 defects and deliver Metrics support to proceed to final sign-off.
