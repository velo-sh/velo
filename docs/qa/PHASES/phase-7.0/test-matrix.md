# Phase 7.0 Test Matrix (RFC-0015: Memory Gravity)

> **QA-SOP Reference**: §12
> **Date**: 2026-01-07
> **Total Tests**: 12

---

## 1. RFC-to-Test Mapping (QA-SOP §12.1)

| Requirement | RFC Section | Test ID | Status |
|:---|:---:|:---|:---:|
| H-17: Immutability | §4.1 | L3-SHM-06, L3-SHM-10 | 🔲 |
| H-18: Ownership | §4.1 | L2-SHM-08 | 🔲 |
| H-19: Write-Sealing | §4.1 | L3-SHM-06 | 🔲 |
| H-20: HugePage Optimization | §4.2 | L2-SHM-05 | 🔲 |
| H-21: Liveness Guard | §4.2 | L2-SHM-04 | 🔲 |
| H-22: Offset Validation | §4.1 | L0-SHM-01 | 🔲 |
| H-23: Seal Ordering | §4.2 | L3-SHM-09 | 🔲 |
| H-24: Host-Only Lifecycle | §4.3 | L2-SHM-07, L2-SHM-08 | 🔲 |
| H-25: HugePage Safety | §4.3 | L2-SHM-05 | 🔲 |
| H-26: Host Death Containment | §4.4 | L2-SHM-08 | 🔲 |
| H-27: FD Containment | §4.4 | L3-SHM-10 | 🔲 |
| H-28: Runtime Revertability | §4.5 | L2-SHM-05 | 🔲 |
| H-29: Alignment Guarantee | §4.6 | L4-SHM-11 | 🔲 |
| H-30: NUMA Affinity | §4.7 | L4-SHM-12 | 🔲 |

**Coverage**: 14/14 Requirements = **100%**

---

## 2. Complete Test Specification

### 2.1 Tier 0: Core Functionality (MUST PASS)

#### L0-SHM-01: RSS Footprint Verification

**Objective**: Verify Memory Gravity achieves shared memory (not N×Model copies)

**Test Steps**:
1. Start Velo Host with a 1GB model in SHM
2. Spawn 4 workers, each attaching to SHM
3. Measure total RSS of all processes

**Acceptance Criteria**:
- Total RSS < `Model_Size * 1.5` (allowing for overhead)
- NOT `4 * Model_Size`

**Platform**: Linux, macOS

---

#### L1-SHM-02: Cold-Start Benchmark (Time-to-Token)

**Objective**: Verify forked workers achieve sub-50ms attachment

**Test Steps**:
1. Pre-load model in SHM via Velo Host
2. Fork worker
3. Measure time from fork to first tensor access

**Acceptance Criteria**:
- Attachment time < 50ms
- vs. traditional torch.load() baseline (~5s for 1GB)

**Platform**: Linux, macOS

---

### 2.2 Tier 2: Scalability & Stability

#### L2-SHM-03: Multi-Model Scalability

**Objective**: Verify 10 workers × 3 models scale correctly

**Test Steps**:
1. Load 3 different models (100MB each) in SHM
2. Spawn 10 workers, each attached to 1+ models
3. Run concurrent inference
4. Check for race conditions or corruption

**Acceptance Criteria**:
- All 10 workers complete inference
- No SIGBUS/SIGSEGV
- RSS remains bounded

**Platform**: Linux

---

#### L2-SHM-04: Attach/Detach Storm (H-21 Verification)

**Objective**: Verify 1000 rapid attach/detach cycles don't leak

**Test Steps**:
1. Create SHM segment
2. Loop 1000 times: spawn worker → attach → detach → kill
3. Monitor FD count and memory

**Acceptance Criteria**:
- Zero FD leak
- Zero memory leak
- No SIGBUS

**Platform**: Linux

---

#### L2-SHM-05: TLB Miss Profiling (HugePages)

**Objective**: Verify HugePage optimization reduces TLB misses

**Test Steps**:
1. Run inference WITHOUT HugePages → record TLB misses (perf stat)
2. Run inference WITH HugePages → record TLB misses
3. Compare

**Acceptance Criteria**:
- HugePage mode shows ≥30% fewer TLB misses
- OR graceful fallback if HUGETLB unavailable

**Platform**: Linux only

---

#### L2-SHM-07: Worker Crash Recovery

**Objective**: Verify Host handles worker crash gracefully

**Test Steps**:
1. Host creates SHM, shares with worker
2. Worker attaches, then SIGKILL'd mid-operation
3. Host detects crash via waitpid()
4. Host decrements refcount

**Acceptance Criteria**:
- No SHM orphan leak
- Host remains stable
- Next worker can attach

**Platform**: Linux, macOS

---

#### L2-SHM-08: Host Restart Survivability (H-26 Verification)

**Objective**: Verify SHM cleanup on Host death

**Test Steps**:
1. Start Host in PID namespace (if available) or container
2. Share SHM with 3 workers
3. SIGKILL Host
4. Verify all workers receive SIGKILL (PID namespace) OR SHM is cleaned

**Acceptance Criteria**:
- No stale memfd survives after Host death
- Workers terminated (if PID namespace) OR SHM inaccessible

**Platform**: Linux (requires PID namespace)

---

### 2.3 Tier 3: Security (MUST PASS)

