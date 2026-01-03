# RFC-0009 QA/Testing Expert Review

> **Reviewer Role**: 🧪 QA & Testing Specialist Group  
> **Review Date**: 2026-01-03  
> **RFC Under Review**: [0009-phase-6.0-static-graph.md](../rfcs/0009-phase-6.0-static-graph.md)  
> **Verdict**: 🟢 **APPROVED** (Requires expanded negative testing suite)

---

## Executive Summary

The verification plan (§6) in the current RFC is a good start but lacks the "destructive" and "adversarial" testing components necessary for a production bootstrapper. As the 9th expert group, we advocate for a **Tiered Testing Strategy (L0-L5)** similar to previous Velo phases, with a focus on graph corruption and extreme edge cases.

---

## 🟢 Strengths Acknowledged

| ID | Finding | Assessment |
|----|---------|------------|
| S-26 | **Performance Benchmarks** | The inclusion of p50/p95/p99 targets and dedicated CI runners (DevOps Audit) is excellent. |
| S-27 | **Automated Invalidation** | `test_graph_invalidation.py` correctly identifies the parity risk on source changes. |
| S-28 | **Fallback Verification** | `test_graph_fallback.py` is critical for ensuring non-breaking behavior. |

---

## 🔴 Critical Findings (P0 - Must Fix)

### P0-008: Missing Negative Testing (Graph Corruption)

**Problem**: The RFC focuses on valid graphs. It does not specify how the loader should behave if the graph section exists but contains **semantically invalid data** (e.g., a cycle that wasn't detected at build time, or an edge pointing to a non-existent module).

**Risk Level**: 🔴 **CRITICAL** - Startup crash.

**Recommendation**:
1. **Fuzzing**: Add a task for `cargo fuzz` targeting the `rkyv` deserialization and graph resolution logic.
2. **Negative Tests**: Implement `test_corrupted_graph.py` which deliberately injects invalid offsets into the `ModuleRecord`.

---

## 🟡 Design Recommendations (P1 - Must Fix Before Implementation)

### P1-017: Edge Case: Symlinked Modules

**Problem**: If a module is a symlink to another file outside the bundle, the static analysis might resolve it differently than the runtime loader.

**Recommendation**:
1. Add `test_symlink_imports.py` to verify that symlinked modules are either captured correctly or explicitly fall back to standard imports.

---

### P1-018: Scale Testing (Deep Dependency Trees)

**Problem**: A project with 1000+ modules might have dependency chains 50-100 modules deep.

**Recommendation**:
1. **Synthetic Load Test**: Create a script to generate a synthetic Python project with 5000 modules and a randomized, deep dependency DAG to verify the "Hard Limit" gating and p99 latency.

---

## 🟠 Testing Enhancements (P2 - Should Address)

### P2-024: Version Skew Matrix

**Observation**: Velo v0.6.0 might run a bundle built by v0.5.x or v1.0.0.

**Recommendation**: 
1. **Compatibility Matrix**: Test "New Loader + Old Bundle" and "Old Loader + New Bundle".
2. **Failure Mode**: Ensure the loader emits a clear `LoaderError::VersionMismatch` instead of a segfault.

---

### P2-025: Concurrent Build/Run Integrity

**Observation**: If `velo run --fast` triggers a rebuild while another process is reading the bundle.

**Recommendation**: 
1. **Stress Test**: Verify that H-3 (File Locking) remains effective during graph rebuilds.

---

## 🔵 Future Considerations (P3)

| ID | Suggestion |
|----|------------|
| P3-015 | Static Analysis "Confidence Score" report for users. |
| P3-016 | Integration with `mutagen` for mutation testing of the graph resolution logic. |

---

## ✅ QA Compliance Checklist

| Requirement | Status |
|-------------|--------|
| Positive Testing (Happy Path) | ✅ (Documented) |
| Negative Testing (Adversarial) | ❌ (Missing) |
| Performance Baselines | ✅ (Standardized) |
| Edge Case Coverage | ⚠️ (Symlinks/Deep DAGs needed) |

---

## 📋 Approval Status

RFC-0009 is **APPROVED** provided that the **Verification Plan (§6)** is updated with the **Negative/Stress Testing** sub-section.

---

*Reviewed by: 🧪 QA Specialist Group (Simulated)*  
*Review Protocol: Tiered Testing & Edge Case Audit*
