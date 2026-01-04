# Agent A (Edge & Graph) -> Review RFC-0009 Static Graph Design

> **Reviewer**: Agent A (Edge Case Specialist)  
> **Review Target**: RFC-0009 Static Import Graph  
> **Date**: 2026-01-03  
> **Stance**: Aggressive boundary testing of graph topology and filesystem parity.

---

## 🟢 Strengths (A-S-01)
- **Hard Limit Gating**: The 5,000 module hard limit is a necessary circuit breaker for build-time safety.
- **Tarjan's SCC**: Correct choice for handling cyclic dependencies without breaking the build.

---

## 🟠 Edge Case Findings (A-P1)

### A-P1-001: The "Deep DAG" Stack Depth
**Problem**: A project with a 400-level deep dependency chain (common in some auto-generated code).
**Risk**: Recursive graph walking during `VeloFinder` initialization might exceed Rust/Python stack limits.
**Recommendation**: The loader MUST use an iterative DFS/BFS for pre-mapping bytecode, not recursion.

### A-P1-002: Symlink "Time-of-Check to Time-of-Use" (TOCTOU)
**Problem**: `source_hash` covers file content, but if a symlink `foo.py -> bar.py` is swapped to `foo.py -> baz.py` *without* changing content, the hash might not trigger a rebuild if metadata isn't included.
**Recommendation**: `source_hash` MUST include file paths and symlink targets in the hash preimage.

### A-P1-003: Namespace Shadowing Boundary
**Problem**: A module in the bundle shadows a module in the user's `site-packages`.
**Recommendation**: Verify `VeloFinder` priority logic handles this consistently with standard CPython `sys.path` ordering.

---

## 📈 Scale & Stress Scenarios

| ID | Scenario | Target |
|----|----------|--------|
| **A-TC-01** | **Empty Bundle** | Graceful "no-op" graph handling |
| **A-TC-02** | **1MB Single Module** | Large bytecode record packing safety |
| **A-TC-03** | **5,001 Modules** | Verify CID build failure |

---

**Agent A Sign-off**: Verified from Boundary Perspective.  
**Recommendation**: Approved for development.
