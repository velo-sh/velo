# Agent B (Core & Import) -> Review RFC-0009 Static Graph Design

> **Reviewer**: Agent B (Core Flow specialist)  
> **Review Target**: RFC-0009 Static Import Graph  
> **Date**: 2026-01-03  
> **Stance**: Conservative verification of Python import semantics and Rkyv zero-copy efficiency.

---

## 🟢 Strengths (B-S-01)
- **Import Protocol Parity**: Preservation of `builtins.__import__` ensures compatibility with existing mocks and instrumentation.
- **Rkyv Zero-Copy**: The < 500μs deserialize target is realistic given the zero-copy nature of the archive.

---

## 🔴 Core Parity Findings (B-P0)

### B-P0-001: `__path__` Mutation Leakage
**Observation**: RFC Section 4.3.2 correctly addresses `mutable_path_packages`. 
**Agent B Supplement**: We must ensure that once a package hits "mutable fallback", its **children** are never accidentally serviced by the stale graph.
**Action**: The loader MUST invalidate the graph sub-tree for any module where `__path__` does not match the cached search location.

### B-P0-002: Lazy Import (PEP 690) Deadlock Risk
**Problem**: If preloading is triggered in a lazy import context, we might violate the "no eager execution" invariant.
**Recommendation**: In lazy mode, the graph MUST only be used for `find_spec` (mapping bytecode), but mandatory pre-mapping of dependencies MUST be disabled.

---

## ⚡ Performance Matrix

| Metric | Target | Method |
|--------|--------|--------|
| **Graph Map Time** | < 200μs | mmap(2) syscall overhead |
| **PHF Lookup** | < 100ns | O(1) mathematical mapping |
| **Memory usage** | < 200KB | Massif heap profiling |

---

**Agent B Sign-off**: Verified from Core Semantics perspective.  
**Recommendation**: Approved for development.
