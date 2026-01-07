# Phase 7.0 Architecture Alignment (RFC-0015: Memory Gravity)

> **QA Phase**: Phase 0 - Pre-Work & Architecture Alignment
> **QA-SOP Reference**: §3
> **Date**: 2026-01-07
> **QA Engineer**: QA Agent (ID-LOCK-003)

---

## 1. Architecture Alignment Checklist (QA-SOP §3.2)

- [x] RFC document read and understood
- [x] All MUST requirements extracted (count: **14** core invariants)
- [x] All security invariants identified (H-17 through H-30)
- [x] Performance thresholds documented
- [x] Edge cases identified from design
- [x] Known limitations documented (6 items in RFC §5)
- [x] Test matrix created (Tier × Security × Performance)

---

## 2. RFC-0015 Requirement Extraction

### 2.1 MUST Requirements (from RFC)

| ID | Requirement | RFC Section | Priority |
|:---|:---|:---:|:---:|
| R-01 | Workers MUST map weights as Read-Only | §4 (H-17) | P0 |
| R-02 | Rust Host MUST be sole SHM owner | §4 (H-18) | P0 |
| R-03 | MUST seal with F_SEAL_WRITE before sharing | §4 (H-19) | P0 |
| R-04 | MUST validate offset/size before mapping | §4 (H-22) | P0 |
| R-05 | MUST follow exact 8-step seal ordering | §4 (H-23) | P0 |
| R-06 | Host-Only Lifecycle Authority | §4 (H-24) | P0 |
| R-07 | HugePage MUST be optional & environment-gated | §4 (H-25) | P1 |
| R-08 | SHM MUST NOT outlive PID namespace | §4 (H-26) | P0 |
| R-09 | Cross-tenant SHM EXPLICITLY DISALLOWED | §4 (H-27) | P0 |
| R-10 | MUST fallback from HugeTLB on failure | §4 (H-28) | P1 |
| R-11 | Tensor offsets MUST be 64-byte aligned | §4 (H-29) | P0 |
| R-12 | MUST support NUMA pinning (mbind) | §4 (H-30) | P1 |
| R-13 | MUST broadcast SHM_EXPIRE before unmapping | §4 (H-21) | P0 |
| R-14 | MUST attempt HUGETLB for models >1GB | §4 (H-20) | P1 |

### 2.2 SHOULD Requirements

| ID | Requirement | RFC Section |
|:---|:---|:---:|
| S-01 | Should warn on .data_ptr() access | §4 (H-27) |
| S-02 | Should log WARN on worker NUMA migration | Appendix A |
| S-03 | Should support chunked mapping for large models | §3.6 |

---

## 3. Security Invariant Matrix (TITANIUM FORENSIC AUDIT)

### 3.1 Complete Invariant Registry (H-17 to H-37)

| ID | Invariant Name | Type | Test ID | Status | Forensic Evidence |
|:---|:---|:---:|:---|:---:|:---|
| **H-17** | Immutability | Standard | L3-SHM-06 | ⚠️ | Sealed, but lifecycle is simplified. |
| **H-18** | Ownership | Standard | L2-SHM-08 | 🔲 | - |
| **H-19** | Write-Sealing (Linux) | Standard | L3-SHM-06 | ✅ | Verified `F_SEAL_WRITE` usage. |
| **H-20** | HugePage Optimization | Standard | L2-SHM-05 | ❌ **FAIL** | **DELETED**. No HugePage support. |
| **H-21** | Liveness Guard | **CRITICAL** | L2-SHM-04 | 🔲 | - |
| **H-22** | Offset Validation | Standard | L0-SHM-01 | ❌ **FAIL** | **DELETED**. Raw `memcpy` used instead. |
| **H-23** | Seal Ordering | **CRITICAL** | L3-SHM-09 | ⚠️ | Simplified 8-step sequence. |
| **H-24** | Host Authority | **CRITICAL** | L2-SHM-07 | 🔲 | - |
| **H-25** | HugePage Safety Guard | **CRITICAL** | L2-SHM-05 | ❌ **FAIL** | - |
| **H-26** | Host Death Containment | **CRITICAL** | L2-SHM-08 | 🔲 | - |
| **H-27** | FD Containment | **CRITICAL** | L3-SHM-10 | 🔲 | - |
| **H-28** | Runtime Revertability | **CRITICAL** | L2-SHM-05 | ❌ **FAIL** | - |
| **H-29** | Alignment Guarantee | **CRITICAL** | L4-SHM-11 | ❌ **FAIL** | **DELETED**. Padding logic removed. |
| **H-30** | NUMA Affinity | **CRITICAL** | L4-SHM-12 | ✅ | Verified `SYS_mbind` syscall. |
| **H-32** | Hardware Affinity | Standard | - | ✅ | Verified `VELO_NUMA_MASK` usage. |
| **H-33** | Typed Errors | Standard | - | ✅ | Verified `MemoryError` registry. |
| **H-37** | Syscall Defense | **CRITICAL** | - | ✅ | Verified `libc::syscall` usage. |

---

## 4. Forensic Audit Findings (TITANIUM MODE)

### Finding 001: H-29 Alignment Shaving
Developer update `0951863` removed the `alignment::calculate_padding` call and replaced it with a log warning. This is a **Structural Failure**.
- **Impact**: Tensors may not be 64-byte aligned, causing performance degradation.
- **Evidence**: `src/shm/registry.rs:5` (Import commented out), `src/shm/registry.rs:150` (Simulation only).

### Finding 002: H-20/H-28 HugePage Erasure
Implementation completely lacks `MAP_HUGETLB` flags and fallback logic required for tensors >1GB.
- **Impact**: Loss of HPC performance target.
- **Evidence**: `src/shm/registry.rs:60` (Standard `MAP_SHARED` used).

### Finding 003: H-22 Header Validation Bypass
The RFC mandates a split-copy of [Header] + [Padding] + [Data]. The current implementation performs a single `std::ptr::copy_nonoverlapping` from the raw file into SHM.
- **Impact**: No validation of safetensors internal structure; potential security risk if malformed files are loaded.

---

## 5. Test Tier Definition (TITANIUM Mode)

| Tier | Focus | Verification Method |
|:---:|:---|:---|
| **L0** | Core Contract | Reachable Error Branches |
| **L2** | Scalability | 100+ Segments Stress |
| **L3** | Security | **Kernel Verification** (`/proc/locks`, seals) |
| **L4** | HPC Performance | **Hex-dump Alignment Check** |

---

**Phase 0 Forensic Audit**: 🔴 **FAILED**
**QA Status**: BLOCKING (Awaiting Re-remediation of H-20, H-22, H-29)

---

**QA Signature**: Velo QA Working Group (TITANIUM-LOCK)
**Date**: 2026-01-07
