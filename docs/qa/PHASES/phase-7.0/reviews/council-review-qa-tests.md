# ⚖️ Grand Council Review: RFC-0015 QA Test Suite

> **Subject**: Phase 7.0 Memory Gravity Test Implementation
> **Date**: 2026-01-07
> **Commit**: `6758119` (7 files, 2765 insertions)

---

## Phase I: The Summons

### Changes Analyzed
```
tests/qa/phase_7_0/*.py      → 4 test files (2273 lines)
docs/qa/PHASES/phase-7.0/*   → 2 docs (492 lines)
```

### Council Members Summoned

| Expert | Reason |
|:---|:---|
| 🔐 **Security Engineer** | L3 security tests (sealing, attack simulation) |
| 🐍 **Python Core Dev** | All tests are Python, mmap/multiprocessing usage |
| ⚡ **HPC Engineer** | L4 performance tests (alignment, NUMA) |
| 🐧 **Linux Specialist** | memfd_create, F_SEAL, /proc filesystem |

---

## Phase II: The Critique

### 🔐 Security Engineer Says:

> "Show me your attack surface and defense validation."

**Critique**:

1. ✅ **L3-SHM-10 Malicious Worker Test**: Good coverage of attack vectors:
   - `mprotect(PROT_WRITE)` bypass attempt
   - Direct `write(fd)` attempt
   - `ftruncate()` shrink attack
   - `dup() + write` escalation

2. ⚠️ **Missing Attack Vector**: No test for `ptrace` attach to sealed memory. RFC-0015 mentions this but L3-SHM-10 doesn't implement it.
   - **Recommendation**: Add ptrace test or document as out-of-scope for v0.7.0.

3. ✅ **Seal Ordering (H-23)**: Properly verifies the 8-step sequence via whitebox testing.

4. ⚠️ **Cross-Tenant Test Missing**: H-27 (FD Capability Containment) claims cross-tenant is "EXPLICITLY DISALLOWED" but no test verifies this enforcement.
   - **Recommendation**: Add a negative test attempting cross-PID-namespace FD passing.

**Verdict**: APPROVED with recommendations

---

### 🐍 Python Core Dev Says:

> "Does this respect mmap lifecycle and multiprocessing safety?"

**Critique**:

1. ✅ **mmap Usage**: Correct use of `mmap.mmap()` with proper `ACCESS_READ`/`ACCESS_WRITE` modes.

2. ✅ **Fixed Pickling Bug**: Good catch on the `recovery_worker` local function issue for macOS spawn-based multiprocessing.

3. ⚠️ **Inline Script Pattern**: Tests use embedded Python strings executed via subprocess. This works but:
   - Harder to debug
   - No IDE support for inline scripts
   - **Recommendation**: Consider refactoring to separate helper modules for complex logic.

4. ⚠️ **GC Dependency**: `test_L2_SHM_04_attach_detach_storm` relies on `gc.collect()` for FD cleanup verification. This may be flaky on different Python implementations.
   - **Recommendation**: Add explicit `mm.close()` calls before checking FD count.

5. ✅ **Memory Safety**: No use of `ctypes` to bypass Python memory safety (which would violate H-17).

**Verdict**: APPROVED

---

### ⚡ HPC Engineer Says:

> "Is the hot path verified? Show me the alignment math."

**Critique**:

1. ✅ **64-byte Alignment Algorithm**: Correctly implements RFC-0015 Appendix A formula:
   ```python
   # Target: (8 + header_len) % 64 == 0
   # Therefore: header_len % 64 == 56
   if remainder <= 56:
       T = L + (56 - remainder)
   else:
       T = L + (64 - remainder) + 56
   ```

2. ✅ **Test Header Lengths**: Good coverage with `[1, 63, 64, 65, 127, 128, 1023, 1024]`.

3. ⚠️ **Missing Edge Case**: What about header_length = 0? Or negative values?
   - **Recommendation**: Add boundary tests for 0 and max header sizes.

4. ✅ **Performance Baseline**: `test_mmap_vs_file_read_baseline` establishes proper baseline comparison.

5. ⚠️ **NUMA Test Coverage**: NUMA test skips gracefully on single-node systems, but doesn't actually verify cross-node penalty when NUMA *is* available.
   - **Recommendation**: On multi-NUMA systems, add a test that intentionally violates NUMA affinity and measures the penalty.

**Verdict**: APPROVED with recommendations

---

### 🐧 Linux Specialist Says:

> "Are the syscalls used correctly? Is /proc parsing robust?"

**Critique**:

1. ✅ **memfd_create Syscall**: Correctly uses `libc.syscall(319, ...)` for x86_64.
   - ⚠️ **Architecture-Specific**: Syscall 319 is x86_64 specific. ARM64 uses a different number.
   - **Recommendation**: Use `SYS_memfd_create` from `libc` or detect architecture.

2. ✅ **F_SEAL Flags**: Correct usage of `F_SEAL_WRITE | F_SEAL_SHRINK | F_SEAL_GROW`.

3. ⚠️ **/proc/self/maps Parsing**: The VMA verification in L3-SHM-09 is fragile:
   ```python
   if f"memfd:" in line or f"deleted" in line:
   ```
   This may break on different kernel versions or container environments.
   - **Recommendation**: Use more robust parsing or the `smaps_rollup` interface.

4. ✅ **Skip Decorators**: Properly uses `skip_unless_linux` and `skip_on_macos_*` for platform-specific tests.

5. ⚠️ **FD Counting**: `/proc/self/fd` listing may include spurious entries from pytest or subprocess handling.
   - **Recommendation**: Use `psutil` or `lsof` for more reliable FD counting.

**Verdict**: APPROVED with recommendations

---

## Phase III: The Verdict

### Summary

| Expert | Verdict | Issues |
|:---|:---:|:---:|
| 🔐 Security Engineer | ✅ APPROVED | 2 recommendations |
| 🐍 Python Core Dev | ✅ APPROVED | 2 recommendations |
| ⚡ HPC Engineer | ✅ APPROVED | 2 recommendations |
| 🐧 Linux Specialist | ✅ APPROVED | 3 recommendations |

### Final Decision

## ✅ APPROVED

The RFC-0015 QA Test Suite is **APPROVED** for merge.

### P0 Blocking Issues: **NONE**

### P1 Recommendations (Future Improvements)

| # | Issue | Owner |
|:---:|:---|:---|
| 1 | Add ptrace attack vector to L3-SHM-10 | QA |
| 2 | Add cross-tenant (cross-PID-namespace) negative test | QA |
| 3 | Refactor inline scripts to helper modules | QA |
| 4 | Add header_length=0 edge case to alignment test | QA |
| 5 | Use architecture-agnostic syscall numbers | QA |
| 6 | Improve /proc/maps parsing robustness | QA |

---

**Council Session Complete**
**Reviewed**: 7 files, 2765 lines
**Status**: 🟢 **MERGED APPROVED**
