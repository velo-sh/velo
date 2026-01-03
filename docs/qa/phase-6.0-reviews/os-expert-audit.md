# RFC-0009 OS/Systems Expert Review

> **Reviewer Role**: 🖥️ Operating Systems & Systems Programming Specialist  
> **Review Date**: 2026-01-03  
> **RFC Under Review**: [0009-phase-6.0-static-graph.md](../rfcs/0009-phase-6.0-static-graph.md)  
> **Verdict**: 🟢 **APPROVED** (Minor Recommendations)

---

## Executive Summary

The RFC demonstrates **excellent understanding** of syscall overhead and file I/O optimization. The design correctly leverages rkyv for zero-copy access and includes proper locking semantics from Phase 5.x (H-3). This review focuses on cross-platform edge cases and potential kernel-level optimizations.

---

## 🟢 Strengths Acknowledged

| ID | Finding | Assessment |
|----|---------|------------|
| S-13 | **Zero-copy design** | rkyv + mmap is the correct approach for minimizing page faults |
| S-14 | **flock integration** | Inherits H-3 read atomicity from Phase 5.x bundle design |
| S-15 | **Latency budget** | 500μs graph deserialize target is achievable with mmap |
| S-16 | **stat() per-import clarification** | Correctly distinguishes fixed vs per-import overhead |

---

## 🟡 Minor Recommendations (P2 - Should Address)

### P2-010: mmap Hint Strategy Not Specified

**Observation**: For optimal performance, the mmap call should include advisory hints:

```rust
// Linux: madvise(MADV_SEQUENTIAL) for graph section
// macOS: posix_fadvise equivalent via fcntl
```

**Recommendation**: Add to Section 4 or Appendix:
```rust
#[cfg(target_os = "linux")]
unsafe { libc::madvise(ptr, len, libc::MADV_SEQUENTIAL); }

#[cfg(target_os = "macos")]
unsafe { libc::fcntl(fd, libc::F_RDAHEAD, 1); }
```

---

### P2-011: Page Fault Accounting

**Observation**: rkyv "zero-copy" still incurs page faults on first access. For a 150KB graph:
- Page size: 4KB (Linux) / 16KB (macOS ARM)
- Pages touched: ~38 (Linux) / ~10 (macOS ARM)
- Expected faults: ~38 / ~10 minor faults

**Recommendation**: Document expected page fault count in Section 5 for transparency.

---

### P2-012: File Descriptor Lifecycle

**Observation**: The RFC doesn't specify when the graph mmap is unmapped:
1. On bundle close?
2. On process exit only?
3. After all imports complete?

**Recommendation**: Specify in Section 4.2:
> The graph mmap SHOULD remain mapped for the process lifetime to benefit from page cache warmth across multiple runs in the same process (e.g., Zygote workers).

---

### P2-013: Cross-Platform Path Handling

**Observation**: `search_locations` stores paths. Windows uses different path separators.

**Recommendation**: 
1. Store paths in POSIX format (forward slashes)
2. Convert to native format at runtime if needed
3. Document this in Section 3.2 schema

---

## 🔵 Future Considerations (P3)

| ID | Suggestion |
|----|------------|
| P3-004 | Consider `O_DIRECT` bypass for bundle reads on Linux (reduces page cache pressure in memory-constrained environments) |
| P3-005 | Explore `io_uring` for async graph loading in Phase 6.2 |
| P3-006 | Add `RUSAGE_SELF` tracking for page fault metrics in debug builds |

---

## ✅ OS Compliance Checklist

| Requirement | Status |
|-------------|--------|
| No blocking syscalls in hot path | ✅ (mmap is non-blocking after initial fault) |
| Proper file locking (H-3) | ✅ (inherited from Phase 5.x) |
| Cross-platform build targets | ✅ (macOS/Linux specified) |
| Memory safety | ✅ (Rust ownership model) |

---

## 📋 Approval Status

RFC-0009 is **APPROVED** from an OS/systems perspective. The P2 recommendations are optional enhancements for v0.6.1 or later.

---

*Reviewed by: 🖥️ OS/Systems Programming Specialist (Simulated)*  
*Review Protocol: Syscall Efficiency & Cross-Platform Audit*
