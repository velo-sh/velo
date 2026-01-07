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

## 3. Security Invariant Matrix (QA-SOP §13)

### 3.1 Complete Invariant Registry (H-17 to H-30)

| ID | Invariant Name | Type | Test ID | Status |
|:---|:---|:---:|:---|:---:|
| **H-17** | Immutability | Standard | L3-SHM-06, L3-SHM-10 | 🔲 |
| **H-18** | Ownership | Standard | L2-SHM-08 | 🔲 |
| **H-19** | Write-Sealing (Linux) | Standard | L3-SHM-06 | 🔲 |
| **H-20** | HugePage Optimization | Standard | L2-SHM-05 | 🔲 |
| **H-21** | Liveness Guard (SIGBUS Prevention) | **CRITICAL** | L2-SHM-04 | 🔲 |
| **H-22** | Offset Validation | Standard | L0-SHM-01 | 🔲 |
| **H-23** | Seal Ordering | **CRITICAL** | L3-SHM-09 | 🔲 |
| **H-24** | Host-Only Lifecycle Authority | **CRITICAL** | L2-SHM-07, L2-SHM-08 | 🔲 |
| **H-25** | HugePage Safety Guard | **CRITICAL** | L2-SHM-05 | 🔲 |
| **H-26** | Host Death Containment | **CRITICAL** | L2-SHM-08 | 🔲 |
| **H-27** | FD Capability Containment | **CRITICAL** | L3-SHM-10 | 🔲 |
| **H-28** | Runtime Revertability | **CRITICAL** | L2-SHM-05 | 🔲 |
| **H-29** | Alignment Guarantee | **CRITICAL** | L4-SHM-11 | 🔲 |
| **H-30** | NUMA Affinity | **CRITICAL** | L4-SHM-12 | 🔲 |

**Summary**: 14 Invariants (9 CRITICAL, 5 Standard)

---

## 4. Test Tier Definition (QA-SOP §3.3)

| Tier | Focus | Tests | Run Frequency | Failure Policy |
|:---:|:---|:---|:---|:---|
| **L0** | Core Functionality | L0-SHM-01, L1-SHM-02 | Every commit | MUST PASS |
| **L2** | Scalability & Stability | L2-SHM-03 to L2-SHM-08 | Daily | SHOULD PASS |
| **L3** | Security | L3-SHM-06, L3-SHM-07, L3-SHM-09, L3-SHM-10 | Every release | MUST PASS |
| **L4** | HFT Performance | L4-SHM-11, L4-SHM-12 | Weekly/Release | MUST PASS |

---

## 5. Verification Plan (from RFC §6)

### 5.1 Tier 0: Core Functionality

| Test ID | Description | Target |
|:---|:---|:---|
| **L0-SHM-01** | RSS footprint verification (4 workers < 2x Model) | P0 |
| **L1-SHM-02** | Cold-start benchmark (Time to Token) | P0 |

### 5.2 Tier 2: Scalability & Stability

| Test ID | Description | Target |
|:---|:---|:---|
| **L2-SHM-03** | Multi-model scalability (10 workers, 3 models) | P1 |
| **L2-SHM-04** | Attach/detach storm (1000 cycles) | P1 |
| **L2-SHM-05** | TLB miss / HugePage profiling | P1 |
| **L2-SHM-08** | Host Restart Survivability | P0 |

### 5.3 Tier 3: Security

| Test ID | Description | Target |
|:---|:---|:---|
| **L3-SHM-06** | mprotect() bypass after F_SEAL_WRITE | P0 |
| **L3-SHM-07** | Worker crash recovery (no orphan leaks) | P0 |
| **L3-SHM-09** | Seal ordering verification (whitebox) | P0 |
| **L3-SHM-10** | Malicious worker (FD dup, PROT_WRITE, ptrace) | P0 |

### 5.4 Tier 4: HFT Performance

| Test ID | Description | Target |
|:---|:---|:---|
| **L4-SHM-11** | 64-byte alignment verification | P0 |
| **L4-SHM-12** | NUMA locality test (dual-socket) | P1 |

---

## 6. Known Limitations (from RFC §5)

| # | Limitation | QA Impact |
|:---:|:---|:---|
| 1 | GPU Tensors not covered | Skip GPU tests |
| 2 | ctypes/data_ptr() can bypass RO | Document as user responsibility |
| 3 | Multi-Tenant requires container isolation | Test only single-tenant |
| 4 | macOS has no kernel-level sealing | Skip L3 security tests on macOS |
| 5 | PyTorch ABI depends on dtype/alignment | Test supported dtypes only |
| 6 | Python RefCycle may delay FD close | Test explicit cleanup path |

---

## 7. Platform Matrix

| Platform | SHM Mechanism | Security Tests | Status |
|:---|:---|:---:|:---:|
| **Linux** | memfd_create + F_SEAL | Full L3/L4 | ✅ Primary |
| **macOS** | shm_open + mmap | L0/L2 only | ⚠️ Dev Only |
| **Windows** | N/A | N/A | ❌ Out of Scope |

---

## 8. Agent Assignment (QA-SOP §4.4)

| Agent | Focus | Tests |
|:---|:---|:---|
| **Agent A (Edge)** | Scale limits, boundary tests | L2-SHM-03, L2-SHM-04 |
| **Agent B (Stability)** | Crash recovery, lifecycle | L2-SHM-07, L2-SHM-08 |
| **Agent C (Security)** | Security invariants, attacks | L3-SHM-06 to L3-SHM-10 |
| **Leader** | Alignment, HFT verification | L4-SHM-11, L4-SHM-12 |

---

## 9. Dependencies Check

| Dependency | Required For | Verified |
|:---|:---|:---:|
| Rust (nightly 2024-12-09) | memfd_create bindings | 🔲 |
| Python 3.11+ | mmap tests | 🔲 |
| PyTorch 2.0+ | frombuffer tests | 🔲 |
| libnuma | NUMA tests (Linux) | 🔲 |
| numactl | NUMA simulation | 🔲 |

---

**Phase 0 Status**: ✅ COMPLETE

**Next Step**: Phase 1 - Test Design & Implementation

---

**QA Signature**: Velo QA Working Group (Phase 7.0)
**Date**: 2026-01-07
