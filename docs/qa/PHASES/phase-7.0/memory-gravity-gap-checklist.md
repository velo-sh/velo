# Memory Gravity (RFC-0015) Gap Verification Checklist

> **Status**: 🟡 Pending QA
> **Target**: v0.7.x GA
> **Last Updated**: 2026-01-19

---

## 1. Overview

RFC-0015 Memory Gravity has been implemented and marked as "Implemented" in v0.7.0. However, several Day 2 verification gaps remain before declaring production-ready (GA) status.

### Current Test Coverage

| Invariant | Test File | Status |
|:---|:---|:---|
| H-17 (SHM ReadOnly) | `tests/qa/phase_7_0/test_SEC_H17_shm_readonly.py` | ✅ |
| H-29 (64-byte Alignment) | `tests/shm_tests.rs::test_alignment_logic` | ✅ |
| H-29 (Padding Enforcement) | `tests/shm_tests.rs::test_registry_enforces_padding` | ✅ |
| H-20 (HugePage Alignment) | `tests/shm_tests.rs::test_shm_alignment_rounding` | ✅ |

---

## 2. Gap Verification Tasks

### 2.1 [P1] PyTorch Silent Copy Detection

**RFC Reference**: RFC-0015 Appendix A, Directive 3

**Problem**: PyTorch may silently copy tensor data if alignment/stride doesn't match its internal requirements, breaking the zero-copy guarantee.

**Task**:
- [ ] Create `tests/qa/phase_7_0/test_L4_SHM_11_pytorch_zerocopy.py`
- [ ] Verify `tensor.storage().data_ptr() == mmap_base + expected_offset`
- [ ] Assert no silent copy occurs for standard dtypes (float32, float16, bfloat16)

**Acceptance Criteria**:
```python
def test_pytorch_zerocopy_verification():
    # Load tensor via Velo SHM
    tensor = velo_load_tensor(shm_path)
    # Verify pointer matches mmap base
    assert tensor.storage().data_ptr() == expected_ptr, "Silent copy detected!"
```

---

### 2.2 [P2] Malicious Worker FD Attack

**RFC Reference**: RFC-0015 H-27 (FD Capability Containment)

**Problem**: A malicious worker may attempt to `dup()` the FD or write via `mprotect()`.

**Task**:
- [ ] Create `tests/qa/phase_7_0/test_L3_SHM_10_malicious_worker.py`
- [ ] Attempt `fcntl.dup(shm_fd)` - should succeed (expected behavior)
- [ ] Attempt `mmap(PROT_WRITE)` on sealed FD - must fail with EPERM
- [ ] Attempt `ctypes.memmove()` to read-only region - must SIGBUS/SIGSEGV

**Acceptance Criteria**:
- Write attempts to sealed SHM must raise OSError or signal
- Test must run in isolated subprocess to avoid crashing test runner

---

### 2.3 [P3] NUMA Locality Verification

**RFC Reference**: RFC-0015 H-30 (NUMA Affinity)

**Problem**: On multi-socket machines, cross-NUMA memory access incurs 30-50% latency penalty.

**Task**:
- [ ] Create `tests/qa/phase_7_0/test_L4_SHM_12_numa_locality.py`
- [ ] Skip if `numa.available() == False` or single-socket
- [ ] Measure memory access latency for local vs remote NUMA node
- [ ] Assert local access is faster by measurable margin

**Acceptance Criteria**:
- Test is skipped gracefully on single-socket machines
- On multi-socket: local access < remote access (within measurement noise)

---

### 2.4 [P2] Velo Doctor Runtime Check

**RFC Reference**: RFC-0015 Appendix A, Directive 3

**Problem**: Users need runtime verification that zero-copy is actually working.

**Task**:
- [ ] Add `velo doctor --check-shm` command
- [ ] Verify alignment of all loaded tensors
- [ ] Report any silent copies detected
- [ ] Output: `✅ All tensors verified zero-copy` or `⚠️ N tensors copied`

---

## 3. Non-Blocking Future Work

| Item | RFC Section | Priority |
|:---|:---|:---|
| H-31 (Execution Barrier) | Appendix C.1 | P3 - v1.0 |
| Multi-FD Sharding (>140GB) | Appendix D.1 | P3 - When needed |
| GPU CUDA IPC | Appendix D.3 | P4 - Out of scope |

---

**Custodian**: QA Engineer
**Review By**: Architect
