# Handover: QA (Phase 7.0 - Memory Gravity Verification)

> **Mission**: Prove that Memory Gravity is **TITANIUM-Grade** (Unbreakable).
> **Role**: QA Engineer (ID-LOCK-003)
> **Compliance**: **Zero-False-Negative**. If a test passes but the implementation has a bug, the test is useless.

## 1. Test Matrix Overview (TITANIUM)

| Tier | Focus | Key Tests |
| :--- | :--- | :--- |
| **L0** | Core Function | `L0-SHM-01` (RSS), `L1-SHM-02` (Latency) |
| **L2** | Scalability | `L2-SHM-03` (10 workers), `L2-SHM-08` (Host Restart) |
| **L3** | Security | `L3-SHM-09` (Seal Order), `L3-SHM-10` (Malicious Worker) |
| **L4** | HFT Perf | `L4-SHM-11` (Alignment), `L4-SHM-12` (NUMA) |

---

## 2. Critical Test Specs

### A. Security (The "Red Team")

**L3-SHM-10: Malicious Worker Simulation**
- **Objective**: Verify H-17 (Immutability) and H-19 (Sealing).
- **Steps**:
  1. Set up a Host with a sealed SHM segment.
  2. Spawn a specialized "Attacker" worker (using `ctypes` or `ptrace`).
  3. Attempt to `mmap(..., PROT_WRITE)`.
  4. Attempt to `write(fd, ...)`.
  5. Attempt to use `mprotect()` to flip permission.
- **Verdict**: PASS only if ALL attempts return `EPERM` or `EACCES`.

**L3-SHM-09: Seal Ordering (Whitebox Check)**
- **Objective**: Verify H-23 (Seal Ordering).
- **Steps**:
  1. Instrument the Host logic (or use `strace` wrapper).
  2. Assert that `munmap(RW)` happens BEFORE `F_ADD_SEALS`.
  3. Assert that NO writable VMA exists for the `memfd` at the moment of sealing.

### B. Performance (The "HFT Team")

**L4-SHM-11: 64-byte Alignment**
- **Objective**: Verify H-29 (Alignment Guarantee).
- **Steps**:
  1. Create synthetic safetensors with header lengths `[1, 63, 64, 65, 1023]`.
  2. Load them via `ShmRegistry`.
  3. For each tensor, calculate: `(mmap_base + offset) % 64`.
- **Verdict**: PASS only if result is 0 for ALL tensors.

**L4-SHM-12: NUMA Locality**
- **Objective**: Verify H-30 (NUMA Affinity).
- **Environment**: Dual-socket machine (or simulated via `numactl`).
- **Steps**:
  1. Start Velo Host on Node 0.
  2. Allocate 10GB SHM.
  3. Spawn Worker.
  4. Check `/proc/<worker_pid>/status` -> `Cpus_allowed_list`.
  5. Check `/proc/<worker_pid>/numa_maps`.
- **Verdict**: PASS only if Worker CPU Node == SHM Page Node.

---

## 3. The "Day 2" Risk Watchlist

Monitor these metrics during load testing:
1. **SIGBUS Rate**: If > 0, H-31 (Execution Barrier) is failing.
2. **NUMA Miss Rate**: If > 1%, H-30 is failing (silent perf killer).
3. **Dirty Page Count**: If > 0 for SHM, H-17 (Immutability) is broken.

## 4. Final Sign-off Criteria
- All L0-L4 tests PASS.
- No "Skipped" tests on Linux (macOS skips allowed).
- **Audit**: Review code for `memcpy` calls. There should be ZERO copies in the hot path.