#### L3-SHM-06: mprotect() Bypass After Sealing (H-17, H-19)

**Objective**: Verify sealed SHM cannot be made writable

**Test Steps**:
1. Host creates sealed SHM (F_SEAL_WRITE)
2. Pass FD to worker
3. Worker attempts `mprotect(ptr, size, PROT_READ | PROT_WRITE)`

**Acceptance Criteria**:
- `mprotect()` returns `EPERM`
- Memory remains read-only

**Platform**: Linux only (macOS has no sealing)

---

#### L3-SHM-09: Seal Ordering Verification (H-23 Whitebox)

**Objective**: Verify exact 8-step seal sequence is followed

**Test Steps**:
1. Instrument or strace the Host SHM creation
2. Verify sequence:
   - memfd_create()
   - mmap(PROT_WRITE)
   - populate weights
   - munmap()
   - mmap(PROT_READ)
   - verify /proc/self/maps (no writable VMAs)
   - F_ADD_SEALS
   - pass FD

**Acceptance Criteria**:
- Steps 4-6 occur BEFORE step 7
- No writable VMA exists at sealing time

**Platform**: Linux only

---

#### L3-SHM-10: Malicious Worker Simulation (H-27)

**Objective**: Verify all write attacks fail against sealed SHM

**Test Steps**:
1. Host creates sealed SHM
2. Fork "attacker" worker
3. Attacker attempts:
   - `mprotect(PROT_WRITE)` → MUST FAIL
   - `write(fd, data, len)` → MUST FAIL  
   - `ftruncate(fd, 0)` → MUST FAIL
   - `dup(fd)` + pass to another process → permitted, but write still fails
   - ptrace attach → permitted on self, but memory still RO

**Acceptance Criteria**:
- ALL write attempts return `EPERM` or `EACCES`
- Memory integrity preserved

**Platform**: Linux only

---

### 2.4 Tier 4: HFT Performance (P0)

#### L4-SHM-11: 64-Byte Alignment Verification (H-29)

**Objective**: Verify all tensor offsets are 64-byte aligned

**Test Steps**:
1. Generate safetensors with varying header lengths: [1, 63, 64, 65, 127, 128, 1023]
2. Load via Velo's alignment-aware writer
3. For each tensor, compute: `(mmap_base + offset) % 64`

**Acceptance Criteria**:
- Result is **0 for ALL tensors**
- No silent PyTorch copy detected

**Platform**: Linux, macOS

---

#### L4-SHM-12: NUMA Locality Test (H-30)

**Objective**: Verify worker CPU matches SHM NUMA node

**Environment**: Dual-socket machine OR `numactl` simulation

**Test Steps**:
1. Host allocates SHM on NUMA Node 0 (`mbind`)
2. Spawn worker with CPU pinned to Node 0
3. Read `/proc/<worker_pid>/numa_maps`
4. Verify all pages are on Node 0

**Acceptance Criteria**:
- Worker CPU Node == SHM Page Node
- Zero cross-socket memory access

**Platform**: Linux only (dual-socket or numactl)

---

## 3. Test File Structure (QA-SOP §4.1)

```
tests/qa/phase_7_0/
├── conftest.py                        # SHM fixtures
├── test_phase7_0_core.py              # L0-SHM-01, L1-SHM-02
├── test_phase7_0_scalability.py       # L2-SHM-03, L2-SHM-04, L2-SHM-05
├── test_phase7_0_lifecycle.py         # L2-SHM-07, L2-SHM-08
├── test_phase7_0_security.py          # L3-SHM-06, L3-SHM-09, L3-SHM-10
└── test_phase7_0_hft.py               # L4-SHM-11, L4-SHM-12
```

---

## 4. Platform Skip Matrix

| Test ID | Linux | macOS | Skip Reason |
|:---|:---:|:---:|:---|
| L0-SHM-01 | ✅ | ✅ | |
| L1-SHM-02 | ✅ | ✅ | |
| L2-SHM-03 | ✅ | ⚠️ | macOS: reduced scale |
| L2-SHM-04 | ✅ | ✅ | |
| L2-SHM-05 | ✅ | ⏭️ SKIP | macOS: no HugePages |
| L2-SHM-07 | ✅ | ✅ | |
| L2-SHM-08 | ✅ | ⏭️ SKIP | macOS: no PID namespace |
| L3-SHM-06 | ✅ | ⏭️ SKIP | macOS: no F_SEAL |
| L3-SHM-09 | ✅ | ⏭️ SKIP | macOS: no F_SEAL |
| L3-SHM-10 | ✅ | ⏭️ SKIP | macOS: no kernel protection |
| L4-SHM-11 | ✅ | ✅ | |
| L4-SHM-12 | ✅ | ⏭️ SKIP | macOS: single-node |

---

## 5. Execution Order (Fail-Fast)

```
L0-SHM-01 ──PASS──▶ L1-SHM-02 ──PASS──▶ L2-* ──PASS──▶ L3-* ──PASS──▶ L4-*
    │                    │                │               │
  FAIL                 FAIL             FAIL            FAIL
    │                    │                │               │
    ▼                    ▼                ▼               ▼
  STOP                 STOP            STOP             STOP
```

---

**QA Signature**: Velo QA Working Group (Phase 7.0)
**Date**: 2026-01-07
