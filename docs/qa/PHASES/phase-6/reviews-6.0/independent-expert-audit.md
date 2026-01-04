# RFC-0009 Independent Expert Review
> **Reviewer Role**: 🔬 Security & Architecture Expert  
> **Review Date**: 2026-01-03  
> **RFC Under Review**: [0009-phase-6.0-static-graph.md](../rfcs/0009-phase-6.0-static-graph.md)  
> **Verdict**: 🟡 **CONDITIONAL APPROVAL** (Requires Clarifications)

---

## Executive Summary

RFC-0009 proposes a sound optimization strategy. The core concept of pre-computing an import graph to eliminate `stat()` calls is technically valid and aligns with Velo's performance-first philosophy. However, **several critical gaps** must be addressed before implementation can proceed.

---

## 🟢 Strengths

| ID | Finding | Assessment |
|----|---------|------------|
| S-01 | **Clear problem definition** | The motivation is well-articulated. `stat()` overhead is a known bottleneck in containerized/serverless environments. |
| S-02 | **Fallback mechanism** | The design correctly includes fallback to standard import for modules not in the graph. This preserves 100% compatibility. |
| S-03 | **Cache invalidation** | Using `source_hash` for invalidation is a robust approach that prevents stale graph issues. |
| S-04 | **Bundle integration** | Extending the existing `.veloc` format is cleaner than introducing a separate file. |

---

## 🟡 Design Gaps (P1 - Must Fix Before Implementation)

### P1-001: Missing Handling for Conditional Imports
**Problem**: Python allows conditional imports that cannot be statically analyzed:
```python
if USE_ASYNC:
    import asyncio
else:
    import threading
```
**Risk**: The static graph will miss these dependencies, causing runtime `ModuleNotFoundError`.

**Recommendation**: 
1. Document this as a known limitation.
2. Implement a `--include-conditional` flag for bundle builder that uses runtime tracing as a fallback.

---

### P1-002: No Specification for `__import__()` and `importlib.import_module()`
**Problem**: Dynamic imports via `__import__()` or `importlib.import_module()` are invisible to AST analysis.

**Risk**: Applications using plugin systems or lazy loading will break silently.

**Recommendation**:
1. The graph should be treated as a **hint**, not a ground truth.
2. If a module is NOT found in the graph, the loader MUST fall back to standard import (already specified, but needs emphasis).
3. Add a metric to track "graph miss rate" in production.

---

### P1-003: Circular Import Detection is Insufficient
**Problem**: The RFC mentions "Detect at build time; fail with clear error" but provides no specification.

**Risk**: Circular imports are common in real-world codebases (e.g., Django models). A naive implementation will cause build failures.

**Recommendation**:
1. Use Tarjan's algorithm for SCC detection.
2. For circular imports, mark all modules in the cycle as "unordered" and load them in the order requested at runtime.
3. Emit a WARNING, not an error, since Python itself handles circular imports at runtime.

---

### P1-004: No Security Invariant for Graph Integrity
**Problem**: The RFC does not specify how the graph itself is protected from tampering.

**Risk**: An attacker could modify the graph to redirect imports to malicious modules.

**Recommendation**:
1. **H-8 (Graph Integrity)**: The import graph MUST be covered by the bundle's global BLAKE3 hash (H-1).
2. The graph section should be included in the `[52..EOF]` range verified by `verify_blake3()`.
3. Add this to the "Security Invariants" section of the RFC.

---

## 🟠 Design Considerations (P2 - Should Address)

### P2-001: Performance Target Ambiguity
**Problem**: The target "< 12ms cold start" assumes FastAPI, but the current 17.7ms is for a *simple script*, not FastAPI.

**Recommendation**: Clarify which benchmark is used. If FastAPI, the baseline is ~500ms, not 17.7ms.

---

### P2-002: Memory Overhead Estimation
**Problem**: "< 100KB for 500 modules" is a rough estimate without justification.

**Recommendation**: Provide a back-of-envelope calculation:
- Average module name: 20 bytes
- Average deps per module: 5
- Per-edge overhead: ~40 bytes (HashMap entry)
- 500 modules × 5 deps × 40 bytes = 100KB ✓

---

### P2-003: No Incremental Rebuild Strategy
**Problem**: If one source file changes, must the entire graph be rebuilt?

**Recommendation**: Consider a two-level invalidation:
1. **File-level hash**: Detect which files changed.
2. **Incremental update**: Only re-analyze changed files and their dependents.

---

## 🔵 Future Considerations (P3 - Nice to Have)

| ID | Suggestion |
|----|------------|
| P3-001 | Consider encoding the graph as a binary trie for O(log n) lookups instead of HashMap. |
| P3-002 | Add support for "optional dependencies" (try/except import) in the graph schema. |
| P3-003 | Integrate with `velo analyze` to visualize the import graph. |

---

## ✅ Recommended Actions Before Approval

1. **Add P1-004 (H-8 Graph Integrity)** to Section 4 of the RFC.
2. **Document P1-001 and P1-002** as known limitations in a new "Limitations" section.
3. **Specify circular import handling** in Section 4.1.
4. **Clarify performance baseline** in Section 5.

Once these are addressed, RFC-0009 is **approved for implementation**.

---

*Reviewed by: 🔬 Independent Expert (Simulated)*  
*Review Protocol: Phase 5.0 Audit Standard*
