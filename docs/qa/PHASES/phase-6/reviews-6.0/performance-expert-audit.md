# RFC-0009 Performance Expert Review

> **Reviewer Role**: ⚡ Performance Engineering Specialist  
> **Review Date**: 2026-01-03  
> **RFC Under Review**: [0009-phase-6.0-static-graph.md](../rfcs/0009-phase-6.0-static-graph.md)  
> **Verdict**: 🟡 **CONDITIONAL APPROVAL** (Performance Targets Need Refinement)

---

## Executive Summary

The RFC proposes a sound optimization strategy with clear performance goals. However, the **benchmarking methodology is incomplete** and some **latency assumptions are overly optimistic**. This review focuses on ensuring the performance claims are measurable, reproducible, and achievable.

---

## 🔴 Critical Findings (P0 - Must Fix)

### P0-003: Graph Deserialization Overhead Not Accounted

**Problem**: The RFC claims "< 100KB" memory for 500 modules but does not account for:
1. **rkyv deserialization time**: Zero-copy access still requires page faults on first access
2. **HashMap reconstruction**: rkyv HashMap access is O(1) but has different constants than std::HashMap
3. **Heap allocations**: String keys require allocation when accessed

**Risk Level**: 🔴 **CRITICAL** - Graph loading itself could become the new bottleneck.

**Measured Baseline Required**:
```
Graph Size: 500 modules × 5 deps = 2,500 edges
Estimated rkyv size: ~50-80KB (needs verification)
Deserialize time: ??? ms (UNKNOWN - must measure)
```

**Recommendation**:
1. Add a **mandatory benchmark** in verification plan: `graph_deserialize_latency_us`
2. Target: **< 500μs** for 500-module graph (0.5ms budget of 10ms target)
3. If rkyv is too slow, consider mmapping the raw bytes and lazy access

---

### P0-004: `stat()` Elimination Claim is Misleading

**Problem**: The RFC claims "0 stat() calls for bundled modules" but this is only true for **import resolution**. The following `stat()` calls remain:

1. **Bundle file itself**: `stat(bundle.veloc)` on open
2. **Cache validation**: `stat(uv.lock)` for fingerprint
3. **Source hash check**: If source files are checked for staleness

**Risk Level**: 🔴 **CRITICAL** - Marketing claim ("0 stat()") is technically inaccurate.

**Recommendation**:
1. Change claim to: "0 stat() calls **per import** for bundled modules"
2. Document the fixed overhead of bundle opening
3. Add syscall tracing test to verify the claim

---

## 🟡 Design Gaps (P1 - Must Fix Before Implementation)

### P1-008: Cold Start Target is Not Decomposed

**Problem**: The target "<10ms for simple script" is a black box. What are the expected contributions?

| Phase | Current Guess | Needs Measurement |
|-------|---------------|-------------------|
| Bundle open | ??? ms | ⚠️ |
| Graph load | ??? ms | ⚠️ |
| Hash verify | ??? ms | ⚠️ |
| Module exec | ??? ms | ⚠️ |

**Recommendation**:
1. Add breakdown targets in Section 5:
   - Bundle open + verify: < 2ms
   - Graph load: < 0.5ms
   - Import resolution: < 0.1ms per module
   - First module exec: < 1ms

---

### P1-009: No Regression Guard for Graph Size

**Problem**: As projects grow, graphs will grow. There's no specification for:
1. Maximum supported graph size
2. Performance degradation curve
3. Warning threshold for large graphs

**Recommendation**:
1. Define soft limit: **1000 modules** (emit warning above)
2. Define hard limit: **5000 modules** (emit error, suggest splitting)
3. Add O(n) complexity guarantees for all graph operations

---

### P1-010: Memory Estimate Lacks Precision

**Problem**: "< 100KB for 500 modules" is derived as:
```
500 modules × 5 deps × 40 bytes = 100KB
```

But this ignores:
- Module name strings (avg 25 chars × 500 = 12.5KB)
- Search locations strings (avg 50 chars × 100 packages = 5KB)
- HashMap overhead (load factor, buckets)
- rkyv alignment padding

**Actual estimate should be**:
```
Edges:           100KB
Module names:    15KB
Search locations: 10KB
HashMap overhead: 20KB
rkyv padding:    10KB
---
Total:           ~155KB (not 100KB)
```

**Recommendation**: Update Section 5 with more accurate estimate: "< 200KB for 500 modules"

---

## 🟠 Design Considerations (P2 - Should Address)

### P2-007: No Warm Path Optimization

**Problem**: The RFC focuses on cold start but doesn't address:
1. **Repeated runs**: Is the graph cached in OS page cache?
2. **Zygote integration**: How does graph interact with pre-warmed process?

**Recommendation**: Add Phase 6.1 item: "Graph preload into Zygote for instant warm start"

---

### P2-008: Benchmark Environment Not Specified

**Problem**: Performance numbers depend heavily on:
- Disk type (NVMe vs HDD)
- OS page cache state
- Python version
- System load

**Recommendation**: Define standard benchmark environment:
```yaml
benchmark_env:
  os: macOS 14+ / Linux 6.x
  disk: NVMe SSD
  cache: cold (drop caches before run)
  python: 3.11.x
  iterations: 10 (report p50, p95, p99)
```

---

### P2-009: No Comparison Against Alternatives

**Problem**: The RFC doesn't compare against:
1. **Python 3.11+ import caching** (lazy imports, __pycache__)
2. **zipimport** performance
3. **Other bundlers** (PyInstaller, Nuitka)

**Recommendation**: Add "Related Work" section comparing approach to alternatives.

---

## ✅ Strengths Acknowledged

| ID | Finding |
|----|---------|
| S-09 | Clear performance targets (even if needing refinement) |
| S-10 | rkyv choice is solid for zero-copy access |
| S-11 | Topological sort enables predictable loading |
| S-12 | Graph miss metric allows runtime monitoring |

---

## 📋 Required Actions Before Approval

1. **[P0-003]** Add graph deserialization benchmark with < 500μs target.
2. **[P0-004]** Correct "0 stat()" claim to "0 stat() per import".
3. **[P1-008]** Add latency breakdown for cold start target.
4. **[P1-009]** Define graph size limits and degradation policy.
5. **[P1-010]** Update memory estimate to ~200KB.
6. **[P2-008]** Specify benchmark environment.

Once these are addressed, RFC-0009 is **approved for implementation**.

---

*Reviewed by: ⚡ Performance Engineering Specialist (Simulated)*  
*Review Protocol: Latency Budget Analysis*
